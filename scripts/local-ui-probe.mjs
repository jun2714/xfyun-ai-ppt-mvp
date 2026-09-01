import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const root = process.cwd();
const targetUrl = process.env.TARGET_URL || "http://127.0.0.1:3030/tools";
const outputDir = resolve(root, ".runtime/ui-probe");
const playwrightRoot = resolve(root, ".runtime/playwright/node_modules/playwright");
const require = createRequire(import.meta.url);
const { chromium } = require(playwrightRoot);

await mkdir(outputDir, { recursive: true });

const diagnostics = {
  targetUrl,
  startedAt: new Date().toISOString(),
  browser: "Microsoft Edge via Playwright",
  pages: [],
  console: [],
  pageErrors: [],
  requestFailures: [],
  httpErrors: [],
  frames: [],
  checkpoints: [],
};

let browser;
let context;
let exitCode = 0;

const attachPageDiagnostics = (page) => {
  page.on("console", (message) => {
    diagnostics.console.push({
      type: message.type(),
      text: message.text(),
      url: page.url(),
    });
  });
  page.on("pageerror", (error) => {
    diagnostics.pageErrors.push({ message: error.message, stack: error.stack || null, url: page.url() });
  });
  page.on("requestfailed", (request) => {
    diagnostics.requestFailures.push({
      method: request.method(),
      url: request.url(),
      failure: request.failure()?.errorText || "unknown",
    });
  });
  page.on("response", (response) => {
    if (response.status() >= 400) {
      diagnostics.httpErrors.push({ status: response.status(), url: response.url() });
    }
  });
};

try {
  browser = await chromium.launch({ channel: "msedge", headless: true });
  context = await browser.newContext({
    viewport: { width: 1600, height: 1000 },
    ignoreHTTPSErrors: true,
  });
  await context.tracing.start({ screenshots: true, snapshots: true, sources: true });

  context.on("page", (page) => attachPageDiagnostics(page));

  const page = await context.newPage();
  attachPageDiagnostics(page);
  await page.goto(targetUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
  await page.waitForTimeout(1500);

  diagnostics.checkpoints.push({
    name: "tools-loaded",
    url: page.url(),
    title: await page.title(),
  });
  await page.screenshot({ path: resolve(outputDir, "01-tools.png"), fullPage: true });

  const pptCard = page.getByText("PPT制作", { exact: true }).first();
  const pptVisible = await pptCard.isVisible().catch(() => false);
  diagnostics.checkpoints.push({ name: "ppt-card-visible", value: pptVisible });

  if (!pptVisible) {
    diagnostics.pageText = (await page.locator("body").innerText().catch(() => "")).slice(0, 30000);
    throw new Error("Could not find a visible 'PPT制作' entry on the tools page.");
  }

  const existingPages = context.pages().length;
  await pptCard.click({ timeout: 10000 });
  await page.waitForTimeout(2000);

  const pages = context.pages();
  const activePage = pages.length > existingPages ? pages[pages.length - 1] : page;
  await activePage.waitForLoadState("domcontentloaded", { timeout: 15000 }).catch(() => {});
  await activePage.waitForTimeout(1000);

  diagnostics.checkpoints.push({
    name: "after-ppt-click",
    url: activePage.url(),
    title: await activePage.title().catch(() => ""),
    pageCount: pages.length,
  });

  diagnostics.frames = activePage.frames().map((frame) => ({ name: frame.name(), url: frame.url() }));
  diagnostics.pageText = (await activePage.locator("body").innerText().catch(() => "")).slice(0, 30000);
  await activePage.screenshot({ path: resolve(outputDir, "02-after-ppt-click.png"), fullPage: true });

  diagnostics.pages = await Promise.all(
    context.pages().map(async (p) => ({ url: p.url(), title: await p.title().catch(() => "") }))
  );
} catch (error) {
  exitCode = 1;
  diagnostics.fatalError = { message: error.message, stack: error.stack || null };
} finally {
  diagnostics.finishedAt = new Date().toISOString();
  if (context) {
    await context.tracing.stop({ path: resolve(outputDir, "trace.zip") }).catch(() => {});
  }
  await browser?.close().catch(() => {});
  await writeFile(resolve(outputDir, "diagnostics.json"), JSON.stringify(diagnostics, null, 2), "utf8");
}

process.exitCode = exitCode;
