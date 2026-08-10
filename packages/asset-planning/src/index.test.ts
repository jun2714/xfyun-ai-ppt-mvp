import assert from "node:assert/strict";
import test from "node:test";
import { buildImageRequest, selectImageSize } from "./index.js";

test("image size follows selected placement aspect ratio", () => {
  assert.equal(selectImageSize(1.7), "1536x1024");
  assert.equal(selectImageSize(0.6), "1024x1536");
  assert.equal(selectImageSize(1), "1024x1024");
});

test("background prompt protects text area and forbids generated slide text", () => {
  const result = buildImageRequest({
    request: { id: "m", claimIds: [], role: "background", description: "A warm classroom scene", fit: "cover", focalPolicy: "subject", textSafeArea: "left", required: true },
    targetAspectRatio: 16 / 9,
    illustrationDirection: "soft editorial illustration"
  });
  assert.match(result.prompt, /text-safe area on the left/i);
  assert.match(result.prompt, /Do not render words/i);
  assert.equal(result.size, "1536x1024");
});
