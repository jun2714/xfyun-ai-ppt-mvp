import { execFile } from "node:child_process";
import { mkdir, readdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { promisify } from "node:util";
import sharp from "sharp";
import { buildApp } from "../apps/api/dist/app.js";
import { OfficeRenderEvidenceAdapter } from "../apps/api/dist/infrastructure/rendering/office-render-evidence.adapter.js";

try { process.loadEnvFile(resolve(".env")); } catch (error) { if (error?.code !== "ENOENT") throw error; }

const run = promisify(execFile);
const root = resolve(process.argv[2] ?? ".runtime/008-acceptance");
const app = buildApp();

const briefs = [
  { slug: "child-classroom", title: "颜色会牵手：三原色混合探索", audience: "幼儿园大班幼儿", usageContext: "集体科学探索活动", objective: "通过观察、猜想、动手混色和表达发现，理解两种颜色混合会产生新颜色", pageCount: 8, constraints: ["适合大班观看距离", "以提问和动手探索推进", "不虚构实验结论"], sourceAssetIds: [], language: "zh-CN" },
  { slug: "parent-communication", title: "把夜晚还给睡眠：家庭睡前节律共建", audience: "幼儿园家长", usageContext: "家长会专题沟通", objective: "帮助家长理解稳定睡前节律的价值，并形成可执行、可持续、不过度焦虑的家庭行动方案", pageCount: 8, constraints: ["语气尊重家长", "不提供医疗诊断", "建议具体但不制造焦虑"], sourceAssetIds: [], language: "zh-CN" },
  { slug: "garden-review", title: "从看见到支持：户外活动观察月度复盘", audience: "幼儿园教师与园务管理者", usageContext: "月度教研与园务复盘", objective: "呈现户外活动观察框架、共性发现、支持策略和下月行动闭环", pageCount: 9, constraints: ["事实与建议分开表达", "没有来源的数据不得编造", "突出行动责任与复盘机制"], sourceAssetIds: [], language: "zh-CN" }
];

const requestJson = async (method, url, body) => {
  const response = await app.inject({ method, url, ...(body ? { payload: body } : {}) });
  const parsed = response.json();
  if (response.statusCode >= 400) throw new Error(`${parsed.error?.code ?? response.statusCode}: ${parsed.error?.message ?? "request failed"}`);
  return parsed.data ?? parsed;
};

const waitForJob = async (jobId) => {
  for (let attempt = 0; attempt < 300; attempt += 1) {
    const job = await requestJson("GET", `/api/v1/jobs/${jobId}`);
    if (job.status === "succeeded") return job;
    if (job.status === "failed") throw new Error(`${job.error?.code ?? "JOB_FAILED"}: ${job.error?.message ?? "job failed"}`);
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 500));
  }
  throw new Error(`JOB_TIMEOUT: ${jobId}`);
};

const startAndWait = async (url, payload = {}) => {
  const job = await requestJson("POST", url, { idempotencyKey: crypto.randomUUID(), ...payload });
  return waitForJob(job.id);
};

const exportSlides = async (pptxPath, outputDirectory, programId) => {
  await mkdir(outputDirectory, { recursive: true });
  const script = `$ErrorActionPreference='Stop'; $app=$null; $deck=$null; try { $app=New-Object -ComObject $env:SPARKDECK_OFFICE_PROGRAM_ID; $deck=$app.Presentations.Open($env:SPARKDECK_RENDER_PPTX,$true,$true,$false); [System.Threading.Thread]::Sleep(800); $deck.Export($env:SPARKDECK_RENDER_IMAGES,'PNG',1280,720) } finally { if ($null -ne $deck) { $deck.Close() }; if ($null -ne $app) { $app.Quit() } }`;
  await run("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", script], { windowsHide: true, timeout: 120_000, env: { ...process.env, SPARKDECK_OFFICE_PROGRAM_ID: programId, SPARKDECK_RENDER_PPTX: pptxPath, SPARKDECK_RENDER_IMAGES: outputDirectory } });
};

const createContactSheet = async (slidesDirectory, outputPath) => {
  const files = (await readdir(slidesDirectory)).filter((name) => /\d+\.png$/i.test(name)).sort((left, right) => Number(left.match(/\d+/)?.[0]) - Number(right.match(/\d+/)?.[0]));
  const width = 400; const height = 225; const columns = Math.min(3, files.length); const rows = Math.ceil(files.length / columns);
  const layers = await Promise.all(files.map(async (name, index) => ({ input: await sharp(resolve(slidesDirectory, name)).resize(width, height, { fit: "fill" }).png().toBuffer(), left: index % columns * width, top: Math.floor(index / columns) * height })));
  await sharp({ create: { width: columns * width, height: rows * height, channels: 3, background: "#111827" } }).composite(layers).png().toFile(outputPath);
};

