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
export type ResolvedCompositionNode = { id: string; kind: CompositionNode["kind"]; sourceIds: string[]; bounds: Bounds; props: Record<string, unknown>; children: ResolvedCompositionNode[] };
export type ResolvedCandidate = CompositionCandidate & { resolved: ResolvedCompositionNode };
export type RelationConstraint = { id: string; pageIds: string[]; predicate: PageRelationPredicate };
export type RepairConstraint = { id: string; pageId: string; issueCodes: string[]; forbiddenGrammarHashes: string[] };
type CandidateFeatures = CompositionCandidate["features"];

export class RelationConstraintCompiler {
  compile(outline: NarrativeOutline, design: DeckDesignPlan): RelationConstraint[] {
    const narrative = outline.arc.pageLinks.flatMap((link) => link.predicates.map((predicate, index) => ({ id: `${link.id}:${index}`, pageIds: [link.fromPageId, link.toPageId], predicate })));
    const visual = design.crossPageConstraints.flatMap((constraint: CrossPageConstraint) => constraint.predicates.map((predicate, index) => ({ id: `${constraint.id}:${index}`, pageIds: constraint.pageIds, predicate })));
    return [...narrative, ...visual];
  }
}

const primitive = (kind: CompositionNode["kind"], id: string, sourceIds: string[], props: Record<string, unknown> = {}, children?: CompositionNode[]): CompositionNode => ({ kind, id, sourceIds, props, ...(children ? { children } : {}) });
const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value));
const textUnits = (value: string) => [...value].reduce((sum, char) => sum + (/[⺀-鿿]/u.test(char) ? 1 : 0.55), 0);
const groupText = (group: ContentGroup) => group.text ?? group.items?.join("\n") ?? group.rows?.map((row) => row.join("  ")).join("\n") ?? "";
const orderedGroups = (page: NarrativePage, intent: PageDesignIntent) => {
  const priority = new Map(intent.hierarchy.map((item) => [item.contentGroupId, item.priority]));
  return [...page.contentGroups].sort((a, b) => (priority.get(a.id) ?? 5) - (priority.get(b.id) ?? 5));
};

const contentLeaf = (page: NarrativePage, group: ContentGroup, index: number) => primitive(group.kind === "chart-data" ? "Chart" : "Text", `${page.id}:content:${index}`, [group.id], { semantic: group.kind === "metric" ? "metric" : group.kind === "caption" ? "caption" : "body", text: groupText(group), required: group.required });
const mediaLeaf = (page: NarrativePage, request: PageDesignIntent["mediaRequests"][number], index: number) => primitive("Image", `${page.id}:media:${index}`, [request.id], { mediaRole: request.role, required: request.required, grow: request.role === "full-bleed-background" ? 1 : 1.3, allowsOverlap: request.role === "full-bleed-background" });
const anchored = (page: NarrativePage, suffix: string, child: CompositionNode, x: number, y: number, width: number, height: number) => primitive("Anchor", `${page.id}:anchor:${suffix}`, [], { xRatio: x, yRatio: y, widthRatio: width, heightRatio: height }, [child]);

type Topology = "editorial" | "rail" | "stage" | "mosaic" | "diagonal" | "poster";
const topologyFeatures: Array<{ topology: Topology; features: CandidateFeatures }> = [
  { topology: "editorial", features: { anchor: "text", direction: "vertical", grouping: "hierarchy", emphasis: "progressive" } },
  { topology: "rail", features: { anchor: "mixed", direction: "horizontal", grouping: "parallel", emphasis: "contrast" } },
  { topology: "stage", features: { anchor: "mixed", direction: "layered", grouping: "association", emphasis: "single-focus" } },
  { topology: "mosaic", features: { anchor: "text", direction: "radial", grouping: "collection", emphasis: "balanced" } },
  { topology: "diagonal", features: { anchor: "relation", direction: "layered", grouping: "sequence", emphasis: "progressive" } },
  { topology: "poster", features: { anchor: "text", direction: "vertical", grouping: "collection", emphasis: "single-focus" } }
];

