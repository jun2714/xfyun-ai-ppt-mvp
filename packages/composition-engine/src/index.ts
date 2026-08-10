import {
  hashContent,
  type Bounds,
  type CompositionCandidate,
  type CompositionNode,
  type ContentGroup,
  type CrossPageConstraint,
  type DeckDesignPlan,
  type NarrativeOutline,
  type NarrativePage,
  type PageDesignIntent,
  type PageRelationPredicate
} from "@sparkdeck/presentation-model";
import type { DesignTokens } from "@sparkdeck/design-language";

export type Canvas = { width: number; height: number };
export type ResolvedCompositionNode = {
  id: string;
  kind: CompositionNode["kind"];
  sourceIds: string[];
  bounds: Bounds;
  props: Record<string, unknown>;
  children: ResolvedCompositionNode[];
};
export type ResolvedCandidate = CompositionCandidate & { resolved: ResolvedCompositionNode };
export type RelationConstraint = { id: string; pageIds: string[]; predicate: PageRelationPredicate };
export type RepairConstraint = { id: string; pageId: string; issueCodes: string[]; forbiddenGrammarHashes: string[] };

/**
 * Compiles narrative relationships into pure semantic constraints.
 * Returning geometry or composition trees here would recreate a hidden page-template mapping.
 */
export class RelationConstraintCompiler {
  compile(outline: NarrativeOutline, design: DeckDesignPlan): RelationConstraint[] {
    const fromNarrative = outline.arc.pageLinks.flatMap((link) => link.predicates.map((predicate, index) => ({
      id: `${link.id}:predicate:${index}`,
      pageIds: [link.fromPageId, link.toPageId],
      predicate
    })));
    const fromDesign = design.crossPageConstraints.flatMap((constraint: CrossPageConstraint) => constraint.predicates.map((predicate, index) => ({
      id: `${constraint.id}:predicate:${index}`,
      pageIds: constraint.pageIds,
      predicate
    })));
    return [...fromNarrative, ...fromDesign];
  }
}

const primitive = (kind: CompositionNode["kind"], id: string, sourceIds: string[], props: Record<string, unknown> = {}, children?: CompositionNode[]): CompositionNode => ({
  kind, id, sourceIds, props, ...(children ? { children } : {})
});
const groupText = (group: ContentGroup) => {
  const prefix = group.label ? `${group.label}\n` : "";
  if (group.text) return `${prefix}${group.text}`;
  if (group.items?.length) return `${prefix}${group.items.map((item) => `• ${item}`).join("\n")}`;
  return `${prefix}${group.rows?.map((row) => row.join("  ·  ")).join("\n") ?? ""}`;
};
const hierarchyOrder = (page: NarrativePage, intent: PageDesignIntent) => {
  const rank = new Map(intent.hierarchy.map((item) => [item.contentGroupId, item.priority]));
  return [...page.contentGroups].sort((left, right) => (rank.get(left.id) ?? 5) - (rank.get(right.id) ?? 5));
};
const textUnits = (value: string) => [...value].reduce((sum, character) => sum + (/[⺀-鿿]/u.test(character) ? 1 : 0.55), 0);
const clamp = (value: number, minimum: number, maximum: number) => Math.max(minimum, Math.min(maximum, value));

type CandidateFeatures = CompositionCandidate["features"];
type InputMetrics = {
  contentCount: number;
  mediaCount: number;
  foregroundMediaCount: number;
  relationshipCount: number;
  textUnits: number;
  hierarchySpread: number;
  motifCount: number;
};

const metricsOf = (page: NarrativePage, intent: PageDesignIntent, design: DeckDesignPlan): InputMetrics => {
  const priorities = intent.hierarchy.map((item) => item.priority);
  return {
    contentCount: page.contentGroups.length,
    mediaCount: intent.mediaRequests.length,
    foregroundMediaCount: intent.mediaRequests.filter((request) => request.role !== "full-bleed-background").length,
    relationshipCount: intent.relationships.length,
    textUnits: textUnits([page.headline, ...page.contentGroups.map(groupText), ...(page.audienceAction?.visible ? [page.audienceAction.instruction] : [])].join("\n")),
    hierarchySpread: priorities.length ? Math.max(...priorities) - Math.min(...priorities) : 0,
    motifCount: design.visualGrammar.motifRules.length
  };
};

