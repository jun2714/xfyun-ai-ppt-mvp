import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const templateDirectory = path.resolve(process.argv[2] ?? "");
if (!process.argv[2]) {
  throw new Error("usage: node scripts/apply-template-metadata.mjs <template-directory>");
}

const templatePath = path.join(templateDirectory, "template.json");
const metadataPath = path.join(templateDirectory, "layout-metadata.json");
const template = JSON.parse(await readFile(templatePath, "utf8"));
const metadata = JSON.parse(await readFile(metadataPath, "utf8"));
const layouts = Array.isArray(template.layouts) ? template.layouts : [];

for (const layout of layouts) {
  if (!metadata[layout.id]) {
    throw new Error(`metadata missing for layout ${layout.id}`);
  }
  layout.metadata = metadata[layout.id];

  const editableImages = [];
  const visit = (value) => {
    if (Array.isArray(value)) {
      value.forEach(visit);
      return;
    }
    if (!value || typeof value !== "object") return;
    if (value.type === "image" && value.decorative === false) {
      editableImages.push(value);
    }
    Object.values(value).forEach(visit);
  };
  visit(layout.components);

  const isBackground = metadata[layout.id].media.backgroundSlots === 1;
  const isSprite = editableImages.length > 1;
  for (const image of editableImages) {
    image.asset_role = isBackground ? "background" : "cutout";
    image.asset_mode = isBackground
      ? "direct-background"
      : isSprite
      ? "sprite-sheet"
      : "single-cutout";
    image.asset_group = isSprite ? `${layout.id}-subjects` : undefined;
    image.aspect_ratio = isBackground ? "16:9" : "1:1";
    image.text_safe_area = isBackground ? "center" : "none";
    image.required = true;
  }

  if (isBackground) {
    const background = editableImages[0];
    background.position = { x: 0, y: 0 };
    background.size = { width: 1280, height: 720 };
    background.fit = "cover";
    for (const component of layout.components ?? []) {
      const elements = component.elements ?? [];
      const backgroundIndex = elements.indexOf(background);
      if (backgroundIndex > 0) {
        elements.splice(backgroundIndex, 1);
        elements.unshift(background);
      }
      for (const element of elements) {
        const points = element.type === "vector" ? element.points : null;
        if (!Array.isArray(points) || points.length !== 4) continue;
        const xs = points.map((point) => Number(point.x));
        const ys = points.map((point) => Number(point.y));
        const coversCanvas =
          Math.min(...xs) <= 0 &&
          Math.min(...ys) <= 0 &&
          Math.max(...xs) >= 1280 &&
          Math.max(...ys) >= 720;
        if (coversCanvas && element.fill && element !== background) {
          element.fill.opacity = Math.min(Number(element.fill.opacity ?? 1), 0.72);
        }
      }
    }
  }
}

const unknown = Object.keys(metadata).filter(
  (layoutId) => !layouts.some((layout) => layout.id === layoutId)
);
if (unknown.length) {
  throw new Error(`metadata contains unknown layouts: ${unknown.join(", ")}`);
}

await writeFile(templatePath, `${JSON.stringify(template, null, 2)}\n`, "utf8");
