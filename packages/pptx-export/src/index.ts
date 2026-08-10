import PptxGenJS from "pptxgenjs";
import type { SceneGraph, SceneNode } from "@sparkdeck/presentation-model";
import { sceneSemanticFingerprint } from "@sparkdeck/scene-graph";

const inch = (points: number) => points / 72;
const color = (value: unknown, fallback: string) => String(value ?? fallback).replace("#", "");
const remoteData = async (url: string) => {
  const response = await fetch(url, { signal: AbortSignal.timeout(120_000) });
  if (!response.ok) throw new Error(`IMAGE_DOWNLOAD_FAILED:${response.status}`);
  const mime = response.headers.get("content-type")?.split(";")[0] ?? "image/png";
  if (!/^image\/(?:png|jpeg|webp)$/i.test(mime)) throw new Error("IMAGE_MIME_INVALID");
  const declaredLength = Number(response.headers.get("content-length") ?? 0);
  if (declaredLength > 24 * 1024 * 1024) throw new Error("IMAGE_TOO_LARGE");
  const bytes = Buffer.from(await response.arrayBuffer());
  if (bytes.length > 24 * 1024 * 1024) throw new Error("IMAGE_TOO_LARGE");
  return `data:${mime};base64,${bytes.toString("base64")}`;
};
const chartSeries = (rows: unknown) => {
  if (!Array.isArray(rows) || rows.length < 2 || !Array.isArray(rows[0])) return [];
  const header = rows[0] as unknown[];
  const categories = rows.slice(1).map((row) => Array.isArray(row) ? String(row[0] ?? "") : "");
  return header.slice(1).map((name, column) => ({
    name: String(name ?? ""),
    labels: categories,
    values: rows.slice(1).map((row) => Array.isArray(row) ? Number(row[column + 1] ?? 0) : 0)
  }));
};

export async function exportSceneToPptx(scene: SceneGraph) {
  const PptxConstructor = PptxGenJS as unknown as { new(): any };
  const pptx = new PptxConstructor();
  pptx.author = "SparkDeck";
  pptx.subject = "Editable presentation generated from SparkDeck Scene Graph";
  pptx.title = scene.presentationId;
  pptx.company = "SparkDeck";
  pptx.lang = "zh-CN";
  pptx.defineLayout({ name: "SCENE", width: inch(scene.canvas.width), height: inch(scene.canvas.height) });
  pptx.layout = "SCENE";
  for (const page of scene.pages) {
    const slide = pptx.addSlide();
    slide.background = { color: color(page.background, "FFFFFF") };
    if (page.speakerNotes.length) slide.addNotes(page.speakerNotes.join("\n"));
    for (const node of [...page.nodes].sort((left, right) => left.zIndex - right.zIndex)) {
      const box = { x: inch(node.bounds.x), y: inch(node.bounds.y), w: inch(node.bounds.width), h: inch(node.bounds.height) };
      if (node.kind === "text") {
        slide.addText(String(node.content.text ?? ""), {
          ...box,
          fontFace: String(node.style.fontFamily ?? "Microsoft YaHei"),
          fontSize: Number(node.style.fontSize ?? 18),
          bold: Number(node.style.fontWeight ?? 400) >= 600,
          color: color(node.style.color, "111111"),
          margin: 0.04,
          rotate: Number(node.style.rotation ?? 0),
          breakLine: false,
          valign: node.style.verticalAlign === "top" ? "top" : node.style.verticalAlign === "bottom" ? "bottom" : "mid",
          align: node.style.align === "center" ? "center" : node.style.align === "right" ? "right" : "left",
          paraSpaceAfterPt: Number(node.style.fontSize ?? 18) * 0.18,
          lineSpacingMultiple: Number(node.style.lineHeight ?? 1.2)
        });
      } else if (node.kind === "shape") {
        const rounded = Number(node.style.radius ?? 0) > 0;
        const opacity = Math.max(0, Math.min(1, Number(node.style.opacity ?? 1)));
        slide.addShape(rounded ? pptx.ShapeType.roundRect : pptx.ShapeType.rect, {
          ...box,
          rectRadius: rounded ? Math.min(box.w, box.h) * 0.12 : 0,
          fill: { color: color(node.style.fill, "FFFFFF"), transparency: Math.round((1 - opacity) * 100) },
          line: { color: color(node.style.stroke, node.style.fill as string ?? "FFFFFF"), transparency: Number(node.style.strokeWidth ?? 1) <= 0 ? 100 : 0, width: Number(node.style.strokeWidth ?? 1) },
          rotate: Number(node.style.rotation ?? 0)
        });
      } else if (node.kind === "image") {
        let data = typeof node.content.dataUri === "string" ? node.content.dataUri : undefined;
        if (!data && typeof node.content.url === "string") data = await remoteData(node.content.url);
        if (data) slide.addImage({ data, x: box.x, y: box.y, sizing: { type: node.content.fit === "contain" ? "contain" : "cover", w: box.w, h: box.h }, rounding: Number(node.style.radius ?? 0) > 0, rotate: Number(node.style.rotation ?? 0) });
      } else if (node.kind === "chart") {
        const series = chartSeries(node.content.rows);
        const maximum = Math.max(1, ...series.flatMap((item) => item.values));
        if (series.length) slide.addChart(pptx.ChartType.bar, series, {
          ...box,
          barDir: "col",
          catAxisLabelFontFace: String(scene.theme.bodyFontFamily ?? "Microsoft YaHei"),
          catAxisLabelFontSize: 12,
          valAxisLabelFontSize: 11,
          showLegend: series.length > 1,
          showTitle: false,
          showValue: false,
          catAxisHidden: true,
          valAxisHidden: true,
          valAxisMinVal: 0,
          valAxisMaxVal: maximum * 1.25,
          valGridLine: { style: "none" },
          chartColors: [color(scene.theme.primary, "4F9C67")],
          showCatName: false,
          showSerName: false,
          showPercent: false
        });
      } else if (node.kind === "connector") {
        slide.addShape(pptx.ShapeType.line, { ...box, flipH: node.content.flipH === true, flipV: node.content.flipV === true, line: { color: color(node.style.stroke, "333333"), width: Number(node.style.strokeWidth ?? 1.5), beginArrowType: "none", endArrowType: "triangle" } });
      }
    }
  }
  const data = await pptx.write({ outputType: "arraybuffer" });
  return { bytes: new Uint8Array(data as ArrayBuffer), semanticFingerprint: sceneSemanticFingerprint(scene) };
}
