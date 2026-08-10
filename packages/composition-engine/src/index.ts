import {
  hashContent,
  type Bounds,
  type CompositionCandidate,
  type CompositionNode,
  type ContentGroup,
  type NarrativePage,
  type PageDesignIntent
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

const primitive = (
  kind: CompositionNode["kind"],
  id: string,
  sourceIds: string[],
  props: Record<string, unknown> = {},
  children?: CompositionNode[]
): CompositionNode => ({ kind, id, sourceIds, props, ...(children ? { children } : {}) });

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

const contentLeaf = (page: NarrativePage, group: ContentGroup, index: number) => primitive(
  group.kind === "chart-data" ? "Chart" : "Text",
  `${page.id}-content-${index}`,
  [group.id],
  {
    contentGroupId: group.id,
    contentKind: group.kind,
    text: groupText(group),
    required: group.required,
    grow: group.kind === "caption" || group.kind === "annotation" ? 0.7 : 1,
    semantic: group.kind === "metric" ? "metric" : group.kind === "caption" ? "caption" : "body"
  }
);

const mediaLeaf = (page: NarrativePage, request: PageDesignIntent["mediaRequests"][number], index: number) => primitive(
  "Image",
  `${page.id}-media-${index}`,
  [request.id],
  {
    requestId: request.id,
    mediaRole: request.role,
    fit: request.fit,
    required: request.required,
    grow: request.role === "background" ? 1 : 1.35,
    allowsOverlap: request.role === "background"
  }
);

const titleLeaf = (page: NarrativePage) => primitive("Text", `${page.id}-title`, [page.id], {
  semantic: "title",
  text: page.headline,
  required: true,
  grow: 0.22
});

const decoration = (page: NarrativePage, suffix: string, treatment: "accent" | "surface" | "scrim") => primitive(
  "Shape",
  `${page.id}-shape-${suffix}`,
  [],
  { decorative: true, treatment, allowsOverlap: true }
);

const safe = (page: NarrativePage, suffix: string, children: CompositionNode[]) => primitive(
  "SafeArea", `${page.id}-safe-${suffix}`, [], {}, children
);
const stack = (page: NarrativePage, suffix: string, children: CompositionNode[], direction: "vertical" | "horizontal" = "vertical") => primitive(
  "Stack", `${page.id}-stack-${suffix}`, [], { direction }, children
);

export function generateCandidateTrees(page: NarrativePage, intent: PageDesignIntent): CompositionCandidate[] {
  const ordered = hierarchyOrder(page, intent);
  const content = ordered.map((group, index) => contentLeaf(page, group, index));
  const media = intent.mediaRequests.map((request, index) => mediaLeaf(page, request, index));
  const title = titleLeaf(page);
  const leadingVisual = intent.flow === "horizontal" || intent.balance === "directional";
  const editorialColumns = media.length
    ? leadingVisual
      ? [primitive("Frame", `${page.id}-editorial-visual`, [], { grow: 1.05 }, media), stack(page, "editorial-copy", content)]
      : [stack(page, "editorial-copy", content), primitive("Frame", `${page.id}-editorial-visual`, [], { grow: 1.05 }, media)]
    : [primitive("Flow", `${page.id}-editorial-copy`, [], { direction: intent.flow === "horizontal" ? "horizontal" : "vertical" }, content)];

  const background = media.find((item) => item.props.mediaRole === "background");
  const foregroundMedia = media.filter((item) => item !== background);
  const stageBackdrop = background ?? decoration(page, "stage-backdrop", "accent");
  const stageCopy = primitive("Anchor", `${page.id}-stage-copy`, [], {
    horizontal: foregroundMedia.length ? (intent.balance === "directional" ? "end" : "start") : "center",
    vertical: "center",
    widthRatio: foregroundMedia.length ? (intent.density === "high" ? 0.58 : 0.48) : 0.78,
    heightRatio: foregroundMedia.length ? 0.78 : 0.68
  }, [primitive("Overlay", `${page.id}-stage-panel`, [], {}, [
    decoration(page, "stage-scrim", "scrim"),
    primitive("Frame", `${page.id}-stage-frame`, [], { padding: 20 }, [stack(page, "stage-stack", [title, ...content])])
  ])]);
  const stageExtras = foregroundMedia.length ? [primitive("Anchor", `${page.id}-stage-media`, [], {
    horizontal: intent.balance === "directional" ? "start" : "end",
    vertical: "end",
    widthRatio: 0.42,
    heightRatio: 0.72
  }, foregroundMedia)] : [];

  const sequenceDirection = intent.flow === "vertical" || intent.flow === "sequence"
    ? (intent.flow === "vertical" ? "vertical" : "horizontal")
    : (intent.flow === "horizontal" ? "horizontal" : "vertical");
  const sequenceItems = [...content, ...media];
  const mosaicItems = [...content, ...media];
  const accentRule = (suffix: string) => primitive("Shape", `${page.id}-shape-${suffix}`, [], { decorative: true, treatment: "accent", grow: 0.018 });

  const definitions: Array<[CompositionCandidate["strategy"], CompositionNode]> = [
    ["editorial", primitive("Canvas", `${page.id}-canvas-editorial`, [page.id], {}, [safe(page, "editorial", [
      stack(page, "editorial-root", [title, accentRule("editorial-rule"), primitive("Grid", `${page.id}-editorial-grid`, [], {
        columns: editorialColumns.length,
        columnWeights: intent.balance === "asymmetric" ? [1.12, 0.88] : [1, 1],
        grow: 1
      }, editorialColumns)])
    ])])],
    ["stage", primitive("Canvas", `${page.id}-canvas-stage`, [page.id], {}, [primitive("Overlay", `${page.id}-stage-overlay`, [], {}, [
      stageBackdrop,
      ...stageExtras,
      stageCopy
    ])])],
    ["sequence", primitive("Canvas", `${page.id}-canvas-sequence`, [page.id], {}, [safe(page, "sequence", [
      stack(page, "sequence-root", [title, accentRule("sequence-rule"), primitive("Flow", `${page.id}-sequence-flow`, [], {
        direction: sequenceDirection,
        grow: 1
      }, sequenceItems)])
    ])])],
    ["mosaic", primitive("Canvas", `${page.id}-canvas-mosaic`, [page.id], {}, [safe(page, "mosaic", [
      stack(page, "mosaic-root", [title, accentRule("mosaic-rule"), primitive("Grid", `${page.id}-mosaic-grid`, [], {
        columns: mosaicItems.length <= 2 ? 2 : mosaicItems.length <= 6 ? 3 : 4,
        grow: 1
      }, mosaicItems)])
    ])])]
  ];

  return definitions.map(([strategy, tree]) => ({
    id: `cand-${hashContent({ pageId: page.id, strategy, intent }).slice(0, 12)}`,
    pageId: page.id,
    strategy,
    tree,
    score: 0,
    hardFailures: [],
    scoreBreakdown: {},
    silhouette: strategy,
    selected: false
  }));
}

const inset = (bounds: Bounds, padding: number): Bounds => ({
  x: bounds.x + padding,
  y: bounds.y + padding,
  width: Math.max(1, bounds.width - padding * 2),
  height: Math.max(1, bounds.height - padding * 2)
});

const splitWeighted = (
  bounds: Bounds,
  children: CompositionNode[],
  direction: "vertical" | "horizontal",
  gap: number
): Bounds[] => {
  const available = (direction === "vertical" ? bounds.height : bounds.width) - gap * Math.max(0, children.length - 1);
  const weights = children.map((child) => Math.max(0.05, Number(child.props.grow ?? 1)));
  const total = weights.reduce((sum, value) => sum + value, 0) || 1;
  let cursor = direction === "vertical" ? bounds.y : bounds.x;
  return children.map((_, index) => {
    const size = available * weights[index]! / total;
    const result = direction === "vertical"
      ? { x: bounds.x, y: cursor, width: bounds.width, height: size }
      : { x: cursor, y: bounds.y, width: size, height: bounds.height };
    cursor += size + gap;
    return result;
  });
};

const textUnits = (value: string) => [...value].reduce((sum, character) => sum + (/[⺀-鿿]/u.test(character) ? 1 : 0.55), 0);
const fitFont = (text: string, bounds: Bounds, preferred: number, minimum: number, singleLine: boolean) => {
  for (let size = preferred; size >= minimum; size -= 1) {
    const perLine = Math.max(1, bounds.width / size);
    const lines = Math.max(1, Math.ceil(textUnits(text) / perLine));
    const required = lines * size * 1.22;
    if (required <= bounds.height && (!singleLine || lines === 1)) return { size, lines, fits: true };
  }
  const perLine = Math.max(1, bounds.width / minimum);
  return { size: minimum, lines: Math.max(1, Math.ceil(textUnits(text) / perLine)), fits: false };
};

export function solveTree(tree: CompositionNode, canvas: Canvas, tokens: DesignTokens): ResolvedCompositionNode {
  const resolve = (current: CompositionNode, bounds: Bounds): ResolvedCompositionNode => {
    const children = current.children ?? [];
    let childBounds: Bounds[] = [];
    if (current.kind === "Canvas") childBounds = children.map(() => ({ x: 0, y: 0, width: canvas.width, height: canvas.height }));
    else if (current.kind === "SafeArea") childBounds = children.map(() => inset(bounds, Math.max(tokens.safeInset, Math.min(canvas.width, canvas.height) * 0.055)));
    else if (current.kind === "Stack" || current.kind === "Flow") {
      childBounds = splitWeighted(bounds, children, (current.props.direction as "vertical" | "horizontal") ?? "vertical", tokens.space);
    } else if (current.kind === "Grid") {
      const columns = Math.max(1, Math.min(children.length || 1, Number(current.props.columns ?? 1)));
      const rows = Math.max(1, Math.ceil(children.length / columns));
      const rawWeights = Array.isArray(current.props.columnWeights) ? current.props.columnWeights.map(Number) : Array.from({ length: columns }, () => 1);
      const columnWeights = Array.from({ length: columns }, (_, index) => Math.max(0.1, rawWeights[index] ?? 1));
      const totalWeight = columnWeights.reduce((sum, value) => sum + value, 0);
      const availableWidth = bounds.width - tokens.space * (columns - 1);
      const rowHeight = (bounds.height - tokens.space * (rows - 1)) / rows;
      const offsets: number[] = [];
      let offset = 0;
      for (let index = 0; index < columns; index += 1) {
        offsets.push(offset);
        offset += availableWidth * columnWeights[index]! / totalWeight + tokens.space;
      }
      childBounds = children.map((_, index) => {
        const column = index % columns;
        const row = Math.floor(index / columns);
        return {
          x: bounds.x + offsets[column]!,
          y: bounds.y + row * (rowHeight + tokens.space),
          width: availableWidth * columnWeights[column]! / totalWeight,
          height: rowHeight
        };
      });
    } else if (current.kind === "Overlay") childBounds = children.map(() => bounds);
    else if (current.kind === "Anchor") {
      const width = bounds.width * Number(current.props.widthRatio ?? 0.5);
      const height = bounds.height * Number(current.props.heightRatio ?? 0.5);
      const x = current.props.horizontal === "end" ? bounds.x + bounds.width - width : current.props.horizontal === "center" ? bounds.x + (bounds.width - width) / 2 : bounds.x;
      const y = current.props.vertical === "end" ? bounds.y + bounds.height - height : current.props.vertical === "center" ? bounds.y + (bounds.height - height) / 2 : bounds.y;
      childBounds = children.map(() => ({ x, y, width, height }));
    } else if (current.kind === "Frame") {
      const padding = Number(current.props.padding ?? tokens.space * 0.7);
      childBounds = children.length === 1 ? [inset(bounds, padding)] : splitWeighted(inset(bounds, padding), children, "vertical", tokens.space);
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
    return {
      id: current.id,
      kind: current.kind,
      sourceIds: current.sourceIds,
      bounds,
      props,
      children: children.map((child, index) => resolve(child, childBounds[index] ?? bounds))
    };
  };
  return resolve(tree, { x: 0, y: 0, width: canvas.width, height: canvas.height });
}

const leaves = (node: ResolvedCompositionNode): ResolvedCompositionNode[] => node.children.length ? node.children.flatMap(leaves) : [node];
const intersects = (left: Bounds, right: Bounds) => left.x < right.x + right.width && left.x + left.width > right.x && left.y < right.y + right.height && left.y + left.height > right.y;
const silhouetteOf = (items: ResolvedCompositionNode[], canvas: Canvas) => items
  .filter((item) => !item.props.decorative && item.props.mediaRole !== "background")
  .map((item) => `${item.kind}:${Math.round(item.bounds.x / canvas.width * 4)}:${Math.round(item.bounds.y / canvas.height * 4)}:${Math.round(item.bounds.width / canvas.width * 4)}:${Math.round(item.bounds.height / canvas.height * 4)}`)
  .sort()
  .join("|");

export function scoreCandidate(
  candidate: CompositionCandidate,
  resolved: ResolvedCompositionNode,
  canvas: Canvas,
  requiredSourceIds: string[],
  intent?: PageDesignIntent
): ResolvedCandidate {
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
  for (let leftIndex = 0; leftIndex < items.length; leftIndex += 1) {
    for (let rightIndex = leftIndex + 1; rightIndex < items.length; rightIndex += 1) {
      const left = items[leftIndex]!;
      const right = items[rightIndex]!;
      if (!intersects(left.bounds, right.bounds)) continue;
      if (left.props.allowsOverlap || right.props.allowsOverlap || left.props.decorative || right.props.decorative) continue;
      failures.push(`UNINTENDED_OVERLAP:${left.id}:${right.id}`);
    }
  }
  const foreground = items.filter((item) => !item.props.decorative && item.props.mediaRole !== "background");
  const occupied = foreground.reduce((sum, item) => sum + item.bounds.width * item.bounds.height, 0) / (canvas.width * canvas.height);
  const centers = foreground.map((item) => (item.bounds.x + item.bounds.width / 2) / canvas.width);
  const center = centers.reduce((sum, value) => sum + value, 0) / Math.max(1, centers.length);
  const hierarchy = foreground.some((item) => item.props.semantic === "title") ? 1 : 0;
  const whitespace = 1 - Math.min(1, Math.abs(0.58 - occupied));
  const balance = Math.max(0, 1 - Math.abs(0.5 - center));
  const density = Math.max(0, 1 - Math.abs(0.5 - occupied));
  const contentCoverage = requiredSourceIds.length ? (requiredSourceIds.filter((id) => sourceIds.has(id)).length / requiredSourceIds.length) : 1;
  const communicationFit = !intent ? 0.75
    : candidate.strategy === "stage" ? (intent.balance === "centered" && ["none", "background", "subject"].includes(intent.visualStrategy) && intent.density === "low" ? 1.5 : 0.45)
    : candidate.strategy === "editorial" ? (intent.balance === "asymmetric" || intent.balance === "directional" || intent.flow === "horizontal" || intent.visualStrategy === "evidence" ? 1 : 0.65)
    : candidate.strategy === "sequence" ? (intent.flow === "sequence" || intent.flow === "vertical" || intent.visualStrategy === "diagram" ? 1 : 0.62)
    : (intent.visualStrategy === "gallery" || intent.density === "high" ? 1 : 0.55);
  const scoreBreakdown = { hierarchy, whitespace, balance, density, contentCoverage, communicationFit };
  const score = Object.values(scoreBreakdown).reduce((sum, value) => sum + value, 0) / Object.keys(scoreBreakdown).length - failures.length * 10;
  return {
    ...candidate,
    resolved,
    hardFailures: [...new Set(failures)],
    scoreBreakdown,
    silhouette: silhouetteOf(items, canvas),
    score
  };
}

export function composePage(page: NarrativePage, intent: PageDesignIntent, canvas: Canvas, tokens: DesignTokens) {
  const required = [page.id, ...page.contentGroups.filter((group) => group.required).map((group) => group.id), ...intent.mediaRequests.filter((request) => request.required).map((request) => request.id)];
  const candidates = generateCandidateTrees(page, intent)
    .map((candidate) => scoreCandidate(candidate, solveTree(candidate.tree, canvas, tokens), canvas, required, intent))
    .filter((candidate) => candidate.hardFailures.length === 0)
    .sort((left, right) => right.score - left.score);
  if (candidates.length < 2) throw new Error(`Fewer than two valid compositions for ${page.id}`);
  return candidates.map((candidate, index) => ({ ...candidate, selected: index === 0 }));
}

export function selectDeckCandidates(candidateSets: ResolvedCandidate[][]) {
  let previousSilhouette = "";
  let previousStrategy = "";
  return candidateSets.map((set) => {
    const ranked = [...set].sort((left, right) => {
      const leftPenalty = (left.silhouette === previousSilhouette ? 0.3 : 0) + (left.strategy === previousStrategy ? 0.12 : 0);
      const rightPenalty = (right.silhouette === previousSilhouette ? 0.3 : 0) + (right.strategy === previousStrategy ? 0.12 : 0);
      return (right.score - rightPenalty) - (left.score - leftPenalty);
    });
    const selected = ranked[0]!;
    previousSilhouette = selected.silhouette;
    previousStrategy = selected.strategy;
    return set.map((candidate) => ({ ...candidate, selected: candidate.id === selected.id }));
  });
}

export function composeDeck(
  pages: NarrativePage[],
  intents: PageDesignIntent[],
  canvas: Canvas,
  tokens: DesignTokens
) {
  const sets = pages.map((page) => {
    const intent = intents.find((item) => item.pageId === page.id);
    if (!intent) throw new Error(`Missing design intent for ${page.id}`);
    return composePage(page, intent, canvas, tokens);
  });
  return selectDeckCandidates(sets);
}
