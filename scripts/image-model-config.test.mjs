import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_DMX_GEMINI_IMAGE_MODEL,
  resolveGeminiImageModel,
} from "./image-model-config.mjs";

test("missing image model defaults to Gemini Flash Lite Image", () => {
  assert.equal(resolveGeminiImageModel({}), DEFAULT_DMX_GEMINI_IMAGE_MODEL);
});

test("stale shared image model migrates before the API process starts", () => {
  assert.equal(
    resolveGeminiImageModel({ DMX_IMAGE_MODEL: "gemini-3.1-flash-image" }),
    DEFAULT_DMX_GEMINI_IMAGE_MODEL,
  );
});

test("custom shared image model remains unchanged", () => {
  assert.equal(
    resolveGeminiImageModel({ DMX_IMAGE_MODEL: "custom-gemini-image-model" }),
    "custom-gemini-image-model",
  );
});

test("explicit provider-specific model wins", () => {
  assert.equal(
    resolveGeminiImageModel({
      DMX_IMAGE_MODEL: "gemini-3.1-flash-image",
      GEMINI_IMAGE_MODEL: "manual-image-model",
    }),
    "manual-image-model",
  );
});