const contentLeaf = (page: NarrativePage, group: ContentGroup, index: number) => primitive(
  group.kind === "chart-data" ? "Chart" : "Text",
  `${page.id}:content:${index}`,
  [group.id],
  {
    contentGroupId: group.id,
    contentKind: group.kind,
    text: groupText(group),
    required: group.required,
    grow: clamp(0.75 + textUnits(groupText(group)) / 90, 0.75, 1.75),
    semantic: group.kind === "metric" ? "metric" : group.kind === "caption" ? "caption" : "body"
  }
);
const mediaLeaf = (page: NarrativePage, request: PageDesignIntent["mediaRequests"][number], index: number) => primitive(
  "Image",
  `${page.id}:media:${index}`,
  [request.id, request.identityId],
  {
    requestId: request.id,
    identityId: request.identityId,
    mediaRole: request.role,
    fit: request.fit,
    required: request.required,
    grow: request.role === "full-bleed-background" ? 1 : 1.35,
    allowsOverlap: request.role === "full-bleed-background"
  }
);
const titleLeaf = (page: NarrativePage) => primitive("Text", `${page.id}:title`, [page.id], { semantic: "title", text: page.headline, required: true, grow: 0.28 });
const visibleActionLeaf = (page: NarrativePage) => page.audienceAction?.visible
  ? primitive("Text", `${page.id}:audience-action`, [page.id], { semantic: "callout", text: page.audienceAction.instruction, required: true, grow: 0.72 })
  : undefined;
const supportingShape = (page: NarrativePage, suffix: string, treatment: "surface" | "accent" | "motif") => primitive("Shape", `${page.id}:shape:${suffix}`, [], { decorative: true, treatment, allowsOverlap: true });

const featureOptions = (metrics: InputMetrics): CandidateFeatures[] => {
  const anchors: CandidateFeatures["anchor"][] = ["mixed", "text"];
  if (metrics.foregroundMediaCount) anchors.push("media");
  if (metrics.relationshipCount) anchors.push("relation");
  const directions: CandidateFeatures["direction"][] = ["horizontal", "vertical", "layered"];
  if (metrics.contentCount + metrics.foregroundMediaCount >= 3) directions.push("radial");
  const groupings: CandidateFeatures["grouping"][] = ["hierarchy", "parallel", "sequence", "collection"];
  if (metrics.relationshipCount) groupings.push("association");
  const emphases: CandidateFeatures["emphasis"][] = ["single-focus", "balanced", "progressive", "contrast"];
  return anchors.flatMap((anchor) => directions.flatMap((direction) => groupings.flatMap((grouping) => emphases.map((emphasis) => ({ anchor, direction, grouping, emphasis })))));
};

const compatibilityScore = (features: CandidateFeatures, metrics: InputMetrics) => {
  let score = 0;
  if (features.anchor === "media") score += metrics.foregroundMediaCount * 0.25;
  if (features.anchor === "relation") score += metrics.relationshipCount * 0.35;
  if (features.grouping === "association") score += metrics.relationshipCount * 0.3;
  if (features.grouping === "collection") score += Math.max(0, metrics.contentCount + metrics.foregroundMediaCount - 2) * 0.12;
  if (features.grouping === "hierarchy") score += metrics.hierarchySpread * 0.12;
  if (features.direction === "vertical") score += metrics.textUnits > 100 ? 0.25 : 0;
  if (features.direction === "horizontal") score += metrics.foregroundMediaCount ? 0.22 : 0;
  if (features.direction === "radial") score += metrics.relationshipCount ? 0.18 : -0.3;
  if (features.emphasis === "single-focus") score += metrics.contentCount <= 2 ? 0.25 : 0;
  if (features.emphasis === "balanced") score += metrics.contentCount > 2 ? 0.2 : 0;
  return score;
};

