import { versioned, type AssetBundlePlan, type NarrativeOutline, type QualityReport, type RenderEvidence, type SceneGraph, type SceneNode } from "@sparkdeck/presentation-model";
import { contrast } from "@sparkdeck/design-language";

export type TextMeasureInput = { text: string; fontFamily: string; fontSize: number; fontWeight: number; maxWidth: number; lineHeight: number };
export type TextMeasureResult = { width: number; height: number; lines: number };
export interface TextMeasurer { measure(input: TextMeasureInput): TextMeasureResult }

export class ConservativeTextMeasurer implements TextMeasurer {
  measure(input: TextMeasureInput): TextMeasureResult {
    const unit = (value: string) => [...value].reduce((sum, character) => sum + (/[⺀-鿿]/u.test(character) ? 1 : 0.56), 0);
    const perLine = Math.max(1, input.maxWidth / input.fontSize);
    const lines = input.text.split("\n").reduce((sum, line) => sum + Math.max(1, Math.ceil(unit(line) / perLine)), 0);
    return { width: Math.min(input.maxWidth, unit(input.text) * input.fontSize), height: lines * input.fontSize * input.lineHeight, lines };
  }
}

const intersects = (left: SceneNode["bounds"], right: SceneNode["bounds"]) => left.x < right.x + right.width && left.x + left.width > right.x && left.y < right.y + right.height && left.y + left.height > right.y;
const containsCenter = (container: SceneNode["bounds"], target: SceneNode["bounds"]) => {
  const x = target.x + target.width / 2;
  const y = target.y + target.height / 2;
  return x >= container.x && x <= container.x + container.width && y >= container.y && y <= container.y + container.height;
};
const visibleOverlapAllowed = (left: SceneNode, right: SceneNode) => {
  if (left.kind === "image" && left.content.mediaRole === "full-bleed-background") return true;
  if (right.kind === "image" && right.content.mediaRole === "full-bleed-background") return true;
  if (left.kind === "connector" || right.kind === "connector") return true;
  if (left.kind === "shape" && right.kind === "shape" && left.style.decorative === true && right.style.decorative === true) return true;
  const shape = left.kind === "shape" ? left : right.kind === "shape" ? right : undefined;
  const other = shape === left ? right : left;
  if (shape?.style.decorative === true && shape.zIndex < other.zIndex && containsCenter(shape.bounds, other.bounds)) return true;
  return false;
};
const pageSignature = (page: SceneGraph["pages"][number]) => page.nodes
  .filter((node) => node.kind !== "shape" && node.content.mediaRole !== "full-bleed-background")
  .map((node) => `${node.kind}:${Math.round(node.bounds.x / page.width * 4)}:${Math.round(node.bounds.y / page.height * 4)}:${Math.round(node.bounds.width / page.width * 4)}:${Math.round(node.bounds.height / page.height * 4)}`)
  .sort().join("|");

