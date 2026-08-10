import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { access, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { constants } from "node:fs";
import { dirname, isAbsolute, relative, resolve, sep } from "node:path";
import { pathToFileURL } from "node:url";
import { promisify } from "node:util";
import sharp from "sharp";

const run = promisify(execFile);
const REQUIRED_PROMPTS = ["narrative.prompt.txt", "design.prompt.txt", "image.prompt.txt", "visual-quality.prompt.txt"];
const REQUIRED_CONFIG = ["DMX_API_KEY", "DMX_TEXT_MODEL", "DMX_IMAGE_MODEL", "DMX_VISION_MODEL"];
const sha256 = (value) => createHash("sha256").update(value).digest("hex");

async function checkWritableDirectory(path) {
  await mkdir(path, { recursive: true });
  const probe = resolve(path, `.sparkdeck-write-probe-${process.pid}`);
  await writeFile(probe, "ok", { flag: "wx" });
  await rm(probe);
}

async function checkOffice(programId) {
  const script = "$ErrorActionPreference='Stop'; $app=$null; $deck=$null; try {$app=New-Object -ComObject $env:SPARKDECK_OFFICE_PROGRAM_ID; $deck=$app.Presentations.Add(); $deck.Close(); $deck=$null} finally {if ($null -ne $deck) {$deck.Close()}; if ($null -ne $app) {$app.Quit()}}";
  await run("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", script], {
    windowsHide: true,
    timeout: 30_000,
    env: { ...process.env, SPARKDECK_OFFICE_PROGRAM_ID: programId }
  });
}

async function installedChineseFont() {
  const fontRoot = resolve(process.env.WINDIR ?? "C:\\Windows", "Fonts");
  const candidates = ["msyh.ttc", "msyh.ttf", "simhei.ttf", "simsun.ttc"];
  for (const name of candidates) {
    try { await access(resolve(fontRoot, name), constants.R_OK); return name; } catch { /* try fallback */ }
  }
  throw new Error("No supported Chinese font or fallback is installed");
}

function isOutsideRepository(repositoryRoot, inputPath) {
  const rel = relative(repositoryRoot, inputPath);
  return rel.startsWith(`..${sep}`) || rel === ".." || isAbsolute(rel);
}

export async function runPreflight(options) {
  // Importing sharp here is intentional: cold-start dependency resolution must execute, not merely parse.
  if (typeof sharp !== "function") throw new Error("sharp runtime import failed");
  const checks = [];
  const record = async (name, action) => {
    try { const detail = await action(); checks.push({ name, passed: true, ...(detail ? { detail } : {}) }); }
    catch (error) { checks.push({ name, passed: false, error: error instanceof Error ? error.message : String(error) }); }
  };

  const packageJson = JSON.parse(await readFile(resolve(options.repositoryRoot, "package.json"), "utf8"));
  await record("node-version", async () => {
    if (Number(process.versions.node.split(".")[0]) < 20) throw new Error(`Node ${process.versions.node} is below 20`);
    return process.versions.node;
  });
  await record("pnpm-version-contract", async () => {
    if (!/^pnpm@10\./.test(packageJson.packageManager ?? "")) throw new Error("workspace must pin pnpm 10");
    return packageJson.packageManager;
  });
  await record("runtime-imports", async () => {
    const appModule = await import(pathToFileURL(resolve(options.repositoryRoot, "apps/api/dist/app.js")).href);
    const renderModule = await import(pathToFileURL(resolve(options.repositoryRoot, "apps/api/dist/infrastructure/rendering/office-render-evidence.adapter.js")).href);
    if (typeof appModule.buildApp !== "function" || typeof renderModule.OfficeRenderEvidenceAdapter !== "function") throw new Error("Acceptance runtime exports are incomplete");
    return { appLoaded: true, officeAdapterLoaded: true };
  });
  await record("external-brief", async () => {
    if (!isOutsideRepository(options.repositoryRoot, options.briefPath)) throw new Error("Brief must be outside the repository");
    const bytes = await readFile(options.briefPath);
    const brief = JSON.parse(bytes.toString("utf8"));
    for (const key of ["title", "audience", "usageContext", "objective", "pageCount", "constraints", "language"])
      if (brief[key] === undefined || brief[key] === null || brief[key] === "") throw new Error(`Brief is missing ${key}`);
    if (!Number.isInteger(brief.pageCount) || brief.pageCount < 1 || brief.pageCount > 30) throw new Error("Brief pageCount must be an integer from 1 to 30");
    return { sha256: sha256(bytes), pageCount: brief.pageCount };
  });
  await record("prompt-contracts", async () => {
    for (const name of REQUIRED_PROMPTS) await access(resolve(options.promptDirectory, name), constants.R_OK);
    return { directory: options.promptDirectory, count: REQUIRED_PROMPTS.length };
  });
  await record("model-config", async () => {
    const missing = REQUIRED_CONFIG.filter((name) => !process.env[name]?.trim());
    if (missing.length) throw new Error(`Missing configuration: ${missing.join(", ")}`);
    const baseUrl = new URL(process.env.DMX_API_BASE_URL ?? "https://www.dmxapi.cn/v1");
    if (baseUrl.protocol !== "https:") throw new Error("DMX_API_BASE_URL must use HTTPS");
    const style = process.env.DMX_IMAGE_API_STYLE ?? "responses";
    if (!new Set(["responses", "images"]).has(style)) throw new Error("DMX_IMAGE_API_STYLE must be responses or images");
    return { baseUrlOrigin: baseUrl.origin, imageApiStyle: style, secretsEchoed: false };
  });
  await record("data-directory", () => checkWritableDirectory(options.dataDirectory));
  await record("output-directory", () => checkWritableDirectory(options.outputDirectory));
  await record("temp-directory", () => checkWritableDirectory(options.tempDirectory));
  await record("chinese-font", installedChineseFont);
  if (!options.skipOffice) {
    await record("wps-com", () => checkOffice("KWPP.Application"));
    await record("powerpoint-com", () => checkOffice("PowerPoint.Application"));
  }

  const report = {
    schemaVersion: 1,
    phase: "preflight",
    passed: checks.every((item) => item.passed),
    checkedAt: new Date().toISOString(),
    checks,
    usage: { textCalls: 0, imageCalls: 0, visualCalls: 0, estimatedCostRmb: 0 }
  };
  await mkdir(dirname(options.reportPath), { recursive: true });
  await writeFile(options.reportPath, JSON.stringify(report, null, 2), "utf8");
  return report;
}
