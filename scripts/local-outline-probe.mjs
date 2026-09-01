import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const root = process.cwd();
const targetUrl = process.env.TARGET_URL || "http://127.0.0.1:5001/upload";
const apiBase = (process.env.API_BASE_URL || "http://127.0.0.1:8000/api/v1/ppt").replace(/\/$/, "");
const topic = process.env.TEST_TOPIC || "认识春天的小动物";
const outputDir = resolve(root, ".runtime/outline-probe");
const playwrightRoot = resolve(root, ".runtime/playwright/node_modules/playwright");
const require = createRequire(import.meta.url);
const { chromium } = require(playwrightRoot);

await mkdir(outputDir, { recursive: true });

const REDACTED_KEYS = /authorization|cookie|token|secret|password|api[_-]?key|credential/i;
const redact = (value, key = "") => {
  if (REDACTED_KEYS.test(key)) return "[redacted]";
  if (Array.isArray(value)) return value.map((item) => redact(item));
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([childKey, childValue]) => [
        childKey,
        redact(childValue, childKey),
      ]),
    );
  }
  if (typeof value === "string") {
    return value
      .replace(/Bearer\s+[A-Za-z0-9._~+\/-]+=*/gi, "Bearer [redacted]")
      .replace(/([?&](?:token|key|api_key|session)=)[^&#\s]+/gi, "$1[redacted]");
  }
  return value;
};

const parseBody = (text) => {
  if (!text) return null;
  try {
    return redact(JSON.parse(text));
  } catch {
    return redact(text.slice(0, 120000));
  }
};

const requestJson = async (url, init = {}) => {
  const started = Date.now();
  try {
    const response = await fetch(url, init);
    const text = await response.text();
    return {
      ok: response.ok,
      status: response.status,
      durationMs: Date.now() - started,
      body: parseBody(text),
    };
  } catch (error) {
    return {
      ok: false,
      status: 0,
      durationMs: Date.now() - started,
      error: error?.message || String(error),
    };
  }
};

const diagnostics = {
  targetUrl,
  apiBase,
  topic,
  startedAt: new Date().toISOString(),
  browser: "Microsoft Edge via Playwright",
  plannerRuntime: null,
  services: {},
  navigation: [],
  startRequest: null,
  startResponse: null,
  outlineStream: null,
  finalOutline: null,
  finalPresentation: null,
  console: [],
  pageErrors: [],
  requestFailures: [],
  httpErrors: [],
  apiTraffic: [],
  checkpoints: [],
  result: { state: "unknown" },
};

diagnostics.plannerRuntime = await requestJson(`${apiBase}/kindergarten/planner/runtime`);
diagnostics.services.editor = await requestJson(targetUrl);
diagnostics.services.web = await requestJson("http://127.0.0.1:5173/");

let browser;
let context;
let page;
let outlineStreamResponse = null;
let exitCode = 0;

const localApiPath = (url) => /\/api\/v1\/ppt\//.test(url);

const attachPageDiagnostics = (targetPage) => {
  targetPage.on("console", (message) => {
    const type = message.type();
    if (["error", "warning"].includes(type)) {
      diagnostics.console.push(
        redact({ type, text: message.text(), url: targetPage.url() }),
      );
    }
  });

  targetPage.on("pageerror", (error) => {
    diagnostics.pageErrors.push(
      redact({
        message: error.message,
        stack: error.stack || null,
        url: targetPage.url(),
      }),
    );
  });

  targetPage.on("requestfailed", (request) => {
    diagnostics.requestFailures.push(
      redact({
        method: request.method(),
        url: request.url(),
        failure: request.failure()?.errorText || "unknown",
      }),
    );
  });

  targetPage.on("request", (request) => {
    const url = request.url();
    if (localApiPath(url)) {
      diagnostics.apiTraffic.push(
        redact({
          phase: "request",
          method: request.method(),
          url,
          at: new Date().toISOString(),
        }),
      );
    }
    if (url.includes("/kindergarten/presentation/start")) {
      diagnostics.startRequest = redact({
        method: request.method(),
        url,
        body: parseBody(request.postData() || ""),
        at: new Date().toISOString(),
      });
    }
  });

  targetPage.on("response", async (response) => {
    const url = response.url();
    if (localApiPath(url)) {
      diagnostics.apiTraffic.push(
        redact({
          phase: "response",
          status: response.status(),
          method: response.request().method(),
          url,
          at: new Date().toISOString(),
        }),
      );
    }

    if (url.includes("/kindergarten/presentation/outline/stream/")) {
      outlineStreamResponse = response;
      diagnostics.outlineStream = {
        url,
        status: response.status(),
        contentType: response.headers()["content-type"] || "",
        receivedAt: new Date().toISOString(),
      };
      return;
    }

    if (url.includes("/kindergarten/presentation/start")) {
      const text = await response.text().catch(() => "");
      diagnostics.startResponse = {
        url,
        status: response.status(),
        body: parseBody(text),
        receivedAt: new Date().toISOString(),
      };
    }

    if (response.status() >= 400 && localApiPath(url)) {
      const text = await response.text().catch(() => "");
      diagnostics.httpErrors.push(
        redact({
          status: response.status(),
          method: response.request().method(),
          url,
          body: parseBody(text),
        }),
      );
    }
  });
};

const bodyText = async () =>
  (await page.locator("body").innerText().catch(() => "")).slice(0, 50000);

try {
  browser = await chromium.launch({ channel: "msedge", headless: true });
  context = await browser.newContext({
    viewport: { width: 1600, height: 1000 },
    ignoreHTTPSErrors: true,
  });
  await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
  context.on("page", attachPageDiagnostics);
  page = await context.newPage();
  attachPageDiagnostics(page);

  await page.goto(targetUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
  diagnostics.navigation.push({
    step: "upload",
    url: page.url(),
    title: await page.title().catch(() => ""),
  });

  await page.waitForTimeout(1200);
  diagnostics.checkpoints.push({ name: "upload-loading-text", text: await bodyText() });
  await page.screenshot({
    path: resolve(outputDir, "01-upload-loading.png"),
    fullPage: true,
  });

  const prompt = page.locator('[data-testid="prompt-input"]');
  const hydrationStartedAt = Date.now();
  await prompt.waitFor({ state: "visible", timeout: 45000 }).catch(() => {});
  diagnostics.checkpoints.push({
    name: "upload-after-hydration-wait",
    elapsedMs: Date.now() - hydrationStartedAt,
    text: await bodyText(),
  });

  if (!(await prompt.isVisible().catch(() => false))) {
    throw new Error(
      "Editor upload page did not expose [data-testid=prompt-input] within 45 seconds.",
    );
  }

  await page.screenshot({ path: resolve(outputDir, "02-upload-ready.png"), fullPage: true });
  await prompt.fill(topic);

  const generate = page.getByRole("button", { name: "生成演示文稿" });
  if (!(await generate.isVisible().catch(() => false))) {
    throw new Error("Editor upload page did not expose the 生成演示文稿 button.");
  }

  const generationStartedAt = Date.now();
  await generate.click();

  await page
    .waitForURL(/http:\/\/127\.0\.0\.1:5173\/presentations\/[^/]+\/outline/, {
      timeout: 30000,
    })
    .catch(() => {});
  await page.waitForTimeout(800);

  diagnostics.navigation.push({
    step: "after-generate",
    url: page.url(),
    elapsedMs: Date.now() - generationStartedAt,
    title: await page.title().catch(() => ""),
  });
  await page.screenshot({
    path: resolve(outputDir, "03-outline-start.png"),
    fullPage: true,
  });

  const idMatch = page.url().match(/\/presentations\/([^/]+)\/outline/);
  const presentationId =
    idMatch?.[1] || diagnostics.startResponse?.body?.presentation_id || null;
  diagnostics.presentationId = presentationId;

  if (!presentationId) {
    diagnostics.checkpoints.push({ name: "no-presentation-id", text: await bodyText() });
    throw new Error(
      "Generation did not reach an outline URL and no presentation_id was returned.",
    );
  }

  const deadline = Date.now() + 105000;
  let finished = false;
  while (Date.now() < deadline) {
    const text = await bodyText();
    const slideCount = await page.locator(".outline-list button").count().catch(() => 0);
    const streamStatusCount = await page
      .locator(".outline-stream-status")
      .count()
      .catch(() => 0);

    diagnostics.result.lastObserved = {
      elapsedMs: Date.now() - generationStartedAt,
      slideCount,
      streamStatusCount,
      text: text.slice(0, 8000),
    };

    if (text.includes("大纲生成失败")) {
      diagnostics.result.state = "outline-error-ui";
      finished = true;
      break;
    }
    if (slideCount >= 3 && streamStatusCount === 0) {
      diagnostics.result.state = "outline-ready";
      diagnostics.result.slideCount = slideCount;
      finished = true;
      break;
    }
    await page.waitForTimeout(1500);
  }

  if (!finished) diagnostics.result.state = "outline-timeout";

  if (outlineStreamResponse) {
    const streamText = await Promise.race([
      outlineStreamResponse
        .text()
        .catch(
          (error) =>
            `[[stream body unavailable: ${error?.message || error}]]`,
        ),
      new Promise((resolvePromise) =>
        setTimeout(
          () => resolvePromise("[[stream body still open after UI deadline]]"),
          7000,
        ),
      ),
    ]);
    diagnostics.outlineStream.body = parseBody(String(streamText));
    diagnostics.outlineStream.finishedAt = new Date().toISOString();
  } else {
    diagnostics.outlineStream = { missing: true };
  }

  diagnostics.finalOutline = await requestJson(`${apiBase}/outlines/${presentationId}`);
  diagnostics.finalPresentation = await requestJson(
    `${apiBase}/presentation/${presentationId}`,
  );
  diagnostics.checkpoints.push({ name: "final-page-text", text: await bodyText() });
  await page.screenshot({
    path: resolve(outputDir, "04-outline-final.png"),
    fullPage: true,
  });

  if (diagnostics.result.state !== "outline-ready") exitCode = 1;
} catch (error) {
  exitCode = 1;
  diagnostics.result.state =
    diagnostics.result.state === "unknown" ? "fatal" : diagnostics.result.state;
  diagnostics.fatalError = redact({
    message: error?.message || String(error),
    stack: error?.stack || null,
  });
  if (page) {
    diagnostics.checkpoints.push({ name: "fatal-page-text", text: await bodyText() });
    await page
      .screenshot({ path: resolve(outputDir, "99-fatal.png"), fullPage: true })
      .catch(() => {});
  }
} finally {
  diagnostics.finishedAt = new Date().toISOString();
  if (context) {
    await context.tracing
      .stop({ path: resolve(outputDir, "trace.zip") })
      .catch(() => {});
  }
  await browser?.close().catch(() => {});
  await writeFile(
    resolve(outputDir, "outline-diagnostics.json"),
    JSON.stringify(redact(diagnostics), null, 2),
    "utf8",
  );
}

process.exitCode = exitCode;