const executeBrief = async (brief) => {
  const directory = resolve(root, brief.slug);
  await mkdir(directory, { recursive: true });
  try {
    const created = await requestJson("POST", "/api/v1/presentations", brief);
    await startAndWait(`/api/v1/presentations/${created.id}/narrative-jobs`);
    let state = await requestJson("GET", `/api/v1/presentations/${created.id}`);
    await requestJson("POST", `/api/v1/presentations/${created.id}/outline/confirm`, { idempotencyKey: crypto.randomUUID(), expectedRevision: state.outline.revision });
    await startAndWait(`/api/v1/presentations/${created.id}/design-jobs`);
    await startAndWait(`/api/v1/presentations/${created.id}/composition-jobs`, { canvas: { width: 960, height: 540 } });
    await startAndWait(`/api/v1/presentations/${created.id}/asset-jobs`);
    await startAndWait(`/api/v1/presentations/${created.id}/quality-jobs`);
    state = await requestJson("GET", `/api/v1/presentations/${created.id}`);
    if (!state.quality?.passed) throw new Error(`QUALITY_GATE_FAILED: ${JSON.stringify(state.quality?.issues ?? [])}`);

    const exported = await app.inject({ method: "POST", url: `/api/v1/presentations/${created.id}/exports`, payload: { idempotencyKey: crypto.randomUUID(), expectedRevision: state.scene.revision } });
    if (exported.statusCode >= 400) throw new Error(`EXPORT_FAILED: ${exported.body}`);
    const pptxPath = resolve(directory, `${brief.slug}.pptx`);
    await writeFile(pptxPath, exported.rawPayload);
    state = await requestJson("GET", `/api/v1/presentations/${created.id}`);
    const usage = await requestJson("GET", `/api/v1/presentations/${created.id}/usage`);
    const layoutTraces = await requestJson("GET", `/api/v1/presentations/${created.id}/layout-traces`);
    const assetTraces = await requestJson("GET", `/api/v1/presentations/${created.id}/asset-traces`);
    const scene = state.scene;
    const powerpoint = await new OfficeRenderEvidenceAdapter("PowerPoint.Application").create(scene, exported.rawPayload);
    if (!powerpoint.evidence.passed) throw new Error(`POWERPOINT_RENDER_DIVERGENCE: ${JSON.stringify(powerpoint.evidence.pages)}`);
    const wpsSlides = resolve(directory, "wps-slides");
    const powerpointSlides = resolve(directory, "powerpoint-slides");
    await exportSlides(pptxPath, wpsSlides, "KWPP.Application");
    await exportSlides(pptxPath, powerpointSlides, "PowerPoint.Application");
    await createContactSheet(wpsSlides, resolve(directory, "wps-contact-sheet.png"));
    await createContactSheet(powerpointSlides, resolve(directory, "powerpoint-contact-sheet.png"));
    const report = {
      presentationId: created.id,
      brief,
      quality: state.quality,
      wpsRenderEvidence: state.renderEvidence,
      powerpointRenderEvidence: powerpoint.evidence,
      usage,
      estimatedCostRmb: usage.reduce((sum, entry) => sum + entry.estimatedCostRmb, 0),
      imageCalls: usage.filter((entry) => entry.purpose === "image").length,
      layoutTraceCount: Object.keys(layoutTraces).length,
      assetTraces
    };
    await writeFile(resolve(directory, "scene-graph.json"), JSON.stringify(scene, null, 2), "utf8");
    await writeFile(resolve(directory, "acceptance-report.json"), JSON.stringify(report, null, 2), "utf8");
    return report;
  } catch (error) {
    await writeFile(resolve(directory, "failure.json"), JSON.stringify({ brief, error: error instanceof Error ? error.message : String(error) }, null, 2), "utf8");
    throw error;
  }
};

await mkdir(root, { recursive: true });
const reports = [];
try {
  for (const brief of briefs) reports.push(await executeBrief(brief));
  await writeFile(resolve(root, "summary.json"), JSON.stringify({ passed: true, reports }, null, 2), "utf8");
  console.log(JSON.stringify({ passed: true, reports: reports.map((report) => ({ presentationId: report.presentationId, title: report.brief.title, pages: report.brief.pageCount, imageCalls: report.imageCalls, estimatedCostRmb: report.estimatedCostRmb })) }));
} finally {
  await app.close();
}