const buildGroupedUnits = (page: NarrativePage, features: CandidateFeatures, units: CompositionNode[], metrics: InputMetrics): CompositionNode => {
  const gapScale = clamp(1 - metrics.textUnits / 800, 0.72, 1.1);
  if (features.grouping === "sequence") return primitive("Flow", `${page.id}:group:sequence`, [], { direction: features.direction === "horizontal" ? "horizontal" : "vertical", gapScale }, units);
  if (features.grouping === "collection") {
    const columns = clamp(Math.round(Math.sqrt(Math.max(1, units.length) * (features.direction === "horizontal" ? 1.5 : 1))), 1, Math.max(1, units.length));
    return primitive("Grid", `${page.id}:group:collection`, [], { columns, gapScale }, units);
  }
  if (features.grouping === "parallel" || features.grouping === "association") {
    const columns = features.direction === "vertical" ? 1 : clamp(Math.ceil(units.length / 2), 2, 4);
    return primitive("Grid", `${page.id}:group:${features.grouping}`, [], { columns, gapScale, relationAware: features.grouping === "association" }, units);
  }
  return primitive("Stack", `${page.id}:group:hierarchy`, [], { direction: features.direction === "horizontal" ? "horizontal" : "vertical", gapScale }, units);
};

/** Builds one tree through generic feature composition; no semantic page role selects a stored tree. */
const buildTree = (page: NarrativePage, intent: PageDesignIntent, design: DeckDesignPlan, features: CandidateFeatures, metrics: InputMetrics): CompositionNode => {
  const orderedGroups = hierarchyOrder(page, intent);
  const content = orderedGroups.map((group, index) => contentLeaf(page, group, index));
  const action = visibleActionLeaf(page);
  if (action) content.push(action);
  const media = intent.mediaRequests.map((request, index) => mediaLeaf(page, request, index));
  const backgrounds = media.filter((node) => node.props.mediaRole === "full-bleed-background");
  const foreground = media.filter((node) => node.props.mediaRole !== "full-bleed-background");
  const title = titleLeaf(page);
  const bodyUnits = [...content, ...foreground];
  const dominant = features.anchor === "media" && foreground.length ? foreground : features.anchor === "text" ? content : features.anchor === "relation" ? bodyUnits : [];
  const remaining = bodyUnits.filter((node) => !dominant.includes(node));
  let composedBody: CompositionNode;
  if (dominant.length && remaining.length) {
    const dominance = clamp(0.45 + Math.abs(metrics.foregroundMediaCount - metrics.contentCount) * 0.035, 0.45, 0.64);
    const groups = [
      primitive("Frame", `${page.id}:dominant`, [], { grow: dominance }, [buildGroupedUnits(page, features, dominant, metrics)]),
      primitive("Frame", `${page.id}:supporting`, [], { grow: 1 - dominance }, [buildGroupedUnits(page, features, remaining, metrics)])
    ];
    composedBody = primitive(features.direction === "layered" ? "Overlay" : "Grid", `${page.id}:anchored-body`, [], { columns: features.direction === "vertical" ? 1 : 2 }, groups);
  } else {
    composedBody = buildGroupedUnits(page, features, bodyUnits, metrics);
  }
  // Headline is a semantic peer in the relation solver. Candidate features decide
  // whether it leads a flow, shares a grid, or anchors a layered composition.
  // No page receives an unconditional title band/body band skeleton.
  let semanticComposition: CompositionNode;
  if (features.direction === "layered") {
    semanticComposition = primitive("Overlay", `${page.id}:semantic-overlay`, [], {}, [
      composedBody,
      primitive("Anchor", `${page.id}:headline-anchor`, [], {
        horizontal: features.emphasis === "contrast" ? "end" : "start",
        vertical: features.emphasis === "progressive" ? "end" : "start",
        widthRatio: clamp(0.42 + textUnits(page.headline) / 500, 0.42, 0.72),
        heightRatio: clamp(0.18 + textUnits(page.headline) / 420, 0.18, 0.36),
        allowsOverlap: true
      }, [{ ...title, props: { ...title.props, allowsOverlap: true } }])
    ]);
  } else if (features.anchor === "relation" || features.grouping === "association") {
    semanticComposition = buildGroupedUnits(page, features, [title, ...bodyUnits], metrics);
  } else {
    const headlineFirst = features.emphasis !== "contrast";
    const headlineFrame = primitive("Frame", `${page.id}:headline-group`, [], {
      grow: features.direction === "horizontal" ? 0.58 : clamp(0.18 + textUnits(page.headline) / 360, 0.18, 0.38),
      paddingScale: 0.25
    }, [title]);
    const mainFrame = primitive("Frame", `${page.id}:main-group`, [], { grow: 1 }, [composedBody]);
    semanticComposition = primitive(features.direction === "horizontal" ? "Grid" : "Stack", `${page.id}:semantic-flow`, [], {
      ...(features.direction === "horizontal" ? { columns: 2 } : { direction: "vertical" }), gapScale: 0.72
    }, headlineFirst ? [headlineFrame, mainFrame] : [mainFrame, headlineFrame]);
  }
  const motifCount = Math.min(2, design.visualGrammar.motifRules.length);
  const motifNodes = Array.from({ length: motifCount }, (_, index) => primitive("Anchor", `${page.id}:motif-anchor:${index}`, [], {
    horizontal: hashContent({ page: page.id, index }).charCodeAt(0) % 2 ? "start" : "end",
    vertical: index % 2 ? "start" : "end",
    widthRatio: 0.08 + Math.min(0.08, metrics.motifCount * 0.015),
    heightRatio: 0.08 + Math.min(0.08, metrics.motifCount * 0.015)
  }, [supportingShape(page, `motif:${index}`, "motif")]));
  const connectors = features.anchor === "relation" || features.grouping === "association"
    ? intent.relationships.map((relationship, index) => primitive("Connector", `${page.id}:connector:${index}`, [relationship.from, relationship.to], { fromSourceId: relationship.from, toSourceId: relationship.to, relationKind: relationship.kind, allowsOverlap: true }))
    : [];
  const safeContent = primitive("SafeArea", `${page.id}:safe`, [], {}, [primitive("Overlay", `${page.id}:content-overlay`, [], {}, [
    ...(features.emphasis === "single-focus" ? [supportingShape(page, "focus-surface", "surface")] : []),
    primitive("Frame", `${page.id}:content-frame`, [], { paddingScale: metrics.textUnits > 160 ? 0.72 : 1 }, [semanticComposition])
  ])]);
  return primitive("Canvas", `${page.id}:canvas:${hashContent(features).slice(0, 8)}`, [page.id], {}, [
    primitive("Overlay", `${page.id}:root-overlay`, [], {}, [...backgrounds, ...motifNodes, ...connectors, safeContent])
  ]);
};

