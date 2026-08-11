import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";

const repositoryRoot = process.cwd();
const templateFile = path.join(repositoryRoot, "templates", "kindergarten-recognition", "template.json");
const source = await readFile(templateFile, "utf8");
const template = JSON.parse(source);
assert.equal(template.id, "kindergarten-recognition");
assert.ok(Array.isArray(template.layouts) && template.layouts.length >= 8, "recognition template needs a reusable layout set");
assert.equal(new Set(template.layouts.map((layout) => layout.id)).size, template.layouts.length, "layout IDs must be unique");

const elements = template.layouts.flatMap((layout) => layout.components ?? []).flatMap((component) => component.elements ?? []);
const images = elements.filter((element) => element.type === "image");
const texts = elements.filter((element) => element.type === "text");
assert.ok(images.length > 0, "recognition layouts must expose replaceable image slots");
assert.ok(texts.length > 0, "recognition layouts must expose editable text slots");
assert.ok(images.every((image) => image.data === "/static/images/replaceable_template_image.png"), "source images must use the replaceable placeholder");
assert.ok(images.every((image) => image.decorative === false), "recognition image slots must remain replaceable content");
assert.ok(texts.every((text) => Array.isArray(text.runs) && text.runs.length > 0), "editable text elements must have runs for hydration");

console.log(`recognition template audit passed: ${template.layouts.length} layouts, ${images.length} image slots, ${texts.length} text elements`);