export function evaluateScene(scene: SceneGraph, options: { measurer?: TextMeasurer; assetPlan?: AssetBundlePlan; outline?: NarrativeOutline; renderEvidence?: RenderEvidence } = {}): QualityReport {
  const measurer = options.measurer ?? new ConservativeTextMeasurer();
  const issues: QualityReport["issues"] = [];
  const signatures: string[] = [];
  for (const page of scene.pages) {
    const actualSources = new Set(page.nodes.flatMap((node) => node.sourceIds));
    for (const sourceId of page.requiredSourceIds) {
      if (!actualSources.has(sourceId)) issues.push({ code: "REQUIRED_CONTENT_MISSING", dimension: "Content", severity: "error", pageId: page.id, nodeIds: [], message: `Required source is not rendered: ${sourceId}`, repairIntent: "recompose-with-all-required-content" });
    }
    for (const node of page.nodes) {
      const bounds = node.bounds;
      if (bounds.x < 0 || bounds.y < 0 || bounds.x + bounds.width > page.width + 0.01 || bounds.y + bounds.height > page.height + 0.01) {
        issues.push({ code: "NODE_OVERFLOW", dimension: "Export", severity: "error", pageId: page.id, nodeIds: [node.id], message: "Element exceeds the slide canvas", repairIntent: "reflow-inside-safe-area" });
      }
      if (node.kind === "text") {
        if (/(?:negative\s*prompt|safe\s*area|placeholder|image\s*description|layout\s*id|template\s*id|css|html|svg|pptx)/i.test(String(node.content.text ?? ""))) issues.push({ code: "PRODUCTION_COPY_VISIBLE", dimension: "Content", severity: "error", pageId: page.id, nodeIds: [node.id], message: "Audience-facing text contains production language", repairIntent: "remove-production-copy-at-narrative-source" });
        const fontSize = Number(node.style.fontSize ?? 0);
        const minimum = node.content.semantic === "title" ? 28 : node.content.semantic === "caption" ? 14 : 16;
        if (fontSize < minimum) issues.push({ code: "FONT_TOO_SMALL", dimension: "Design", severity: "error", pageId: page.id, nodeIds: [node.id], message: "Text is below its readable minimum", repairIntent: "shorten-copy-or-enlarge-region" });
        const measured = measurer.measure({
          text: String(node.content.text ?? ""), fontFamily: String(node.style.fontFamily ?? "Arial"), fontSize,
          fontWeight: Number(node.style.fontWeight ?? 400), maxWidth: bounds.width, lineHeight: Number(node.style.lineHeight ?? 1.2)
        });
        if (measured.height > bounds.height + 0.5) issues.push({ code: "TEXT_OVERFLOW", dimension: "Design", severity: "error", pageId: page.id, nodeIds: [node.id], message: "Text exceeds its measured text box", repairIntent: "shorten-copy-or-change-composition" });
        if (node.content.semantic === "title" && measured.lines > 1) issues.push({ code: "TITLE_WRAP", dimension: "Design", severity: "error", pageId: page.id, nodeIds: [node.id], message: "Slide title wraps to multiple lines", repairIntent: "shorten-title-or-use-wider-title-region" });
        const supportingShape = page.nodes.filter((candidate) => candidate.kind === "shape" && candidate.zIndex < node.zIndex && containsCenter(candidate.bounds, bounds)).sort((left, right) => right.zIndex - left.zIndex)[0];
        const backgroundColor = supportingShape ? String(supportingShape.style.fill ?? page.background) : page.background;
        const color = String(node.style.color ?? "#000000");
        if (/^#[0-9a-f]{6}$/i.test(color) && /^#[0-9a-f]{6}$/i.test(backgroundColor) && contrast(color, backgroundColor) < 4.5) issues.push({ code: "LOW_CONTRAST", dimension: "Design", severity: "error", pageId: page.id, nodeIds: [node.id], message: "Text contrast is insufficient", repairIntent: "apply-contrast-surface-or-text-color" });
        const imageBelow = page.nodes.some((candidate) => candidate.kind === "image" && candidate.zIndex < node.zIndex && intersects(candidate.bounds, bounds));
        if (imageBelow && !supportingShape) issues.push({ code: "TEXT_ON_IMAGE_UNPROTECTED", dimension: "Design", severity: "error", pageId: page.id, nodeIds: [node.id], message: "Text sits on an image without a contrast surface", repairIntent: "add-text-safe-scrim" });
      }
      if (node.kind === "image" && !node.content.assetId) {
        const required = node.sourceIds.some((sourceId) => page.requiredSourceIds.includes(sourceId));
        issues.push({ code: "ASSET_UNRESOLVED", dimension: "Content", severity: required ? "error" : "warning", pageId: page.id, nodeIds: [node.id], message: "Media placement has no resolved asset", ...(required ? { repairIntent: "resolve-required-asset-or-select-no-image-candidate" } : {}) });
      }
      if (node.kind === "image" && node.content.mediaRole === "full-bleed-background") {
        const coverage = node.bounds.width * node.bounds.height / (page.width * page.height);
        if (coverage < 0.9) issues.push({ code: "WRONG_MEDIA_ROLE", dimension: "Design", severity: "error", pageId: page.id, nodeIds: [node.id], message: "A full-bleed background does not cover the slide", repairIntent: "recompose-background-as-full-bleed" });
      }
    }
    for (let leftIndex = 0; leftIndex < page.nodes.length; leftIndex += 1) {
      for (let rightIndex = leftIndex + 1; rightIndex < page.nodes.length; rightIndex += 1) {
        const left = page.nodes[leftIndex]!;
        const right = page.nodes[rightIndex]!;
        if (intersects(left.bounds, right.bounds) && !visibleOverlapAllowed(left, right)) issues.push({ code: "NODE_OVERLAP", dimension: "Design", severity: "error", pageId: page.id, nodeIds: [left.id, right.id], message: "Visible editable elements overlap", repairIntent: "choose-non-overlapping-candidate" });
      }
    }
    const occupied = page.nodes.filter((node) => node.kind !== "shape" && node.content.mediaRole !== "full-bleed-background").reduce((sum, node) => sum + node.bounds.width * node.bounds.height, 0) / (page.width * page.height);
    if (occupied > 0.88) issues.push({ code: "PAGE_TOO_DENSE", dimension: "Design", severity: "warning", pageId: page.id, nodeIds: [], message: "Page has insufficient breathing room", repairIntent: "reduce-density-or-split-content" });
    if (!page.nodes.some((node) => node.kind === "image" || node.kind === "chart" || node.content.semantic === "metric") && page.nodes.filter((node) => node.kind === "shape").length === 0) issues.push({ code: "VISUAL_ANCHOR_MISSING", dimension: "Design", severity: "warning", pageId: page.id, nodeIds: [], message: "Page has no clear visual anchor", repairIntent: "strengthen-native-or-media-focal-point" });
    signatures.push(pageSignature(page));
  }
  for (let index = 1; index < signatures.length; index += 1) if (signatures[index] === signatures[index - 1]) issues.push({ code: "REPETITIVE_COMPOSITION", dimension: "Coherence", severity: "warning", pageId: scene.pages[index]?.id, nodeIds: [], message: "Adjacent pages have the same composition silhouette", repairIntent: "select-alternative-candidate" });
  if (options.assetPlan) {
    const referencedAssets = new Set(scene.pages.flatMap((page) => page.nodes.map((node) => node.content.assetId).filter((assetId): assetId is string => typeof assetId === "string")));
    for (const assetId of options.assetPlan.resolvedAssetIds) if (!referencedAssets.has(assetId)) issues.push({ code: "UNUSED_GENERATED_ASSET", dimension: "Content", severity: "error", nodeIds: [], message: `Generated asset is not used: ${assetId}`, repairIntent: "remove-unused-generation" });
  }
  if (options.outline) {
    const pageById = new Map(scene.pages.map((page) => [page.id, page]));
    for (const link of options.outline.arc.pageLinks) for (const predicate of link.predicates) {
      if (predicate.kind !== "conceal" && predicate.kind !== "introduce") continue;
      const page = pageById.get(predicate.onPageId);
      if (!page) continue;
      const sources = new Set(page.nodes.flatMap((node) => node.sourceIds));
      const invalid = predicate.kind === "conceal" ? predicate.sourceIds.filter((id) => sources.has(id)) : predicate.sourceIds.filter((id) => !sources.has(id));
      if (invalid.length) issues.push({ code: predicate.kind === "conceal" ? "ANSWER_LEAKED_BEFORE_REVEAL" : "CROSS_PAGE_STATE_MISMATCH", dimension: "Coherence", severity: "error", pageId: page.id, nodeIds: [], message: "Cross-page visibility does not satisfy its narrative predicate", repairIntent: "recompose-linked-page-group-from-predicates" });
    }
  }
  if (options.renderEvidence) {
    const evidenceByPage = new Map(options.renderEvidence.pages.map((page) => [page.pageId, page]));
    for (const page of scene.pages) {
      const evidence = evidenceByPage.get(page.id);
      if (!evidence || evidence.differenceScore > 0.08) issues.push({ code: "PPTX_RENDER_DIVERGENCE", dimension: "Export", severity: "error", pageId: page.id, nodeIds: [], message: "Final PPTX rendering is missing or diverges from the Scene render", repairIntent: "align-exporter-with-scene-render-semantics" });
    }
  }
  const errorCounts = { Content: 0, Design: 0, Coherence: 0, Export: 0 };
  for (const issue of issues) if (issue.severity === "error") errorCounts[issue.dimension] += 1;
  const scores = { Content: Math.max(0, 100 - errorCounts.Content * 20), Design: Math.max(0, 100 - errorCounts.Design * 12), Coherence: Math.max(0, 100 - errorCounts.Coherence * 20), Export: Math.max(0, 100 - errorCounts.Export * 25) };
  // A single deck contact sheet is cheaper than per-page calls and lets vision inspect rhythm and identity continuity.
  const visualReviewPageIds = scene.pages.map((page) => page.id);
  return versioned({ presentationId: scene.presentationId, passed: !issues.some((issue) => issue.severity === "error"), scores, issues, visualReviewPageIds, visualReviewStatus: visualReviewPageIds.length ? "pending" as const : "not-required" as const, ...(options.renderEvidence ? { renderEvidenceHash: options.renderEvidence.contentHash } : {}), repairCount: 0 }, 0, { scene: scene.contentHash, ...(options.renderEvidence ? { renderEvidence: options.renderEvidence.contentHash } : {}) });
}

export function buildVisualReviewBatch(scene: SceneGraph, report: QualityReport) {
  return {
    sceneHash: scene.contentHash,
    pageIds: report.visualReviewPageIds,
    dimensions: ["Content", "Design", "Coherence"] as const,
    contactSheetRequired: report.visualReviewPageIds.length > 0,
    maxPaidCalls: report.visualReviewPageIds.length > 0 ? 1 : 0
  };
}

export function applyVisualReview(report: QualityReport, visualIssues: Array<{ pageId: string; dimension: "Content" | "Design" | "Coherence"; severity: "warning" | "error"; message: string; repairIntent: string }>): QualityReport {
  const issues = [...report.issues, ...visualIssues.map((issue) => ({ ...issue, code: "VISUAL_REVIEW", nodeIds: [] }))];
  const visualErrors = visualIssues.filter((issue) => issue.severity === "error");
  const scores = { ...report.scores };
  for (const issue of visualErrors) scores[issue.dimension] = Math.max(0, scores[issue.dimension] - 15);
  return versioned({
    presentationId: report.presentationId,
    passed: report.passed && visualErrors.length === 0,
    scores,
    issues,
    visualReviewPageIds: report.visualReviewPageIds,
    visualReviewStatus: visualErrors.length ? "failed" as const : "passed" as const,
    ...(report.renderEvidenceHash ? { renderEvidenceHash: report.renderEvidenceHash } : {}),
    repairCount: report.repairCount
  }, report.revision + 1, report.upstreamHashes);
}