/** Builds independent page topologies; no shared title/body wrapper is emitted. */
const buildTopology = (page: NarrativePage, intent: PageDesignIntent, design: DeckDesignPlan, topology: Topology, features: CandidateFeatures): CompositionNode => {
  const groups = orderedGroups(page, intent);
  const content = groups.map((group, index) => contentLeaf(page, group, index));
  if (page.audienceAction?.visible) content.push(primitive("Text", `${page.id}:action`, [page.id], { semantic: "callout", text: page.audienceAction.instruction, required: true }));
  const media = intent.mediaRequests.map((request, index) => mediaLeaf(page, request, index));
  const backgrounds = media.filter((node) => node.props.mediaRole === "full-bleed-background");
  const foreground = media.filter((node) => node.props.mediaRole !== "full-bleed-background");
  const units = [...content, ...foreground];
  const title = primitive("Text", `${page.id}:title`, [page.id], { semantic: "title", text: page.headline, required: true });
  const nodes: CompositionNode[] = [...backgrounds];
  const count = Math.max(1, units.length);
  if (topology === "editorial") {
    nodes.push(anchored(page, "title", title, 0.07, 0.08, 0.72, 0.18));
    units.forEach((unit, index) => nodes.push(anchored(page, `unit:${index}`, unit, 0.08 + index % 2 * 0.45, 0.34 + Math.floor(index / 2) * (0.53 / Math.ceil(count / 2)), 0.39, 0.42 / Math.ceil(count / 2))));
  } else if (topology === "rail") {
    nodes.push(anchored(page, "title", title, 0.06, 0.12, 0.30, 0.70));
    units.forEach((unit, index) => nodes.push(anchored(page, `unit:${index}`, unit, 0.42, 0.10 + index * (0.80 / count), 0.50, 0.68 / count)));
  } else if (topology === "stage") {
    nodes.push(anchored(page, "title", title, 0.13, 0.09, 0.74, 0.20));
    if (units[0]) nodes.push(anchored(page, "hero", units[0], 0.18, 0.34, 0.64, 0.36));
    units.slice(1).forEach((unit, index) => nodes.push(anchored(page, `support:${index}`, unit, 0.10 + index * (0.82 / Math.max(1, count - 1)), 0.76, 0.72 / Math.max(1, count - 1), 0.14)));
  } else if (topology === "mosaic") {
    nodes.push(anchored(page, "title", title, 0.32, 0.08, 0.60, 0.18));
    const columns = count > 4 ? 3 : 2; const rows = Math.ceil(count / columns);
    units.forEach((unit, index) => nodes.push(anchored(page, `tile:${index}`, unit, 0.07 + index % columns * (0.86 / columns), 0.32 + Math.floor(index / columns) * (0.58 / rows), 0.76 / columns, 0.48 / rows)));
  } else if (topology === "diagonal") {
    nodes.push(anchored(page, "title", title, 0.08, 0.08, 0.58, 0.18));
    units.forEach((unit, index) => { const w = count === 1 ? 0.70 : 0.42; const h = clamp(0.56 / count + 0.08, 0.15, 0.30); nodes.push(anchored(page, `step:${index}`, unit, 0.12 + index * (0.70 / count), 0.34 + index * (0.42 / count), w, h)); });
  } else {
    nodes.push(anchored(page, "title", title, 0.12, 0.16, 0.76, 0.25));
    units.forEach((unit, index) => nodes.push(anchored(page, `caption:${index}`, unit, 0.16 + index % 2 * 0.38, 0.52 + Math.floor(index / 2) * (0.34 / Math.ceil(count / 2)), 0.30, 0.25 / Math.ceil(count / 2))));
  }
  const motifCount = Math.min(2, design.visualGrammar.motifRules.length || 1);
  for (let index = 0; index < motifCount; index += 1) nodes.push(anchored(page, `motif:${index}`, primitive("Shape", `${page.id}:motif:${index}`, [], { decorative: true, treatment: index ? "accent" : "motif", allowsOverlap: true }), index ? 0.88 : 0.01, index ? 0.02 : 0.86, 0.10, 0.12));
  return primitive("Canvas", `${page.id}:canvas:${topology}`, [page.id], { topology }, [primitive("Overlay", `${page.id}:overlay:${topology}`, [], {}, nodes)]);
};