const constraintIdsForPage = (pageId: string, constraints: RelationConstraint[]) => constraints.filter((constraint) => constraint.pageIds.includes(pageId)).map((constraint) => constraint.id);

/** Produces a diverse search stream ordered by content-derived compatibility, not by page type. */
export function generateCandidateTrees(page: NarrativePage, intent: PageDesignIntent, design: DeckDesignPlan, constraints: RelationConstraint[], repairConstraints: RepairConstraint[] = []): CompositionCandidate[] {
  const metrics = metricsOf(page, intent, design);
  const options = featureOptions(metrics).sort((left, right) => {
    const delta = compatibilityScore(right, metrics) - compatibilityScore(left, metrics);
    return delta || hashContent(left).localeCompare(hashContent(right));
  });
  const seen = new Set<string>();
  const pageRepairs = repairConstraints.filter((constraint) => constraint.pageId === page.id);
  const forbidden = new Set(pageRepairs.flatMap((constraint) => constraint.forbiddenGrammarHashes));
  const candidates: CompositionCandidate[] = [];
  for (const features of options) {
    const tree = buildTree(page, intent, design, features, metrics);
    const grammarHash = hashContent(tree);
    if (seen.has(grammarHash) || forbidden.has(grammarHash)) continue;
    seen.add(grammarHash);
    candidates.push({
      id: `cand-${hashContent({ pageId: page.id, grammarHash }).slice(0, 16)}`,
      pageId: page.id,
      features,
      grammarHash,
      tree,
      trace: {
        inputMetrics: metrics,
        constraintIds: [...constraintIdsForPage(page.id, constraints), ...pageRepairs.map((constraint) => constraint.id)],
        differences: Object.entries(features).map(([key, value]) => `${key}:${value}`),
        rejectedReasons: []
      },
      score: 0,
      hardFailures: [],
      scoreBreakdown: {},
      silhouette: grammarHash,
      selected: false
    });
  }
  return candidates;
}

