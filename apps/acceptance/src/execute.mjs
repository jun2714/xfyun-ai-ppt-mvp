import { execFile } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { basename, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { promisify } from "node:util";
import sharp from "sharp";

const run = promisify(execFile);
const digest = (value) => createHash("sha256").update(value).digest("hex");
const safeSlug = (value) => value.normalize("NFKC").replace(/[^\p{L}\p{N}]+/gu, "-").replace(/^-|-$/g, "").slice(0, 48) || "acceptance";

async function exportSlides(pptxPath, outputDirectory, programId) {
  await mkdir(outputDirectory, { recursive: true });
  const script = "$ErrorActionPreference='Stop';$app=$null;$deck=$null;try{$app=New-Object -ComObject $env:SPARKDECK_OFFICE_PROGRAM_ID;$deck=$app.Presentations.Open($env:SPARKDECK_RENDER_PPTX,$true,$true,$false);[System.Threading.Thread]::Sleep(800);$deck.Export($env:SPARKDECK_RENDER_IMAGES,'PNG',1280,720)}finally{if($null-ne$deck){$deck.Close()};if($null-ne$app){$app.Quit()}}";
  await run("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", script], { windowsHide: true, timeout: 120_000, env: { ...process.env, SPARKDECK_OFFICE_PROGRAM_ID: programId, SPARKDECK_RENDER_PPTX: pptxPath, SPARKDECK_RENDER_IMAGES: outputDirectory } });
}

async function contactSheet(slidesDirectory, outputPath) {
  const files = (await readdir(slidesDirectory)).filter((name) => /\d+\.png$/i.test(name)).sort((a, b) => Number(a.match(/\d+/)?.[0]) - Number(b.match(/\d+/)?.[0]));
  if (!files.length) throw new Error(`No rendered slides in ${slidesDirectory}`);
  const width = 400, height = 225, columns = Math.min(3, files.length), rows = Math.ceil(files.length / columns);
  const layers = await Promise.all(files.map(async (name, index) => ({ input: await sharp(resolve(slidesDirectory, name)).resize(width, height, { fit: "fill" }).png().toBuffer(), left: index % columns * width, top: Math.floor(index / columns) * height })));
  await sharp({ create: { width: columns * width, height: rows * height, channels: 3, background: "#111827" } }).composite(layers).png().toFile(outputPath);
}

export async function executeAcceptance({ repositoryRoot, briefPath, outputDirectory }) {
  const briefBytes = await readFile(briefPath);
  const brief = JSON.parse(briefBytes.toString("utf8"));
  const directory = resolve(outputDirectory, safeSlug(brief.title));
  await mkdir(directory, { recursive: true });
  const freeze = {
    frozenAt: new Date().toISOString(), briefPath: basename(briefPath), briefHash: digest(briefBytes),
    promptHashes: Object.fromEntries(await Promise.all(["narrative", "design", "image", "visual-quality"].map(async (name) => [name, digest(await readFile(resolve(repositoryRoot, `apps/api/prompts/009/${name}.prompt.txt`)))]))),
    sourceDiffHash: digest((await run("git", ["diff", "--binary"], { cwd: repositoryRoot, windowsHide: true, maxBuffer: 32 * 1024 * 1024 })).stdout)
  };
  await writeFile(resolve(directory, "freeze-manifest.json"), JSON.stringify(freeze, null, 2));
  const { buildApp } = await import(pathToFileURL(resolve(repositoryRoot, "apps/api/dist/app.js")).href);
  const app = buildApp();
  const request = async (method, url, body) => {
    const response = await app.inject({ method, url, ...(body ? { payload: body } : {}) });
    const parsed = response.headers["content-type"]?.includes("json") ? response.json() : undefined;
    if (response.statusCode >= 400) throw new Error(`${parsed?.error?.code ?? response.statusCode}: ${parsed?.error?.message ?? response.body}`);
    return parsed?.data ?? parsed ?? response;
  };
  const waitJob = async (jobId) => {
    while (true) {
      const job = await request("GET", `/api/v1/jobs/${jobId}`);
      if (job.status === "succeeded") return job;
      if (job.status === "failed") throw new Error(`${job.error?.code ?? "JOB_FAILED"}: ${job.error?.message ?? "job failed"}`);
      await new Promise((done) => setTimeout(done, 500));
    }
  };
  const start = async (path, payload = {}) => waitJob((await request("POST", path, { idempotencyKey: randomUUID(), ...payload })).id);
  let presentationId;
  try {
    const created = await request("POST", "/api/v1/presentations", brief); presentationId = created.id;
    await start(`/api/v1/presentations/${presentationId}/narrative-jobs`);
    let state = await request("GET", `/api/v1/presentations/${presentationId}`);
    await writeFile(resolve(directory, "narrative.json"), JSON.stringify(state.outline, null, 2));
    await request("POST", `/api/v1/presentations/${presentationId}/outline/confirm`, { idempotencyKey: randomUUID(), expectedRevision: state.outline.revision });
    await start(`/api/v1/presentations/${presentationId}/design-jobs`);
    await start(`/api/v1/presentations/${presentationId}/composition-jobs`, { canvas: { width: 960, height: 540 } });
    await start(`/api/v1/presentations/${presentationId}/asset-jobs`);
    await start(`/api/v1/presentations/${presentationId}/quality-jobs`);
    state = await request("GET", `/api/v1/presentations/${presentationId}`);
    const usage = await request("GET", `/api/v1/presentations/${presentationId}/usage`);
    await writeFile(resolve(directory, "state-before-export.json"), JSON.stringify(state, null, 2));
    await writeFile(resolve(directory, "usage-ledger.json"), JSON.stringify(usage, null, 2));
    if (!state.quality?.passed) throw new Error(`QUALITY_GATE_FAILED:${JSON.stringify(state.quality?.issues ?? [])}`);
    const exported = await app.inject({ method: "POST", url: `/api/v1/presentations/${presentationId}/exports`, payload: { idempotencyKey: randomUUID(), expectedRevision: state.scene.revision } });
    if (exported.statusCode >= 400) throw new Error(`EXPORT_FAILED:${exported.body}`);
    const pptxPath = resolve(directory, `${safeSlug(brief.title)}.pptx`); await writeFile(pptxPath, exported.rawPayload);
    const wps = resolve(directory, "wps-slides"), powerpoint = resolve(directory, "powerpoint-slides");
    await exportSlides(pptxPath, wps, "KWPP.Application"); await exportSlides(pptxPath, powerpoint, "PowerPoint.Application");
    await contactSheet(wps, resolve(directory, "wps-contact-sheet.png")); await contactSheet(powerpoint, resolve(directory, "powerpoint-contact-sheet.png"));
    const report = { passed: true, presentationId, briefHash: freeze.briefHash, pptxHash: digest(exported.rawPayload), pageCount: state.scene.pages.length, quality: state.quality, usage, estimatedCostRmb: usage.reduce((sum, item) => sum + item.estimatedCostRmb, 0) };
    await writeFile(resolve(directory, "acceptance-report.json"), JSON.stringify(report, null, 2));
    return { directory, report };
  } catch (error) {
    const failure = { passed: false, frozen: true, presentationId, error: error instanceof Error ? error.message : String(error) };
    await writeFile(resolve(directory, "failure.json"), JSON.stringify(failure, null, 2));
    throw error;
  } finally { await app.close(); }
}
