import assert from "node:assert/strict";
import test from "node:test";
import { buildImageRequest, selectImageSize } from "./index.js";

test("image size follows selected placement aspect ratio", () => {
  assert.equal(selectImageSize(1.7), "1536x1024");
  assert.equal(selectImageSize(0.6), "1024x1536");
  assert.equal(selectImageSize(1), "1024x1024");
});

test("image request stays structured so prompt prose remains external", () => {
  const result = buildImageRequest({
    request: { id: "m", identityId: "identity-a", semanticEntityId: "entity-a", visualIdentityKey: "visual-a", reusePolicy: "exact", claimIds: [], role: "full-bleed-background", description: "A spatial scene", fit: "cover", focalPolicy: "subject", textSafeArea: "left", required: true },
    targetAspectRatio: 16 / 9,
    mediaLanguage: { rendering: "illustrated", backgroundTreatment: "spatial", subjectTreatment: "consistent", consistencyRule: "preserve identity" }
  });
  assert.equal(result.context.textSafeArea, "left");
  assert.equal(result.context.role, "full-bleed-background");
  assert.equal(result.size, "1536x1024");
});

test("asset request identity changes when media role changes", () => {
  const request = { id: "m", identityId: "identity-a", semanticEntityId: "entity-a", visualIdentityKey: "visual-a", reusePolicy: "exact" as const, claimIds: [], role: "subject" as const, description: "one visual", fit: "contain" as const, focalPolicy: "subject" as const, required: true };
  const subject = buildImageRequest({ request, targetAspectRatio: 1 });
  const background = buildImageRequest({ request: { ...request, role: "full-bleed-background" as const, fit: "cover" as const }, targetAspectRatio: 1 });
  assert.notEqual(subject.requestHash, background.requestHash);
});