const inset = (bounds: Bounds, padding: number): Bounds => ({ x: bounds.x + padding, y: bounds.y + padding, width: Math.max(1, bounds.width - padding * 2), height: Math.max(1, bounds.height - padding * 2) });
const splitWeighted = (bounds: Bounds, children: CompositionNode[], direction: "vertical" | "horizontal", gap: number): Bounds[] => {
  const available = (direction === "vertical" ? bounds.height : bounds.width) - gap * Math.max(0, children.length - 1);
  const weights = children.map((child) => Math.max(0.05, Number(child.props.grow ?? 1)));
  const total = weights.reduce((sum, value) => sum + value, 0) || 1;
  let cursor = direction === "vertical" ? bounds.y : bounds.x;
  return children.map((_, index) => {
    const size = available * weights[index]! / total;
    const result = direction === "vertical" ? { x: bounds.x, y: cursor, width: bounds.width, height: size } : { x: cursor, y: bounds.y, width: size, height: bounds.height };
    cursor += size + gap;
    return result;
  });
};
const fitFont = (text: string, bounds: Bounds, preferred: number, minimum: number, singleLine: boolean) => {
  for (let size = preferred; size >= minimum; size -= 1) {
    const lines = Math.max(1, Math.ceil(textUnits(text) / Math.max(1, bounds.width / size)));
    if (lines * size * 1.22 <= bounds.height && (!singleLine || lines === 1)) return { size, lines, fits: true };
  }
  return { size: minimum, lines: Math.max(1, Math.ceil(textUnits(text) / Math.max(1, bounds.width / minimum))), fits: false };
};

/** Resolves a generic composition tree into deterministic canvas geometry. */
export function solveTree(tree: CompositionNode, canvas: Canvas, tokens: DesignTokens): ResolvedCompositionNode {
  const resolve = (current: CompositionNode, bounds: Bounds): ResolvedCompositionNode => {
    const children = current.children ?? [];
    const gap = tokens.space * Number(current.props.gapScale ?? 1);
    let childBounds: Bounds[] = [];
    if (current.kind === "Canvas") childBounds = children.map(() => ({ x: 0, y: 0, width: canvas.width, height: canvas.height }));
    else if (current.kind === "SafeArea") childBounds = children.map(() => inset(bounds, Math.max(tokens.safeInset, Math.min(canvas.width, canvas.height) * 0.055)));
    else if (current.kind === "Stack" || current.kind === "Flow") childBounds = splitWeighted(bounds, children, (current.props.direction as "vertical" | "horizontal") ?? "vertical", gap);
    else if (current.kind === "Grid") {
      const columns = Math.max(1, Math.min(children.length || 1, Number(current.props.columns ?? 1)));
      const rows = Math.max(1, Math.ceil(children.length / columns));
      const availableWidth = bounds.width - gap * (columns - 1);
      const columnWidth = availableWidth / columns;
      const rowHeight = (bounds.height - gap * (rows - 1)) / rows;
      childBounds = children.map((_, index) => ({ x: bounds.x + (index % columns) * (columnWidth + gap), y: bounds.y + Math.floor(index / columns) * (rowHeight + gap), width: columnWidth, height: rowHeight }));
    } else if (current.kind === "Overlay") childBounds = children.map(() => bounds);
    else if (current.kind === "Anchor") {
      const width = bounds.width * Number(current.props.widthRatio ?? 0.5);
      const height = bounds.height * Number(current.props.heightRatio ?? 0.5);
      const x = current.props.horizontal === "end" ? bounds.x + bounds.width - width : current.props.horizontal === "center" ? bounds.x + (bounds.width - width) / 2 : bounds.x;
      const y = current.props.vertical === "end" ? bounds.y + bounds.height - height : current.props.vertical === "center" ? bounds.y + (bounds.height - height) / 2 : bounds.y;
      childBounds = children.map(() => ({ x, y, width, height }));
    } else if (current.kind === "Frame") {
      const padding = tokens.space * Number(current.props.paddingScale ?? 0.7);
      childBounds = children.length === 1 ? [inset(bounds, padding)] : splitWeighted(inset(bounds, padding), children, "vertical", gap);
    } else childBounds = children.map(() => bounds);
    const props = { ...current.props };
    if (current.kind === "Text") {
      const semantic = String(props.semantic ?? "body");
      const preferred = semantic === "title" ? tokens.titlePt : semantic === "metric" ? tokens.deckTitlePt : semantic === "caption" ? tokens.captionPt : tokens.bodyPt;
      const minimum = semantic === "title" ? 28 : semantic === "caption" ? 14 : 16;
      const result = fitFont(String(props.text ?? ""), bounds, preferred, minimum, semantic === "title");
      props.fontSize = result.size;
      props.estimatedLines = result.lines;
      props.textFits = result.fits;
    }
    return { id: current.id, kind: current.kind, sourceIds: current.sourceIds, bounds, props, children: children.map((child, index) => resolve(child, childBounds[index] ?? bounds)) };
  };
  const initial = resolve(tree, { x: 0, y: 0, width: canvas.width, height: canvas.height });
  const resolvedLeaves = leaves(initial);
  const source = (id: string) => resolvedLeaves.find((node) => node.kind !== "Connector" && node.sourceIds.includes(id));
  const positionConnectors = (node: ResolvedCompositionNode): ResolvedCompositionNode => {
    if (node.kind !== "Connector") return { ...node, children: node.children.map(positionConnectors) };
    const from = source(String(node.props.fromSourceId ?? ""));
    const to = source(String(node.props.toSourceId ?? ""));
    if (!from || !to) return node;
    const fromCenter = { x: from.bounds.x + from.bounds.width / 2, y: from.bounds.y + from.bounds.height / 2 };
    const toCenter = { x: to.bounds.x + to.bounds.width / 2, y: to.bounds.y + to.bounds.height / 2 };
    return { ...node, props: { ...node.props, flipH: toCenter.x < fromCenter.x, flipV: toCenter.y < fromCenter.y }, bounds: { x: Math.min(fromCenter.x, toCenter.x), y: Math.min(fromCenter.y, toCenter.y), width: Math.max(1, Math.abs(toCenter.x - fromCenter.x)), height: Math.max(1, Math.abs(toCenter.y - fromCenter.y)) } };
  };
  return positionConnectors(initial);
}