export function generateCandidateTrees(page: NarrativePage, intent: PageDesignIntent, design: DeckDesignPlan, constraints: RelationConstraint[], repairConstraints: RepairConstraint[] = []): CompositionCandidate[] {
  const forbidden = new Set(repairConstraints.filter((item) => item.pageId === page.id).flatMap((item) => item.forbiddenGrammarHashes));
  return topologyFeatures.map(({ topology, features }) => {
    const tree = buildTopology(page, intent, design, topology, features); const grammarHash = hashContent(tree);
    return { id: `cand-${hashContent({ page: page.id, topology }).slice(0, 16)}`, pageId: page.id, features, grammarHash, tree, trace: { inputMetrics: { contentCount: page.contentGroups.length, mediaCount: intent.mediaRequests.length, textUnits: textUnits(page.headline + page.contentGroups.map(groupText).join("")) }, constraintIds: constraints.filter((item) => item.pageIds.includes(page.id)).map((item) => item.id), differences: [`topology:${topology}`, ...Object.entries(features).map(([key, value]) => `${key}:${value}`)], rejectedReasons: forbidden.has(grammarHash) ? ["forbidden-by-repair"] : [] }, score: 0, hardFailures: forbidden.has(grammarHash) ? ["FORBIDDEN_GRAMMAR"] : [], scoreBreakdown: {}, silhouette: topology, selected: false };
  });
}

const insetAnchor = (bounds: Bounds, props: Record<string, unknown>): Bounds => ({ x: bounds.x + bounds.width * Number(props.xRatio ?? 0), y: bounds.y + bounds.height * Number(props.yRatio ?? 0), width: Math.max(1, bounds.width * Number(props.widthRatio ?? 1)), height: Math.max(1, bounds.height * Number(props.heightRatio ?? 1)) });
const fitFont = (text: string, bounds: Bounds, preferred: number, minimum: number, singleLine: boolean) => { for (let size = preferred; size >= minimum; size -= 1) { const lines = Math.max(1, Math.ceil(textUnits(text) / Math.max(1, bounds.width / size))); if (lines * size * 1.2 <= bounds.height && (!singleLine || lines === 1)) return { size, lines, fits: true }; } return { size: minimum, lines: Math.ceil(textUnits(text) / Math.max(1, bounds.width / minimum)), fits: false }; };

export function solveTree(tree: CompositionNode, canvas: Canvas, tokens: DesignTokens): ResolvedCompositionNode {
  const resolve = (node: CompositionNode, bounds: Bounds): ResolvedCompositionNode => {
    const children = node.children ?? []; let childBounds = children.map(() => bounds);
    if (node.kind === "Anchor") childBounds = children.map(() => insetAnchor(bounds, node.props));
    const props = { ...node.props };
    if (node.kind === "Text") { const semantic = String(props.semantic ?? "body"); const preferred = semantic === "title" ? tokens.titlePt : semantic === "metric" ? tokens.deckTitlePt : tokens.bodyPt; const result = fitFont(String(props.text ?? ""), bounds, preferred, semantic === "title" ? 26 : 16, semantic === "title"); props.fontSize = result.size; props.estimatedLines = result.lines; props.textFits = result.fits; }
    return { id: node.id, kind: node.kind, sourceIds: node.sourceIds, bounds, props, children: children.map((child, index) => resolve(child, childBounds[index]!)) };
  };
  return resolve(tree, { x: 0, y: 0, width: canvas.width, height: canvas.height });
}

const leaves = (node: ResolvedCompositionNode): ResolvedCompositionNode[] => node.children.length ? node.children.flatMap(leaves) : [node];
const intersects = (a: Bounds, b: Bounds) => a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;

