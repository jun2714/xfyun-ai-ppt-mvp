import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const root = process.cwd();
const targetUrl = process.env.TARGET_URL || "http://127.0.0.1:5001/upload";
const apiBase = (process.env.API_BASE_URL || "http://127.0.0.1:8000/api/v1/ppt").replace(/\/$/, "");
const topic = process.env.TEST_TOPIC_B64
  ? Buffer.from(process.env.TEST_TOPIC_B64, "base64").toString("utf8")
  : process.env.TEST_TOPIC || "小种子收到了一封春天的来信";
const expectedSlides = Number(process.env.EXPECTED_SLIDES || 8);
const outputDir = resolve(root, ".runtime/full-ppt-probe");
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
      Object.entries(value).map(([childKey, childValue]) => [childKey, redact(childValue, childKey)]),
    );
  }
  if (typeof value === "string") {
    return value
      .replace(/Bearer\s+[A-Za-z0-9._~+\/-]+=*/gi, "Bearer [redacted]")
      .replace(/([?&](?:token|key|api_key|session|tn_session)=)[^&#\s]+/gi, "$1[redacted]");
  }
  return value;
};

const parseBody = (text) => {
  if (!text) return null;
  try {
    return redact(JSON.parse(text));
  } catch {
    return redact(String(text).slice(0, 120000));
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

const stripOutlineMarkup = (line) =>
  String(line || "")
    .trim()
    .replace(/^#{1,6}\s+/, "")
    .replace(/^(?:[-*+•]|\d+[.)])\s+/, "")
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/__(.*?)__/g, "$1")
    .trim();

const outlineVisibleLines = (content) =>
  String(content || "")
    .split(/\r?\n/)
    .map(stripOutlineMarkup)
    .filter(Boolean);

const NON_AUDIENCE_KEYS = new Set([
  "__speaker_note__",
  "__content_contract__",
  "image_prompt",
  "__image_prompt__",
  "icon_query",
  "__icon_query__",
  "image_url",
  "__image_url__",
  "icon_url",
  "__icon_url__",
  "url",
  "prompt",
  "query",
  "type",
  "charttype",
  "chart_type",
  "color",
  "colors",
  "axiscolor",
  "axis_color",
  "gridcolor",
  "grid_color",
  "legendcolor",
  "legend_color",
]);

const collectAudienceStrings = (value, parentKey = "") => {
  const result = [];
  if (parentKey.startsWith("__") || NON_AUDIENCE_KEYS.has(parentKey.toLowerCase())) {
    return result;
  }
  if (Array.isArray(value)) {
    for (const child of value) {
      if (typeof child === "string") result.push(child);
      else if (child && typeof child === "object") result.push(...collectAudienceStrings(child, parentKey));
    }
    return result;
  }
  if (!value || typeof value !== "object") return result;
  for (const [key, child] of Object.entries(value)) {
    if (key.startsWith("__") || NON_AUDIENCE_KEYS.has(key.toLowerCase())) continue;
    if (typeof child === "string") result.push(child);
    else if (child && typeof child === "object") result.push(...collectAudienceStrings(child, key));
  }
  return result;
};

const collectImageUrls = (value, found = []) => {
  if (Array.isArray(value)) {
    for (const child of value) collectImageUrls(child, found);
    return found;
  }
  if (!value || typeof value !== "object") return found;
  if (value.type === "image" && typeof value.data === "string" && value.data.trim()) {
    found.push(value.data.trim());
  }
  for (const [key, child] of Object.entries(value)) {
    if (["image_url", "__image_url__"].includes(key) && typeof child === "string" && child.trim()) {
      found.push(child.trim());
    } else if (child && typeof child === "object") {
      collectImageUrls(child, found);
    }
  }
  return found;
};

const collectVisibleUiText = (value, found = []) => {
  if (!value || typeof value !== "object") return found;
  if (value.type === "text" && Array.isArray(value.runs)) {
    found.push(value.runs.map((run) => run?.text || "").join(""));
  }
  for (const child of Object.values(value)) {
    if (child && typeof child === "object") collectVisibleUiText(child, found);
  }
  return found;
};

const collectTextBoxOverflows = (value, slideIndex, found = []) => {
  if (Array.isArray(value)) {
    for (const child of value) collectTextBoxOverflows(child, slideIndex, found);
    return found;
  }
  if (!value || typeof value !== "object") return found;
  if (value.type === "text" && value.size && value.font && Array.isArray(value.runs)) {
    const text = value.runs.map((run) => run?.text || "").join("");
    const width = Number(value.size.width || 0);
    const height = Number(value.size.height || 0);
    const fontSize = Number(value.font.size || 0);
    const lineHeight = Math.max(1, Number(value.font.line_height || 1.15));
    const letterSpacing = Math.max(0, Number(value.font.letter_spacing || 0));
    if (text && width > 0 && height > 0 && fontSize > 0) {
      const visualUnits = (line) => [...line].reduce(
        (sum, character) => sum + (character.codePointAt(0) > 0x2ff ? 1 : 0.55),
        0,
      );
      const unitsPerLine = Math.max(1, width / fontSize);
      const wrappedLines = text.split(/\r?\n/).reduce(
        (sum, line) => sum + Math.max(1, Math.ceil(
          (visualUnits(line) + Math.max(0, [...line].length - 1) * letterSpacing / fontSize) / unitsPerLine,
        )),
        0,
      );
      const requiredHeight = wrappedLines * fontSize * lineHeight;
      if (requiredHeight > height * 1.02) {
        found.push({
          page: slideIndex + 1,
          name: value.name || null,
          text,
          width,
          height,
          fontSize,
          requiredHeight,
        });
      }
    }
  }
  for (const child of Object.values(value)) {
    if (child && typeof child === "object") collectTextBoxOverflows(child, slideIndex, found);
  }
  return found;
};

const collectTemplatePlaceholders = (value, slideIndex, found = []) => {
  if (Array.isArray(value)) {
    for (const child of value) collectTemplatePlaceholders(child, slideIndex, found);
    return found;
  }
  if (!value || typeof value !== "object") return found;
  if (value.type === "text" && Array.isArray(value.runs)) {
    const text = value.runs.map((run) => run?.text || "").join("").trim();
    if (
      /^(?:lorem ipsum|heading|title|subtitle|description|your topic|your title|insert text here)\b/i.test(text)
    ) {
      found.push({ page: slideIndex + 1, name: value.name || null, text });
    }
  }
  for (const child of Object.values(value)) {
    if (child && typeof child === "object") collectTemplatePlaceholders(child, slideIndex, found);
  }
  return found;
};

const diagnostics = {
  targetUrl,
  apiBase,
  topic,
  expectedSlides,
  startedAt: new Date().toISOString(),
  plannerRuntime: await requestJson(`${apiBase}/kindergarten/planner/runtime`),
  imageRuntime: await requestJson(`${apiBase}/diagnostics/image-runtime`),
  navigation: [],
  streamRequests: [],
  httpErrors: [],
  console: [],
  requestFailures: [],
  outline: null,
  finalPresentation: null,
  fidelity: [],
  imageChecks: [],
  validationErrors: [],
  layoutOverflows: [],
  templatePlaceholders: [],
  result: { state: "starting" },
};

let browser;
let context;
let page;
let streamResponse = null;
let exitCode = 0;

const isLocalPptApi = (url) => /\/api\/v1\/ppt\//.test(url);

try {
  if (diagnostics.plannerRuntime.body?.model !== "deepseek-v4-pro-0813") {
    throw new Error(`Unexpected planner runtime: ${JSON.stringify(diagnostics.plannerRuntime.body)}`);
  }
  if (diagnostics.imageRuntime.body?.model !== "gemini-3.1-flash-lite-image") {
    throw new Error(`Unexpected image runtime: ${JSON.stringify(diagnostics.imageRuntime.body)}`);
  }
  if (diagnostics.imageRuntime.body?.google_genai_compatible !== true) {
    throw new Error(`Incompatible Google GenAI SDK runtime: ${JSON.stringify(diagnostics.imageRuntime.body)}`);
  }

  browser = await chromium.launch({ channel: "msedge", headless: true });
  context = await browser.newContext({
    viewport: { width: 1600, height: 1000 },
    ignoreHTTPSErrors: true,
  });
  await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
  page = await context.newPage();

  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type())) {
      diagnostics.console.push(redact({ type: message.type(), text: message.text(), url: page.url() }));
    }
  });
  page.on("requestfailed", (request) => {
    diagnostics.requestFailures.push(redact({
      method: request.method(),
      url: request.url(),
      failure: request.failure()?.errorText || "unknown",
    }));
  });
  page.on("request", (request) => {
    const url = request.url();
    if (/\/api\/v1\/ppt\/presentation\/stream\//.test(url)) {
      diagnostics.streamRequests.push({ method: request.method(), url: redact(url), at: new Date().toISOString() });
    }
  });
  page.on("response", async (response) => {
    const url = response.url();
    if (/\/api\/v1\/ppt\/presentation\/stream\//.test(url)) {
      streamResponse = response;
    }
    if (response.status() >= 400 && (isLocalPptApi(url) || /\/app_data\/images\//.test(url))) {
      const text = await response.text().catch(() => "");
      diagnostics.httpErrors.push(redact({
        status: response.status(),
        method: response.request().method(),
        url,
        body: parseBody(text),
      }));
    }
  });

  await page.goto(targetUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
  diagnostics.navigation.push({ step: "upload", url: page.url() });
  const prompt = page.locator('[data-testid="prompt-input"]');
  await prompt.waitFor({ state: "visible", timeout: 45000 });
  await prompt.fill(topic);
  if (expectedSlides > 0) {
    await page.getByTestId("slides-select").click();
    await page.getByRole("option", { name: `${expectedSlides} 页`, exact: true }).click();
  }
  await page.getByRole("button", { name: "生成演示文稿" }).click();

  await page.waitForURL(/\/presentations\/[^/]+\/outline/, { timeout: 30000 });
  const idMatch = page.url().match(/\/presentations\/([^/]+)\/outline/);
  const presentationId = idMatch?.[1];
  if (!presentationId) throw new Error("Could not resolve presentation id after outline navigation.");
  diagnostics.presentationId = presentationId;
  diagnostics.navigation.push({ step: "outline", url: page.url(), presentationId });
  await page.screenshot({ path: resolve(outputDir, "01-outline-start.png"), fullPage: true });

  const outlineDeadline = Date.now() + 240000;
  while (Date.now() < outlineDeadline) {
    const slideCount = await page.locator(".outline-list button").count().catch(() => 0);
    const statusCount = await page.locator(".outline-stream-status").count().catch(() => 0);
    const body = await page.locator("body").innerText().catch(() => "");
    if (body.includes("大纲生成失败")) throw new Error("Outline UI reported failure.");
    if (slideCount >= 3 && statusCount === 0) break;
    await page.waitForTimeout(1500);
  }

  const outlineResponse = await requestJson(`${apiBase}/outlines/${presentationId}`);
  if (!outlineResponse.ok || !Array.isArray(outlineResponse.body?.slides) || outlineResponse.body.slides.length < 3) {
    throw new Error(`Outline checkpoint unavailable: ${JSON.stringify(outlineResponse)}`);
  }
  diagnostics.outline = outlineResponse.body;
  await page.screenshot({ path: resolve(outputDir, "02-outline-ready.png"), fullPage: true });

  const confirm = page.getByRole("button", { name: "确认生成" });
  await confirm.waitFor({ state: "visible", timeout: 30000 });
  await confirm.waitFor({ state: "attached", timeout: 30000 });
  const disabled = await confirm.isDisabled().catch(() => true);
  if (disabled) throw new Error("确认生成 button stayed disabled after outline completion.");
  await confirm.click();

  await page.waitForURL(new RegExp(`/presentations/${presentationId}/edit`), { timeout: 45000 });
  diagnostics.navigation.push({ step: "edit", url: page.url() });
  await page.locator('iframe[title="PPT 编辑器"]').waitFor({ state: "visible", timeout: 45000 });
  await page.screenshot({ path: resolve(outputDir, "03-editor-streaming.png"), fullPage: true });

  const streamDeadline = Date.now() + 45000;
  while (!streamResponse && Date.now() < streamDeadline) {
    await page.waitForTimeout(500);
  }
  if (!streamResponse) throw new Error("Presentation EventSource request was never observed.");

  let streamTimeout;
  let streamFinished;
  try {
    streamFinished = await Promise.race([
      streamResponse.finished().then((error) => !error).catch(() => false),
      new Promise((resolvePromise) => {
        streamTimeout = setTimeout(() => resolvePromise(false), 420000);
      }),
    ]);
  } finally {
    clearTimeout(streamTimeout);
  }
  diagnostics.streamFinished = streamFinished;
  if (!streamFinished) diagnostics.validationErrors.push("Generation stream did not finish before timeout.");

  await page.waitForTimeout(2000);
  const finalResponse = await requestJson(`${apiBase}/presentation/${presentationId}`);
  if (!finalResponse.ok || !Array.isArray(finalResponse.body?.slides)) {
    throw new Error(`Final presentation checkpoint unavailable: ${JSON.stringify(finalResponse)}`);
  }
  diagnostics.finalPresentation = finalResponse.body;

  const finalSlides = [...finalResponse.body.slides].sort((a, b) => Number(a?.index ?? 0) - Number(b?.index ?? 0));
  const outlineSlides = outlineResponse.body.slides;
  if (finalSlides.length !== outlineSlides.length) {
    throw new Error(`Slide count changed from reviewed outline ${outlineSlides.length} to final deck ${finalSlides.length}.`);
  }
  if (expectedSlides > 0 && finalSlides.length !== expectedSlides) {
    throw new Error(`Expected ${expectedSlides} slides but final deck contains ${finalSlides.length}.`);
  }

  for (let index = 0; index < outlineSlides.length; index += 1) {
    const expectedLines = outlineVisibleLines(outlineSlides[index]?.content);
    const finalText = collectAudienceStrings(finalSlides[index]?.content).join("\n");
    const missing = expectedLines.filter((line) => !finalText.includes(line));
    const visibleUiText = collectVisibleUiText(finalSlides[index]?.ui).join("\n");
    const missingFromUi = expectedLines.filter((line) => !visibleUiText.includes(line));
    diagnostics.fidelity.push({ page: index + 1, expectedLines, missing, missingFromUi });
    if (missing.length || missingFromUi.length) {
      diagnostics.validationErrors.push(
        `Page ${index + 1} lost reviewed copy. Content missing: ${missing.join(" | ")}; UI missing: ${missingFromUi.join(" | ")}`,
      );
    }
  }

  diagnostics.layoutOverflows = finalSlides.flatMap((slide, index) =>
    collectTextBoxOverflows(slide?.ui, index),
  );
  if (diagnostics.layoutOverflows.length) {
    diagnostics.validationErrors.push(
      `Final deck contains ${diagnostics.layoutOverflows.length} overflowing text boxes: ` +
      diagnostics.layoutOverflows.map((item) => `page ${item.page} ${item.name || "text"}`).join(", "),
    );
  }

  diagnostics.templatePlaceholders = finalSlides.flatMap((slide, index) =>
    collectTemplatePlaceholders(slide?.ui, index),
  );
  if (diagnostics.templatePlaceholders.length) {
    diagnostics.validationErrors.push(
      `Final deck contains ${diagnostics.templatePlaceholders.length} imported template placeholders: ` +
      diagnostics.templatePlaceholders.map((item) => `page ${item.page} ${item.text}`).join(", "),
    );
  }

  if (diagnostics.streamRequests.length !== 1) {
    diagnostics.validationErrors.push(
      `Paid presentation stream was opened ${diagnostics.streamRequests.length} times; expected exactly 1.`,
    );
  }

  const isGeneratedImageUrl = (url) => /\/app_data\/images\//.test(url) && !/placeholder/i.test(url);
  const contentImageUrls = [...new Set(collectImageUrls(finalSlides.map((slide) => slide?.content)))]
    .filter(isGeneratedImageUrl);
  const uiImageUrls = [...new Set(collectImageUrls(finalSlides.map((slide) => slide?.ui)))]
    .filter(isGeneratedImageUrl);
  diagnostics.contentImageUrlCount = contentImageUrls.length;
  diagnostics.uiImageUrlCount = uiImageUrls.length;
  if (contentImageUrls.some((url) => !uiImageUrls.includes(url)) ||
      uiImageUrls.some((url) => !contentImageUrls.includes(url))) {
    diagnostics.validationErrors.push("Stored content and rendered UI disagree on generated image URLs.");
  }
  if (contentImageUrls.length === 0) {
    throw new Error("Database slide content retained only placeholder image URLs after generation.");
  }
  if (uiImageUrls.length === 0) {
    throw new Error("Final slide UI contains no generated image URLs.");
  }
  const imageUrls = [...new Set([...contentImageUrls, ...uiImageUrls])];
  diagnostics.imageUrlCount = imageUrls.length;
  for (const rawUrl of imageUrls) {
    let url = rawUrl;
    if (url.startsWith("/")) url = `${new URL(apiBase).origin}${url}`;
    const started = Date.now();
    try {
      const response = await context.request.get(url, { timeout: 45000, failOnStatusCode: false });
      const contentType = response.headers()["content-type"] || "";
      const status = response.status();
      const body = await response.body();
      diagnostics.imageChecks.push({
        url: redact(url),
        status,
        contentType,
        bytes: body.length,
        durationMs: Date.now() - started,
      });
      if (status !== 200) throw new Error(`Generated image returned HTTP ${status}: ${url}`);
      if (!contentType.startsWith("image/")) throw new Error(`Image URL returned ${contentType}: ${url}`);
      if (body.length < 10000) throw new Error(`Generated image is unexpectedly small (${body.length} bytes): ${url}`);
      const imagePath = new URL(url);
      const proxyUrl = `${new URL(targetUrl).origin}${imagePath.pathname}${imagePath.search}`;
      const proxyResponse = await context.request.get(proxyUrl, { timeout: 45000, failOnStatusCode: false });
      const proxyBody = await proxyResponse.body();
      diagnostics.imageChecks.at(-1).editorProxyStatus = proxyResponse.status();
      if (proxyResponse.status() !== 200 || !proxyBody.equals(body)) {
        throw new Error(`Editor proxy did not deliver the identical image: ${redact(proxyUrl)}`);
      }
    } catch (error) {
      diagnostics.imageChecks.push({
        url: redact(url),
        error: error?.message || String(error),
        durationMs: Date.now() - started,
      });
      throw error;
    }
  }

  if (diagnostics.httpErrors.some((item) => item.status === 404 && /app_data\/images/.test(item.url))) {
    throw new Error("Browser observed a 404 for a generated app_data image.");
  }

  if (diagnostics.validationErrors.length) {
    throw new Error(diagnostics.validationErrors.join("\n"));
  }

  diagnostics.result = {
    state: "passed",
    slideCount: finalSlides.length,
    streamRequestCount: diagnostics.streamRequests.length,
    checkedImages: diagnostics.imageChecks.length,
  };
  await page.screenshot({ path: resolve(outputDir, "04-editor-final.png"), fullPage: true });
} catch (error) {
  exitCode = 1;
  diagnostics.result = { state: "failed" };
  diagnostics.fatalError = redact({ message: error?.message || String(error), stack: error?.stack || null });
  if (page) {
    await page.screenshot({ path: resolve(outputDir, "99-failure.png"), fullPage: true }).catch(() => {});
  }
} finally {
  diagnostics.finishedAt = new Date().toISOString();
  if (context) {
    await context.tracing.stop({ path: resolve(outputDir, "trace.zip") }).catch(() => {});
  }
  await browser?.close().catch(() => {});
  await writeFile(
    resolve(outputDir, "full-ppt-diagnostics.json"),
    JSON.stringify(redact(diagnostics), null, 2),
    "utf8",
  );
}

process.exitCode = exitCode;
