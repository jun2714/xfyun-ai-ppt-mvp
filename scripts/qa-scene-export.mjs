import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { versioned } from "../packages/presentation-model/dist/index.js";
import { resolveDesignTokens } from "../packages/design-language/dist/index.js";
import { composeDeck } from "../packages/composition-engine/dist/index.js";
import { buildAssetPlan } from "../packages/asset-planning/dist/index.js";
import { compileSceneGraph } from "../packages/scene-graph/dist/index.js";
import { evaluateScene } from "../packages/quality-engine/dist/index.js";
import { exportSceneToPptx } from "../packages/pptx-export/dist/index.js";

const outputDirectory = resolve(process.argv[2] ?? ".runtime/qa");
await mkdir(outputDirectory, { recursive: true });
const brief = versioned({ id: "qa-brief", title: "让每一页只说清一件事", audience: "演示观众", usageContext: "质量验收", objective: "验证原生文本、形状、图表和跨页构图", pageCount: 3, constraints: [], sourceAssetIds: [], language: "zh-CN" });
const pages = [
  { id: "qa-page-1", purpose: "open", headline: "清楚的主线让演示更容易理解", message: "先确定观众要带走什么", contentGroups: [{ id: "qa-g-1", kind: "paragraph", text: "每一页承担一个明确的沟通任务，标题直接说出这一页的结论。", claimIds: [], required: true }], speakerNotes: ["本页用于验证标题、正文和讲者备注。"], evidenceRequests: [], continuityLinks: ["qa-page-2"] },
  { id: "qa-page-2", purpose: "explain", headline: "层级、留白和对齐共同建立阅读顺序", message: "版式不是固定槽位", contentGroups: [{ id: "qa-g-2a", kind: "list", label: "先看", items: ["标题结论", "主要视觉", "必要说明"], claimIds: [], required: true }, { id: "qa-g-2b", kind: "annotation", label: "保持", text: "相邻页面轮廓有变化，但字体、色彩和形状语言保持一致。", claimIds: [], required: true }], speakerNotes: [], evidenceRequests: [], continuityLinks: ["qa-page-1", "qa-page-3"] },
  { id: "qa-page-3", purpose: "close", headline: "同一份 Scene Graph 同时驱动预览与导出", message: "编辑后无需重新理解另一套布局", contentGroups: [{ id: "qa-g-3", kind: "chart-data", label: "一致性检查", rows: [["维度", "得分"], ["内容", 92], ["设计", 88], ["导出", 96]], claimIds: [], required: true }], speakerNotes: [], evidenceRequests: [], continuityLinks: ["qa-page-2"] }
];
const outline = versioned({ briefId: brief.id, pages, confirmedAt: new Date().toISOString() }, 0, { brief: brief.contentHash });
const plan = versioned({
  briefId: brief.id, designSeed: "qa-seed", tone: ["clear", "warm"],
  typography: { character: "clear humanist", headingFamily: "Microsoft YaHei", bodyFamily: "Microsoft YaHei", headingWeight: 700, bodyWeight: 400 },
  palette: { mood: "natural", background: "#F7F4EC", surface: "#FFFFFF", text: "#17372A", primary: "#2D7A50", secondary: "#E58B4A", accent: "#F1C75B", muted: "#CBD8D0" },
  shapeLanguage: { character: "soft", cornerStyle: "soft", strokeStyle: "subtle", motif: "quiet organic edge" },
  densityTarget: "airy", rhythm: { variation: "strong", continuity: ["consistent colors", "consistent type"] }, consistencyRules: ["one focal message per page"]
});
const intents = [
  { pageId: "qa-page-1", focalMessage: pages[0].message, hierarchy: [{ contentGroupId: "qa-g-1", priority: 1 }], groups: [{ id: "qa-dg-1", contentGroupIds: ["qa-g-1"], treatment: "emphasis" }], relationships: [], visualStrategy: "none", balance: "centered", flow: "vertical", density: "low", emphasis: [], mediaRequests: [], avoid: [] },
  { pageId: "qa-page-2", focalMessage: pages[1].message, hierarchy: [{ contentGroupId: "qa-g-2a", priority: 1 }, { contentGroupId: "qa-g-2b", priority: 2 }], groups: [{ id: "qa-dg-2", contentGroupIds: ["qa-g-2a", "qa-g-2b"], treatment: "paired" }], relationships: [{ from: "qa-g-2a", to: "qa-g-2b", kind: "supports" }], visualStrategy: "none", balance: "asymmetric", flow: "horizontal", density: "medium", emphasis: [], mediaRequests: [], avoid: [] },
  { pageId: "qa-page-3", focalMessage: pages[2].message, hierarchy: [{ contentGroupId: "qa-g-3", priority: 1 }], groups: [{ id: "qa-dg-3", contentGroupIds: ["qa-g-3"], treatment: "evidence" }], relationships: [], visualStrategy: "diagram", balance: "centered", flow: "vertical", density: "low", emphasis: [], mediaRequests: [], avoid: [] }
];
const tokens = resolveDesignTokens(plan);
const candidateSets = composeDeck(pages, intents, { width: 960, height: 540 }, tokens);
const assetPlan = buildAssetPlan({ presentationId: "qa-presentation", outline, intents, candidateSets });
const scene = compileSceneGraph({ presentationId: "qa-presentation", outline, intents, candidateSets, tokens, canvas: { width: 960, height: 540 }, assetPlan, assets: {} });
const quality = evaluateScene(scene, { assetPlan });
const artifact = await exportSceneToPptx(scene);
await writeFile(resolve(outputDirectory, "sparkdeck-007-qa.pptx"), artifact.bytes);
await writeFile(resolve(outputDirectory, "qa-report.json"), JSON.stringify({ quality, selected: scene.pages.map((page, index) => ({ pageId: page.id, candidateId: page.selectedCandidateId, strategy: candidateSets[index]?.find((candidate) => candidate.id === page.selectedCandidateId)?.strategy, candidates: candidateSets[index]?.map((candidate) => ({ strategy: candidate.strategy, score: candidate.score, selected: candidate.selected, failures: candidate.hardFailures })), riskFlags: page.riskFlags })), fingerprint: artifact.semanticFingerprint }, null, 2), "utf8");
if (!quality.passed) {
  console.error(JSON.stringify(quality.issues, null, 2));
  process.exitCode = 2;
} else console.log(resolve(outputDirectory, "sparkdeck-007-qa.pptx"));
