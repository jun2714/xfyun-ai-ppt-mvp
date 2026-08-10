import sharp from "sharp";
import type { SceneGraph, SceneNode } from "@sparkdeck/presentation-model";
import type { ContactSheetPort } from "../../application/ports/contact-sheet.port.js";

const xml = (value: unknown) => String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
const textLines = (text: string, width: number, fontSize: number) => {
  const max = Math.max(1, Math.floor(width / fontSize));
  return text.split("\n").flatMap((line) => Array.from({ length: Math.max(1, Math.ceil([...line].length / max)) }, (_, index) => [...line].slice(index * max, (index + 1) * max).join("")));
};
const renderNode = (node: SceneNode) => {
  const { x, y, width, height } = node.bounds;
  if (node.kind === "shape") return `<rect x="${x}" y="${y}" width="${width}" height="${height}" rx="${Number(node.style.radius ?? 0)}" fill="${xml(node.style.fill ?? "#FFFFFF")}" fill-opacity="${Number(node.style.opacity ?? 1)}"/>`;
  if (node.kind === "image") {
    const href = typeof node.content.dataUri === "string" ? node.content.dataUri : typeof node.content.url === "string" ? node.content.url : "";
    return href ? `<image x="${x}" y="${y}" width="${width}" height="${height}" preserveAspectRatio="${node.content.fit === "contain" ? "xMidYMid meet" : "xMidYMid slice"}" href="${xml(href)}"/>` : `<rect x="${x}" y="${y}" width="${width}" height="${height}" fill="#E5E7EB"/><text x="${x + width / 2}" y="${y + height / 2}" text-anchor="middle" font-size="18" fill="#6B7280">image unresolved</text>`;
  }
  if (node.kind === "chart" && Array.isArray(node.content.rows)) {
    const values = (node.content.rows as unknown[]).slice(1).map((row) => Array.isArray(row) ? Number(row[1] ?? 0) : 0);
    const max = Math.max(1, ...values); const barWidth = width / Math.max(1, values.length) * 0.55;
    return values.map((value, index) => { const barHeight = height * 0.8 * value / max; return `<rect x="${x + index * width / values.length + barWidth * 0.4}" y="${y + height - barHeight}" width="${barWidth}" height="${barHeight}" fill="#2D7A50"/>`; }).join("");
  }
  if (node.kind === "text") {
    const fontSize = Number(node.style.fontSize ?? 18); const lines = textLines(String(node.content.text ?? ""), width, fontSize);
    const anchor = node.style.align === "center" ? "middle" : node.style.align === "right" ? "end" : "start";
    const tx = anchor === "middle" ? x + width / 2 : anchor === "end" ? x + width : x;
    return `<text x="${tx}" y="${y + fontSize}" text-anchor="${anchor}" font-family="${xml(node.style.fontFamily ?? "sans-serif")}" font-size="${fontSize}" font-weight="${Number(node.style.fontWeight ?? 400)}" fill="${xml(node.style.color ?? "#111111")}">${lines.map((line, index) => `<tspan x="${tx}" dy="${index === 0 ? 0 : fontSize * 1.2}">${xml(line)}</tspan>`).join("")}</text>`;
  }
  return "";
};

export class SvgContactSheetAdapter implements ContactSheetPort {
  async render(scene: SceneGraph, pageIds: string[]): Promise<string> {
    const pages = pageIds.map((id) => scene.pages.find((page) => page.id === id)).filter((page): page is SceneGraph["pages"][number] => Boolean(page));
    const columns = Math.min(3, Math.max(1, pages.length)); const tileWidth = 400; const scale = tileWidth / scene.canvas.width; const tileHeight = scene.canvas.height * scale; const labelHeight = 34; const rows = Math.ceil(pages.length / columns);
    const width = columns * tileWidth; const height = rows * (tileHeight + labelHeight);
    const content = pages.map((page, index) => { const column = index % columns; const row = Math.floor(index / columns); const tx = column * tileWidth; const ty = row * (tileHeight + labelHeight); return `<g transform="translate(${tx} ${ty})"><rect width="${tileWidth}" height="${tileHeight}" fill="${page.background}"/><g transform="scale(${scale})">${[...page.nodes].sort((a, b) => a.zIndex - b.zIndex).map(renderNode).join("")}</g><rect y="${tileHeight}" width="${tileWidth}" height="${labelHeight}" fill="#111827"/><text x="12" y="${tileHeight + 23}" font-family="sans-serif" font-size="15" fill="#FFFFFF">${xml(page.id)}</text></g>`; }).join("");
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">${content}</svg>`;
    const png = await sharp(Buffer.from(svg)).png().toBuffer();
    return `data:image/png;base64,${png.toString("base64")}`;
  }
}
