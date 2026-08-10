import { randomUUID } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { basename, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const repositoryRoot = resolve(process.cwd());
try { process.loadEnvFile(resolve(repositoryRoot, ".env")); } catch (error) {
  if (error?.code !== "ENOENT") throw error;
}

// This smoke run deliberately uses the stable 008 prompt contract and a separate
// data directory. It must not read or mutate the abandoned 009 acceptance state.
process.env.PROMPT_DIRECTORY = resolve(repositoryRoot, "apps/api/prompts/008");
process.env.DATA_DIRECTORY = resolve(repositoryRoot, ".runtime/text-only-smoke/data");
process.env.NODE_ENV = "development";

const briefPaths = process.argv.slice(2);
if (briefPaths.length < 1) throw new Error("Pass at least one Brief JSON file or presentation ID");

await import(pathToFileURL(resolve(repositoryRoot, "apps/api/dist/app.js")).href);
const { buildApp } = await import(pathToFileURL(resolve(repositoryRoot, "apps/api/dist/app.js")).href);
const { exportSceneToPptx } = await import(pathToFileURL(resolve(repositoryRoot, "packages/pptx-export/dist/index.js")).href);
const { evaluateScene } = await import(pathToFileURL(resolve(repositoryRoot, "packages/quality-engine/dist/index.js")).href);

const outputRoot = resolve(repositoryRoot, ".runtime/text-only-smoke/output");
await mkdir(outputRoot, { recursive: true });

const safeName = (value) => value.normalize("NFKC").replace(/[^\p{L}\p{N}]+/gu, "-").replace(/^-|-$/g, "").slice(0, 60);

async function runBrief(briefPath) {
  const app = buildApp();
  let brief;
  const request = async (method, url, payload) => {
    const response = await app.inject({ method, url, ...(payload ? { payload } : {}) });
    const body = response.headers["content-type"]?.includes("json") ? response.json() : undefined;
    if (response.statusCode >= 400) throw new Error(`${body?.error?.code ?? response.statusCode}: ${body?.error?.message ?? response.body}`);
    return body?.data ?? body;
  };
  const waitJob = async (jobId) => {
    for (;;) {
      const job = await request("GET", `/api/v1/jobs/${jobId}`);
      if (job.status === "succeeded") return;
      if (job.status === "failed") throw new Error(`${job.error?.code ?? "JOB_FAILED"}: ${job.error?.message ?? "job failed"}`);
      await new Promise((done) => setTimeout(done, 250));
    }
  };
  const start = async (url, payload = {}) => waitJob((await request("POST", url, { idempotencyKey: randomUUID(), ...payload })).id);

  try {
    let created;
    let state;
    if (briefPath.startsWith("pres_")) {
      created = { id: briefPath };
      state = await request("GET", `/api/v1/presentations/${created.id}`);
      brief = state.brief;
      if (!state.outline?.confirmedAt) throw new Error("Resume requires a confirmed outline");
    } else {
      brief = JSON.parse(await readFile(resolve(briefPath), "utf8"));
      created = await request("POST", "/api/v1/presentations", brief);
      await start(`/api/v1/presentations/${created.id}/narrative-jobs`);
      state = await request("GET", `/api/v1/presentations/${created.id}`);
      await request("POST", `/api/v1/presentations/${created.id}/outline/confirm`, { idempotencyKey: randomUUID(), expectedRevision: state.outline.revision });
    }
    if (!state.design) await start(`/api/v1/presentations/${created.id}/design-jobs`);
    await start(`/api/v1/presentations/${created.id}/composition-jobs`, { canvas: { width: 960, height: 540 } });
    state = await request("GET", `/api/v1/presentations/${created.id}`);

    // No asset job is called. Any media request is a failure because this run
    // proves the text-only path rather than silently spending image tokens.
    const mediaRequests = state.design.intents.flatMap((intent) => intent.mediaRequests);
    if (mediaRequests.length) throw new Error(`TEXT_ONLY_CONTRACT_VIOLATION: model requested ${mediaRequests.length} media assets`);

    const quality = evaluateScene(state.scene, { outline: state.outline });
    const artifact = await exportSceneToPptx(state.scene);
    const usage = await request("GET", `/api/v1/presentations/${created.id}/usage`);
    const deckDirectory = resolve(outputRoot, safeName(brief.title));
    await mkdir(deckDirectory, { recursive: true });
    const pptxPath = resolve(deckDirectory, `${safeName(brief.title)}-${created.id.slice(-8)}.pptx`);
    await writeFile(pptxPath, artifact.bytes);
    const report = {
      passed: true,
      brief: briefPath.startsWith("pres_") ? briefPath : basename(briefPath),
      presentationId: created.id,
      title: brief.title,
      pageCount: state.scene.pages.length,
      textCalls: usage.filter((entry) => entry.purpose === "narrative" || entry.purpose === "design").length,
      imageCalls: usage.filter((entry) => entry.purpose.includes("image")).length,
      estimatedCostRmb: usage.reduce((sum, entry) => sum + entry.estimatedCostRmb, 0),
      qualityPassed: quality.passed,
      qualityIssues: quality.issues,
      pptxPath
    };
    await writeFile(resolve(deckDirectory, "report.json"), JSON.stringify(report, null, 2));
    await writeFile(resolve(deckDirectory, "outline.json"), JSON.stringify(state.outline, null, 2));
    return report;
  } finally {
    await app.close();
  }
}

const reports = [];
for (const briefPath of briefPaths) reports.push(await runBrief(briefPath));
await writeFile(resolve(outputRoot, "summary.json"), JSON.stringify(reports, null, 2));
console.log(JSON.stringify(reports, null, 2));