export function scoreCandidate(candidate: CompositionCandidate, resolved: ResolvedCompositionNode, canvas: Canvas, requiredSourceIds: string[], repairIssueCodes: string[] = []): ResolvedCandidate {
  const items = leaves(resolved); const failures = [...candidate.hardFailures]; const sources = new Set(items.flatMap((item) => item.sourceIds));
  if (requiredSourceIds.some((id) => !sources.has(id))) failures.push("REQUIRED_SOURCE_MISSING");
  if (items.some((item) => item.kind === "Text" && item.props.textFits === false)) failures.push("TEXT_OVERFLOW");
  const visible = items.filter((item) => !item.props.decorative && !item.props.allowsOverlap && item.props.mediaRole !== "full-bleed-background");
  if (visible.some((item, index) => visible.slice(index + 1).some((other) => intersects(item.bounds, other.bounds)))) failures.push("NODE_OVERLAP");
  const topology = String(candidate.tree.props.topology ?? candidate.silhouette); const seedBias = parseInt(hashContent({ page: candidate.pageId, topology }).slice(0, 6), 16) / 0xffffff;
  const preferredFlow = candidate.features.direction === "horizontal" || candidate.features.direction === "vertical" ? 0.25 : 0.1;
  const repairBonus = repairIssueCodes.includes("REPETITIVE_COMPOSITION") ? seedBias * 0.4 : 0;
  const scoreBreakdown = { valid: failures.length ? -10 : 4, contentDrivenVariation: seedBias, preferredFlow, repairBonus };
  return { ...candidate, resolved, hardFailures: [...new Set(failures)], scoreBreakdown, silhouette: topology, score: Object.values(scoreBreakdown).reduce((sum, value) => sum + value, 0) };
}

export function composePage(page: NarrativePage, intent: PageDesignIntent, design: DeckDesignPlan, constraints: RelationConstraint[], canvas: Canvas, tokens: DesignTokens, repairConstraints: RepairConstraint[] = []) {
  const required = [page.id, ...page.contentGroups.filter((group) => group.required).map((group) => group.id), ...intent.mediaRequests.filter((request) => request.required).map((request) => request.id)];
  const issueCodes = repairConstraints.filter((item) => item.pageId === page.id).flatMap((item) => item.issueCodes);
  const scored = generateCandidateTrees(page, intent, design, constraints, repairConstraints).map((candidate) => scoreCandidate(candidate, solveTree(candidate.tree, canvas, tokens), canvas, required, issueCodes));
  const legal = scored.filter((candidate) => candidate.hardFailures.length === 0).sort((a, b) => b.score - a.score);
  const pool = legal.length >= 2 ? legal : scored.sort((a, b) => a.hardFailures.length - b.hardFailures.length || b.score - a.score);
  return pool.slice(0, 6).map((candidate, index) => ({ ...candidate, selected: index === 0 }));
}

export function selectDeckCandidates(pageIds: string[], candidateSets: ResolvedCandidate[][], _constraints: RelationConstraint[], _canvas: Canvas, pinned: Record<string, string> = {}) {
  let previous = "";
  return candidateSets.map((set, index) => {
    const pageId = pageIds[index]!; const pinnedCandidate = pinned[pageId] ? set.find((item) => item.id === pinned[pageId]) : undefined;
    const ranked = [...set].sort((a, b) => (a.silhouette === previous ? 1 : 0) - (b.silhouette === previous ? 1 : 0) || b.score - a.score);
    const chosen = pinnedCandidate ?? ranked[0] ?? set[0]; previous = chosen?.silhouette ?? "";
    return set.map((candidate) => ({ ...candidate, selected: candidate.id === chosen?.id }));
  });
}

export function composeDeck(outline: NarrativeOutline, intents: PageDesignIntent[], design: DeckDesignPlan, canvas: Canvas, tokens: DesignTokens, repairConstraints: RepairConstraint[] = []) {
  const constraints = new RelationConstraintCompiler().compile(outline, design);
  const sets = outline.pages.map((page) => { const intent = intents.find((item) => item.pageId === page.id); if (!intent) throw new Error(`Missing design intent for ${page.id}`); return composePage(page, intent, design, constraints, canvas, tokens, repairConstraints); });
  return selectDeckCandidates(outline.pages.map((page) => page.id), sets, constraints, canvas);
}