const leaves = (node: ResolvedCompositionNode): ResolvedCompositionNode[] => node.children.length ? node.children.flatMap(leaves) : [node];
const intersects = (left: Bounds, right: Bounds) => left.x < right.x + right.width && left.x + left.width > right.x && left.y < right.y + right.height && left.y + left.height > right.y;
const silhouetteOf = (items: ResolvedCompositionNode[], canvas: Canvas) => items
  .filter((item) => !item.props.decorative && item.props.mediaRole !== "full-bleed-background")
  .map((item) => `${item.kind}:${Math.round(item.bounds.x / canvas.width * 5)}:${Math.round(item.bounds.y / canvas.height * 5)}:${Math.round(item.bounds.width / canvas.width * 5)}:${Math.round(item.bounds.height / canvas.height * 5)}`)
  .sort().join("|");

/** Scores hard invariants first; a candidate with any hard failure can never be selected. */
export function scoreCandidate(candidate: CompositionCandidate, resolved: ResolvedCompositionNode, canvas: Canvas, requiredSourceIds: string[], repairIssueCodes: string[] = []): ResolvedCandidate {
  const items = leaves(resolved);
  const failures: string[] = [];
  const sourceIds = new Set(items.flatMap((item) => item.sourceIds));
  for (const required of requiredSourceIds) if (!sourceIds.has(required)) failures.push(`MISSING_REQUIRED_SOURCE:${required}`);
  for (const item of items) {
    const bounds = item.bounds;
    if (bounds.x < -0.01 || bounds.y < -0.01 || bounds.x + bounds.width > canvas.width + 0.01 || bounds.y + bounds.height > canvas.height + 0.01) failures.push(`OUT_OF_BOUNDS:${item.id}`);
    if (bounds.width < 1 || bounds.height < 1) failures.push(`EMPTY_BOUNDS:${item.id}`);
    if (item.kind === "Text" && item.props.textFits === false) failures.push(`TEXT_OVERFLOW:${item.id}`);
  }
  for (let leftIndex = 0; leftIndex < items.length; leftIndex += 1) for (let rightIndex = leftIndex + 1; rightIndex < items.length; rightIndex += 1) {
    const left = items[leftIndex]!; const right = items[rightIndex]!;
    if (intersects(left.bounds, right.bounds) && !left.props.allowsOverlap && !right.props.allowsOverlap && !left.props.decorative && !right.props.decorative) failures.push(`UNINTENDED_OVERLAP:${left.id}:${right.id}`);
  }
  const foreground = items.filter((item) => !item.props.decorative && item.props.mediaRole !== "full-bleed-background");
  const occupied = foreground.reduce((sum, item) => sum + item.bounds.width * item.bounds.height, 0) / (canvas.width * canvas.height);
  const centers = foreground.map((item) => (item.bounds.x + item.bounds.width / 2) / canvas.width);
  const center = centers.reduce((sum, value) => sum + value, 0) / Math.max(1, centers.length);
  const hierarchy = foreground.some((item) => item.props.semantic === "title") ? 1 : 0;
  const whitespace = Math.max(0, 1 - Math.abs(0.58 - occupied));
  const balance = Math.max(0, 1 - Math.abs(0.5 - center));
  const density = Math.max(0, 1 - Math.abs(0.5 - occupied));
  const contentCoverage = requiredSourceIds.length ? requiredSourceIds.filter((id) => sourceIds.has(id)).length / requiredSourceIds.length : 1;
  const relationLegibility = candidate.features.anchor === "relation" || candidate.features.grouping === "association" ? 1 : 0.72;
  const nativeShapeContribution = items.some((item) => item.kind === "Shape") ? 1 : 0.65;
  let repairFit = 1;
  if (repairIssueCodes.some((code) => code === "TEXT_OVERFLOW" || code === "TITLE_WRAP")) repairFit *= candidate.features.direction === "vertical" || candidate.features.grouping === "hierarchy" ? 1 : 0.55;
  if (repairIssueCodes.includes("VISUAL_ANCHOR_MISSING")) repairFit *= candidate.features.emphasis === "single-focus" || candidate.features.anchor === "media" ? 1 : 0.6;
  if (repairIssueCodes.includes("REPETITIVE_COMPOSITION")) repairFit *= candidate.features.direction === "layered" || candidate.features.direction === "radial" ? 1 : 0.7;
  const scoreBreakdown = { hierarchy, whitespace, balance, density, contentCoverage, relationLegibility, nativeShapeContribution, repairFit };
  const score = Object.values(scoreBreakdown).reduce((sum, value) => sum + value, 0) / Object.keys(scoreBreakdown).length - failures.length * 10;
  return { ...candidate, resolved, hardFailures: [...new Set(failures)], scoreBreakdown, silhouette: silhouetteOf(items, canvas), score };
}

