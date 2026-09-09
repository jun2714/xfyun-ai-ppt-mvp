import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const hookUrl = new URL(
  "../app/(presentation-generator)/presentation/hooks/usePresentationStreaming.ts",
  import.meta.url,
);

async function source() {
  return readFile(hookUrl, "utf8");
}

test("paid presentation stream never auto-retries", async () => {
  const text = await source();

  assert.match(text, /const PAID_STREAM_AUTO_RETRY_COUNT = 0;/);
  assert.doesNotMatch(text, /scheduleRetry\s*\(/);
  assert.doesNotMatch(text, /Presentation stream retry/);
  assert.doesNotMatch(text, /STREAM_RETRY_DELAY_MS/);
});

test("asset-stage failure keeps an in-memory deck instead of reloading over it", async () => {
  const text = await source();
  const start = text.indexOf("const finalizeFailure =");
  const end = text.indexOf("const preloadPreparedPresentation", start);
  assert.ok(start >= 0 && end > start, "finalizeFailure block should exist");

  const failureBlock = text.slice(start, end);
  assert.match(
    failureBlock,
    /const hasPartialDeck = Array\.isArray\(currentSlides\) && currentSlides\.length > 0;/,
  );
  assert.match(failureBlock, /if \(!hasPartialDeck\) \{/);
  assert.match(failureBlock, /fetchUserSlides\(\)/);

  const guardIndex = failureBlock.indexOf("if (!hasPartialDeck) {");
  const fetchIndex = failureBlock.indexOf("fetchUserSlides()", guardIndex);
  assert.ok(fetchIndex > guardIndex, "fetch should only happen inside no-partial-deck guard");
});
