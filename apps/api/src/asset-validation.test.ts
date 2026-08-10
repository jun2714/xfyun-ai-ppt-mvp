import assert from "node:assert/strict";
import test from "node:test";
import sharp from "sharp";
import { SharpAssetValidationAdapter } from "./infrastructure/assets/sharp-asset-validation.adapter.js";
import { AppError } from "./shared/errors/app-error.js";

const hasCode = (code: string) => (error: unknown) => error instanceof AppError && error.code === code;

test("asset validation accepts sufficient normalized pixels and preserves dimensions", async () => {
  const base64 = (await sharp({ create: { width: 480, height: 320, channels: 3, background: "#4f9c67" } }).png().toBuffer()).toString("base64");
  const result = await new SharpAssetValidationAdapter().validate({ base64, role: "scene", targetAspectRatio: 1.5 });
  assert.equal(result.width, 480);
  assert.equal(result.height, 320);
  assert.ok(result.base64.length > 100);
});

test("asset validation rejects low resolution, wrong background aspect, and opaque cutouts", async () => {
  const low = (await sharp({ create: { width: 64, height: 64, channels: 3, background: "#ffffff" } }).png().toBuffer()).toString("base64");
  await assert.rejects(() => new SharpAssetValidationAdapter().validate({ base64: low, role: "subject", targetAspectRatio: 1 }), hasCode("ASSET_RESOLUTION_TOO_LOW"));
  const opaque = (await sharp({ create: { width: 400, height: 400, channels: 3, background: "#ffffff" } }).png().toBuffer()).toString("base64");
  await assert.rejects(() => new SharpAssetValidationAdapter().validate({ base64: opaque, role: "transparent-cutout", targetAspectRatio: 1 }), hasCode("ASSET_TRANSPARENCY_MISSING"));
  await assert.rejects(() => new SharpAssetValidationAdapter().validate({ base64: opaque, role: "full-bleed-background", targetAspectRatio: 16 / 9 }), hasCode("ASSET_ASPECT_MISMATCH"));
});

test("asset validation rejects HTTPS references that resolve directly to private networks", async () => {
  await assert.rejects(() => new SharpAssetValidationAdapter().validate({ url: "https://127.0.0.1/image.png", role: "subject", targetAspectRatio: 1 }), hasCode("ASSET_REFERENCE_UNSAFE"));
  await assert.rejects(() => new SharpAssetValidationAdapter().validate({ url: "https://[::1]/image.png", role: "subject", targetAspectRatio: 1 }), hasCode("ASSET_REFERENCE_UNSAFE"));
});