/** Adaptive search stops after structural novelty is exhausted or the engineering cap is reached. */
export function composePage(page: NarrativePage, intent: PageDesignIntent, design: DeckDesignPlan, constraints: RelationConstraint[], canvas: Canvas, tokens: DesignTokens, repairConstraints: RepairConstraint[] = []) {
  const required = [page.id, ...page.contentGroups.filter((group) => group.required).map((group) => group.id), ...intent.mediaRequests.filter((request) => request.required).flatMap((request) => [request.id, request.identityId])];
  const valid: ResolvedCandidate[] = [];
  const silhouettes = new Set<string>();
  const rejected = new Map<string, number>();
  let attemptsWithoutNovelty = 0;
  const searchCap = 32;
  const validCap = 8;
  const repairIssueCodes = repairConstraints.filter((constraint) => constraint.pageId === page.id).flatMap((constraint) => constraint.issueCodes);
  for (const candidate of generateCandidateTrees(page, intent, design, constraints, repairConstraints).slice(0, searchCap)) {
    const scored = scoreCandidate(candidate, solveTree(candidate.tree, canvas, tokens), canvas, required, repairIssueCodes);
    if (scored.hardFailures.length) {
      for (const failure of scored.hardFailures) rejected.set(failure, (rejected.get(failure) ?? 0) + 1);
      continue;
    }
    if (silhouettes.has(scored.silhouette)) attemptsWithoutNovelty += 1;
    else { silhouettes.add(scored.silhouette); attemptsWithoutNovelty = 0; valid.push(scored); }
    if (valid.length >= 2 && (valid.length >= validCap || attemptsWithoutNovelty >= 6)) break;
  }
  if (valid.length < 2) {
    const diagnostics = [...rejected.entries()].sort((left, right) => right[1] - left[1]).slice(0, 6).map(([code, count]) => `${code}(${count})`).join(",");
    throw new Error(`COMPOSITION_NO_VALID_CANDIDATE:${page.id}:${diagnostics || "NO_STRUCTURAL_NOVELTY"}`);
  }
  return valid.sort((left, right) => right.score - left.score).map((candidate, index) => ({ ...candidate, selected: index === 0 }));
}

