import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { OfficeRenderEvidenceAdapter } from "../apps/api/dist/infrastructure/rendering/office-render-evidence.adapter.js";

const scenePath = resolve(process.argv[2] ?? ".runtime/008-offline-qa/scene-graph.json");
const pptxPath = resolve(process.argv[3] ?? ".runtime/008-offline-qa/sparkdeck-008-qa.pptx");
const reportPath = resolve(process.argv[4] ?? ".runtime/008-offline-qa/office-render-report.json");
const programId = process.argv[5] ?? "KWPP.Application";
const scene = JSON.parse(await readFile(scenePath, "utf8"));
const pptx = await readFile(pptxPath);
const result = await new OfficeRenderEvidenceAdapter(programId).create(scene, pptx);
await writeFile(reportPath, JSON.stringify(result.evidence, null, 2), "utf8");
console.log(JSON.stringify({ passed: result.evidence.passed, pages: result.evidence.pages.map((page) => ({ pageId: page.pageId, differenceScore: page.differenceScore })) }));
if (!result.evidence.passed) process.exitCode = 2;
