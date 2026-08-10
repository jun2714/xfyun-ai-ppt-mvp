import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve, sep } from "node:path";
import { promisify } from "node:util";
import sharp from "sharp";
import { RenderEvidenceSchema, versioned, type SceneGraph } from "@sparkdeck/presentation-model";
import type { RenderEvidencePort } from "../../application/ports/render-evidence.port.js";
import { AppError } from "../../shared/errors/app-error.js";
import { renderScenePagePng } from "./svg-contact-sheet.adapter.js";

const run = promisify(execFile);
const digest = (value: Uint8Array) => createHash("sha256").update(value).digest("hex");
const OFFICE_EXPORT_SCRIPT = String.raw`
$ErrorActionPreference='Stop'
$deck=$null
$app=$null
try {
  $app=New-Object -ComObject $env:SPARKDECK_OFFICE_PROGRAM_ID
  $deck=$app.Presentations.Open($env:SPARKDECK_RENDER_PPTX,$true,$true,$false)
  # Office chart parts finish materializing after Open returns; exporting immediately can omit them.
  [System.Threading.Thread]::Sleep(800)
  $deck.Export($env:SPARKDECK_RENDER_IMAGES,'PNG',1280,720)
} finally {
  if ($null -ne $deck) { $deck.Close() }
  if ($null -ne $app) { $app.Quit() }
}`;

/** Uses the installed WPS/PowerPoint rendering engine, so acceptance pixels come from a real target office application. */
export class OfficeRenderEvidenceAdapter implements RenderEvidencePort {
  constructor(private readonly programId: string) {
    if (!/^[A-Za-z0-9.]+$/.test(programId)) throw new Error("INVALID_OFFICE_PROGRAM_ID");
  }

  async create(scene: SceneGraph, pptxBytes: Uint8Array) {
    const root = await mkdtemp(join(tmpdir(), "sparkdeck-office-render-"));
    const safeRoot = resolve(tmpdir()) + sep;
    if (!resolve(root).startsWith(safeRoot)) throw new AppError("EXPORT_TEMP_PATH_INVALID", "Render workspace is outside the operating-system temp directory", 500);
    try {
      const pptxPath = join(root, "deck.pptx");
      const imageRoot = join(root, "slides");
      await writeFile(pptxPath, pptxBytes);
      try {
        await run("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", OFFICE_EXPORT_SCRIPT], { windowsHide: true, timeout: 120_000, env: { ...process.env, SPARKDECK_RENDER_PPTX: pptxPath, SPARKDECK_RENDER_IMAGES: imageRoot, SPARKDECK_OFFICE_PROGRAM_ID: this.programId } });
      } catch (cause) {
        throw new AppError("EXPORT_RENDER_FAILED", cause instanceof Error ? cause.message : "Office rendering failed", 500, [], { stage: "rendering", presentationId: scene.presentationId, incurredCost: false, manualRetryAllowed: true });
      }
      const renderedFiles = (await readdir(imageRoot)).filter((name) => /^(?:幻灯片|slide)\s*\d+\.png$/i.test(name)).sort((left, right) => Number(left.match(/\d+/)?.[0]) - Number(right.match(/\d+/)?.[0]));
      if (renderedFiles.length !== scene.pages.length) throw new AppError("EXPORT_RENDER_PAGE_COUNT_INVALID", "Rendered page count does not match Scene Graph", 500);
      const pages = [];
      const renderedPngs: Buffer[] = [];
      for (let index = 0; index < scene.pages.length; index += 1) {
        const page = scene.pages[index]!;
        const scenePng = await renderScenePagePng(page, 1280);
        const pptxPng = await readFile(join(imageRoot, renderedFiles[index]!));
        renderedPngs.push(pptxPng);
        const width = 960;
        const height = Math.round(width * page.height / page.width);
        // Blurring removes anti-aliasing noise while preserving geometry, crop, missing media and text-flow divergence.
        const left = await sharp(scenePng).resize(width, height, { fit: "fill" }).removeAlpha().blur(1).raw().toBuffer();
        const right = await sharp(pptxPng).resize(width, height, { fit: "fill" }).removeAlpha().blur(1).raw().toBuffer();
        let difference = 0;
        for (let offset = 0; offset < left.length; offset += 1) difference += Math.abs(left[offset]! - right[offset]!);
        pages.push({ pageId: page.id, sceneImageHash: digest(scenePng), pptxImageHash: digest(pptxPng), differenceScore: difference / (left.length * 255), width, height });
      }
      const payload = { presentationId: scene.presentationId, pages, passed: pages.every((page) => page.differenceScore <= 0.08), pptxHash: digest(pptxBytes) };
      const tileWidth = 400;
      const tileHeight = Math.round(tileWidth * scene.canvas.height / scene.canvas.width);
      const labelHeight = 34;
      const columns = Math.min(3, Math.max(1, renderedPngs.length));
      const rows = Math.ceil(renderedPngs.length / columns);
      const tileLayers = await Promise.all(renderedPngs.flatMap((png, index) => {
        const left = index % columns * tileWidth;
        const top = Math.floor(index / columns) * (tileHeight + labelHeight);
        const safeId = scene.pages[index]!.id.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
        return [
          sharp(png).resize(tileWidth, tileHeight, { fit: "fill" }).png().toBuffer().then((input) => ({ input, left, top })),
          Promise.resolve({ input: Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="${tileWidth}" height="${labelHeight}"><rect width="100%" height="100%" fill="#111827"/><text x="12" y="23" font-family="sans-serif" font-size="15" fill="#FFFFFF">${safeId}</text></svg>`), left, top: top + tileHeight })
        ];
      }));
      const contactSheet = await sharp({ create: { width: columns * tileWidth, height: rows * (tileHeight + labelHeight), channels: 3, background: "#111827" } })
        .composite(tileLayers)
        .png().toBuffer();
      return { evidence: RenderEvidenceSchema.parse(versioned(payload, 0, { scene: scene.contentHash })), contactSheetDataUri: `data:image/png;base64,${contactSheet.toString("base64")}` };
    } finally {
      // The exact directory was created by mkdtemp under tmpdir and verified above.
      await rm(root, { recursive: true, force: true });
    }
  }
}