const sourceBounds = (candidate: ResolvedCandidate, sourceId: string) => leaves(candidate.resolved).find((node) => node.sourceIds.includes(sourceId))?.bounds;
const normalizedDistance = (left: Bounds, right: Bounds, canvas: Canvas) => {
  const values = [Math.abs(left.x - right.x) / canvas.width, Math.abs(left.y - right.y) / canvas.height, Math.abs(left.width - right.width) / canvas.width, Math.abs(left.height - right.height) / canvas.height];
  return values.reduce((sum, value) => sum + value, 0) / values.length;
};

/** Evaluates linked candidates without using a predicate as a layout selector. */
const crossPagePenalty = (candidate: ResolvedCandidate, selected: Map<string, ResolvedCandidate>, pageId: string, constraints: RelationConstraint[], canvas: Canvas) => {
  let penalty = 0;
  for (const constraint of constraints.filter((item) => item.pageIds.includes(pageId))) {
    const otherPage = constraint.pageIds.find((id) => id !== pageId && selected.has(id));
    if (!otherPage) continue;
    const other = selected.get(otherPage)!;
    if (constraint.predicate.kind === "preserve") for (const sourceId of constraint.predicate.sourceIds) {
      const left = sourceBounds(candidate, sourceId); const right = sourceBounds(other, sourceId);
      if (!left || !right) penalty += 1;
      else if (constraint.predicate.properties.some((property) => property !== "identity")) penalty += normalizedDistance(left, right, canvas);
    }
  }
  return penalty;
};

/** Selects the deck as a sequence so local quality cannot destroy cross-page continuity. */
export function selectDeckCandidates(pageIds: string[], candidateSets: ResolvedCandidate[][], constraints: RelationConstraint[], canvas: Canvas, pinned: Record<string, string> = {}) {
  type Beam = { score: number; selected: Map<string, ResolvedCandidate>; silhouettes: string[] };
  let beam: Beam[] = [{ score: 0, selected: new Map(), silhouettes: [] }];
  const beamWidth = 12;
  pageIds.forEach((pageId, index) => {
    const next: Beam[] = [];
    const eligible = (candidateSets[index] ?? []).filter((candidate) => !pinned[pageId] || candidate.id === pinned[pageId]);
    for (const state of beam) for (const candidate of eligible) {
      const previous = state.silhouettes.at(-1);
      const repetitionPenalty = previous === candidate.silhouette ? 0.3 : 0;
      const linkPenalty = crossPagePenalty(candidate, state.selected, pageId, constraints, canvas);
      next.push({ score: state.score + candidate.score - repetitionPenalty - linkPenalty, selected: new Map(state.selected).set(pageId, candidate), silhouettes: [...state.silhouettes, candidate.silhouette] });
    }
    beam = next.sort((left, right) => right.score - left.score).slice(0, beamWidth);
  });
  const winner = beam[0];
  if (!winner) throw new Error("COMPOSITION_DECK_SELECTION_FAILED");
  return candidateSets.map((set, index) => set.map((candidate) => ({ ...candidate, selected: candidate.id === winner.selected.get(pageIds[index]!)?.id })));
}

export function composeDeck(outline: NarrativeOutline, intents: PageDesignIntent[], design: DeckDesignPlan, canvas: Canvas, tokens: DesignTokens, repairConstraints: RepairConstraint[] = []) {
  const constraints = new RelationConstraintCompiler().compile(outline, design);
  const sets = outline.pages.map((page) => {
    const intent = intents.find((item) => item.pageId === page.id);
    if (!intent) throw new Error(`DESIGN_PAGE_REFERENCE_INVALID:${page.id}`);
    return composePage(page, intent, design, constraints, canvas, tokens, repairConstraints);
  });
  return selectDeckCandidates(outline.pages.map((page) => page.id), sets, constraints, canvas);
}
