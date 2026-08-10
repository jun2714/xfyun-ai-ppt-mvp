import { existsSync, readdirSync } from "node:fs";
import { extname, join } from "node:path";
import { openSync, type Font, type FontCollection } from "fontkit";
import { ConservativeTextMeasurer, type TextMeasureInput, type TextMeasureResult, type TextMeasurer } from "@sparkdeck/quality-engine";

type FontRecord = { font: Font; family: string; weight: number };

const weightOf = (font: Font) => {
  const name = `${font.subfamilyName ?? ""} ${font.postscriptName ?? ""}`.toLowerCase();
  if (/thin/.test(name)) return 100;
  if (/extra.?light|ultra.?light/.test(name)) return 200;
  if (/light/.test(name)) return 300;
  if (/medium/.test(name)) return 500;
  if (/semi.?bold|demi.?bold/.test(name)) return 600;
  if (/extra.?bold|ultra.?bold/.test(name)) return 800;
  if (/black|heavy/.test(name)) return 900;
  if (/bold/.test(name)) return 700;
  return 400;
};

/** Measures installed font glyph advances, matching office rendering more closely than character-count estimates. */
export class FontkitTextMeasurerAdapter implements TextMeasurer {
  private registry?: FontRecord[];
  private readonly fallback = new ConservativeTextMeasurer();

  measure(input: TextMeasureInput): TextMeasureResult {
    const font = this.resolve(input.fontFamily, input.fontWeight);
    if (!font) return this.fallback.measure(input);
    const widthOf = (text: string) => font.layout(text).positions.reduce((sum, position) => sum + position.xAdvance, 0) * input.fontSize / font.unitsPerEm;
    const lineWidths: number[] = [];
    for (const paragraph of input.text.split("\n")) {
      let current = 0;
      const segments = [...new Intl.Segmenter(undefined, { granularity: "word" }).segment(paragraph)].map((item) => item.segment);
      for (const segment of segments.length ? segments : [""]) {
        const segmentWidth = widthOf(segment);
        if (current > 0 && current + segmentWidth > input.maxWidth) { lineWidths.push(current); current = 0; }
        if (segmentWidth <= input.maxWidth) { current += segmentWidth; continue; }
        for (const character of segment) {
          const characterWidth = widthOf(character);
          if (current > 0 && current + characterWidth > input.maxWidth) { lineWidths.push(current); current = 0; }
          current += characterWidth;
        }
      }
      lineWidths.push(current);
    }
    const lines = Math.max(1, lineWidths.length);
    return { width: Math.min(input.maxWidth, Math.max(...lineWidths, 0)), height: lines * input.fontSize * input.lineHeight, lines };
  }

  private resolve(family: string, weight: number): Font | undefined {
    this.registry ??= this.loadRegistry();
    const normalized = family.trim().toLowerCase();
    const candidates = this.registry.filter((record) => record.family === normalized || record.family.includes(normalized) || normalized.includes(record.family));
    return candidates.sort((left, right) => Math.abs(left.weight - weight) - Math.abs(right.weight - weight))[0]?.font;
  }

  /** Font discovery is lazy because most API routes never run visual quality measurement. */
  private loadRegistry(): FontRecord[] {
    const fontRoot = join(process.env.SystemRoot ?? "C:\\Windows", "Fonts");
    if (!existsSync(fontRoot)) return [];
    const records: FontRecord[] = [];
    for (const name of readdirSync(fontRoot)) {
      if (![".ttf", ".otf", ".ttc"].includes(extname(name).toLowerCase())) continue;
      try {
        const opened = openSync(join(fontRoot, name));
        const fonts = "fonts" in opened ? (opened as FontCollection).fonts : [opened as Font];
        for (const font of fonts) if (font.familyName) records.push({ font, family: font.familyName.trim().toLowerCase(), weight: weightOf(font) });
      } catch { /* A corrupt or unsupported system font must not stop deck quality checks. */ }
    }
    return records;
  }
}
