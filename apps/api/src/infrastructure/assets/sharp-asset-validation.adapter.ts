import { lookup } from "node:dns/promises";
import { request } from "node:https";
import { isIP } from "node:net";
import sharp from "sharp";
import type { AssetValidationInput, AssetValidationPort, ValidatedAsset } from "../../application/ports/asset-validation.port.js";
import { AppError } from "../../shared/errors/app-error.js";

const MAX_DOWNLOAD_BYTES = 24 * 1024 * 1024;
const MAX_REDIRECTS = 3;

const isPrivateAddress = (address: string) => {
  const normalized = address.toLowerCase().replace(/^::ffff:/, "");
  if (isIP(normalized) === 4) {
    const [first = 0, second = 0] = normalized.split(".").map(Number);
    return first === 0 || first === 10 || first === 127 || first >= 224 || (first === 169 && second === 254) || (first === 172 && second >= 16 && second <= 31) || (first === 192 && second === 168);
  }
  return normalized === "::" || normalized === "::1" || normalized.startsWith("fc") || normalized.startsWith("fd") || /^fe[89ab]/.test(normalized);
};

/** Converts remote output to stable local bytes and rejects artifacts that cannot fulfill their declared role. */
export class SharpAssetValidationAdapter implements AssetValidationPort {
  async validate(input: AssetValidationInput): Promise<ValidatedAsset> {
    const bytes = input.base64 ? Buffer.from(input.base64, "base64") : await this.download(input.url, input.incurredCost ?? false);
    if (!bytes.length) throw new AppError("ASSET_EMPTY", "Asset contains no image bytes", 422, [], { stage: "asset-validation", incurredCost: input.incurredCost ?? false, manualRetryAllowed: true });
    try {
      const image = sharp(bytes, { failOn: "error" });
      const [metadata, stats] = await Promise.all([image.metadata(), image.stats()]);
      const width = metadata.width ?? 0;
      const height = metadata.height ?? 0;
      if (width < 256 || height < 256) throw new Error("ASSET_RESOLUTION_TOO_LOW");
      const aspect = width / height;
      const aspectDistance = Math.abs(Math.log(aspect / input.targetAspectRatio));
      if (input.role === "full-bleed-background" && aspectDistance > 0.45) throw new Error("ASSET_ASPECT_MISMATCH");
      const alpha = stats.channels[3];
      const hasMeaningfulTransparency = Boolean(metadata.hasAlpha && alpha && alpha.min < 245);
      if (input.role === "transparent-cutout" && !hasMeaningfulTransparency) throw new Error("ASSET_TRANSPARENCY_MISSING");
      const normalized = await sharp(bytes).png().toBuffer();
      return { base64: normalized.toString("base64"), width, height, hasMeaningfulTransparency };
    } catch (cause) {
      const reason = cause instanceof Error ? cause.message : "ASSET_DECODE_FAILED";
      throw new AppError(reason, "Asset failed role and image integrity validation", 422, [], { stage: "asset-validation", incurredCost: input.incurredCost ?? false, manualRetryAllowed: true });
    }
  }

  private async download(url: string | undefined, incurredCost: boolean, redirects = 0): Promise<Buffer> {
    if (!url) return Buffer.alloc(0);
    const parsed = new URL(url);
    if (parsed.protocol !== "https:") throw new AppError("ASSET_REFERENCE_UNSAFE", "Asset URL must use HTTPS", 400);
    const hostname = parsed.hostname.replace(/^\[|\]$/g, "");
    const addresses = isIP(hostname) ? [{ address: hostname, family: isIP(hostname) }] : await lookup(hostname, { all: true, verbatim: true });
    if (!addresses.length || addresses.some((entry) => isPrivateAddress(entry.address))) throw new AppError("ASSET_REFERENCE_UNSAFE", "Asset host resolves to a non-public address", 400);
    const selected = addresses[0]!;

    // Pin the verified address in the TLS socket lookup. Resolving first and then
    // calling global fetch would leave a DNS-rebinding gap between both operations.
    return await new Promise<Buffer>((resolve, reject) => {
      const operation = request(parsed, {
        lookup: (_hostname, _options, callback) => callback(null, selected.address, selected.family as 4 | 6)
      }, (response) => {
        const status = response.statusCode ?? 0;
        if (status >= 300 && status < 400 && response.headers.location) {
          response.resume();
          if (redirects >= MAX_REDIRECTS) return reject(new AppError("ASSET_REDIRECT_LIMIT", "Asset redirect limit exceeded", 422));
          const next = new URL(response.headers.location, parsed).toString();
          void this.download(next, incurredCost, redirects + 1).then(resolve, reject);
          return;
        }
        if (status < 200 || status >= 300) {
          response.resume();
          reject(new AppError("ASSET_DOWNLOAD_FAILED", `Asset download failed with HTTP ${status}`, 502, [], { stage: "asset-validation", incurredCost, manualRetryAllowed: true }));
          return;
        }
        const declaredLength = Number(response.headers["content-length"] ?? 0);
        if (declaredLength > MAX_DOWNLOAD_BYTES) {
          response.destroy();
          reject(new AppError("ASSET_TOO_LARGE", "Asset exceeds the download limit", 422, [], { stage: "asset-validation", incurredCost, manualRetryAllowed: true }));
          return;
        }
        const chunks: Buffer[] = [];
        let total = 0;
        response.on("data", (chunk: Buffer) => {
          total += chunk.length;
          if (total > MAX_DOWNLOAD_BYTES) response.destroy(new AppError("ASSET_TOO_LARGE", "Asset exceeds the download limit", 422, [], { stage: "asset-validation", incurredCost, manualRetryAllowed: true }));
          else chunks.push(chunk);
        });
        response.on("end", () => resolve(Buffer.concat(chunks)));
        response.on("error", reject);
      });
      operation.setTimeout(60_000, () => operation.destroy(new AppError("ASSET_DOWNLOAD_TIMEOUT", "Asset download timed out", 504, [], { stage: "asset-validation", incurredCost, manualRetryAllowed: true })));
      operation.on("error", reject);
      operation.end();
    });
  }
}
