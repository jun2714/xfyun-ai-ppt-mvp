import {
  SceneGraphSchema,
  hashContent,
  versioned,
  type AssetBundlePlan,
  type ContentGroup,
  type NarrativeOutline,
  type PageDesignIntent,
  type SceneGraph,
  type SceneNode
} from "@sparkdeck/presentation-model";
import type { DesignTokens } from "@sparkdeck/design-language";
import type { ResolvedCandidate, ResolvedCompositionNode } from "@sparkdeck/composition-engine";

const leaves = (node: ResolvedCompositionNode): ResolvedCompositionNode[] => node.children.length ? node.children.flatMap(leaves) : [node];
const groupText = (group: ContentGroup) => {
  const prefix = group.label ? `${group.label}\n` : "";
  if (group.text) return `${prefix}${group.text}`;
  if (group.items?.length) return `${prefix}${group.items.map((item) => `• ${item}`).join("\n")}`;
  return `${prefix}${group.rows?.map((row) => row.join("  ·  ")).join("\n") ?? ""}`;
};

const shapeStyle = (treatment: string, tokens: DesignTokens) => {
  if (treatment === "accent") return { fill: tokens.primary, opacity: 1, stroke: tokens.primary, radius: tokens.radius };
  if (treatment === "scrim") return { fill: tokens.surface, opacity: 0.9, stroke: tokens.surface, radius: tokens.radius };
  if (treatment === "motif") return { fill: tokens.accent, opacity: 0.88, stroke: tokens.accent, radius: tokens.radius };
  return { fill: tokens.surface, opacity: 1, stroke: tokens.muted, radius: tokens.radius };
};

export function compileSceneGraph(input: {
  presentationId: string;
  outline: NarrativeOutline;
  intents: PageDesignIntent[];
  candidateSets: ResolvedCandidate[][];
  tokens: DesignTokens;
  canvas: { width: number; height: number };
  revision?: number | undefined;
  assetPlan?: AssetBundlePlan | undefined;
  assets?: Record<string, { url?: string | undefined; dataUri?: string | undefined; alt: string }> | undefined;
}): SceneGraph {
  const pages = input.outline.pages.map((page, pageIndex) => {
    const set = input.candidateSets[pageIndex] ?? [];
    const selected = set.find((candidate) => candidate.selected) ?? set[0];
    if (!selected) throw new Error(`Missing composition for ${page.id}`);
    const groups = new Map(page.contentGroups.map((group) => [group.id, group]));
    const intent = input.intents.find((item) => item.pageId === page.id);
    if (!intent) throw new Error(`Missing design intent for ${page.id}`);
    const nodes: SceneNode[] = leaves(selected.resolved)
      .filter((leaf) => ["Text", "Shape", "Image", "Chart", "Connector"].includes(leaf.kind))
      .map((leaf, zIndex) => {
        const group = leaf.sourceIds.map((id) => groups.get(id)).find((item) => item !== undefined);
        const placement = input.assetPlan?.placements.find((item) => item.boundsRef === leaf.id || leaf.sourceIds.includes(item.requestId));
        const request = intent.mediaRequests.find((item) => leaf.sourceIds.includes(item.id));
        const asset = placement?.assetId ? input.assets?.[placement.assetId] : undefined;
        const semantic = String(leaf.props.semantic ?? "body");
        const kind = leaf.kind.toLowerCase() as SceneNode["kind"];
        const content: Record<string, unknown> = kind === "text"
          ? {
              text: semantic === "title" ? page.headline : group ? groupText(group) : String(leaf.props.text ?? page.message),
              semantic,
              contentKind: group?.kind ?? "headline",
              paragraphs: group?.items ?? []
            }
          : kind === "image"
            ? {
                placementId: placement?.id,
                assetId: placement?.assetId,
                url: asset?.url,
                dataUri: asset?.dataUri,
                // Private generation descriptions must never become audience-visible fallback copy.
                alt: asset?.alt ?? request?.audienceAlt ?? "",
                fit: placement?.fit ?? request?.fit ?? "cover",
                focalPolicy: placement?.focalPolicy ?? request?.focalPolicy ?? "auto",
                mediaRole: placement?.role ?? request?.role ?? "subject"
              }
            : kind === "chart"
              ? { rows: group?.rows ?? [], label: group?.label ?? "" }
              : kind === "connector"
                ? { flipH: leaf.props.flipH === true, flipV: leaf.props.flipV === true, relationKind: leaf.props.relationKind }
              : {};
        const style: Record<string, unknown> = kind === "text"
          ? {
              fontFamily: semantic === "title" || semantic === "metric" ? input.tokens.headingFontFamily : input.tokens.bodyFontFamily,
              fontSize: Number(leaf.props.fontSize ?? (semantic === "title" ? input.tokens.titlePt : input.tokens.bodyPt)),
              fontWeight: semantic === "title" || semantic === "metric" ? input.tokens.headingWeight : input.tokens.bodyWeight,
              color: input.tokens.text,
              lineHeight: input.tokens.lineHeight,
              verticalAlign: "middle",
              align: intent.balance === "centered" ? "center" : "left"
            }
          : kind === "shape"
            ? { ...shapeStyle(String(leaf.props.treatment ?? "surface"), input.tokens), decorative: leaf.props.decorative === true, allowsOverlap: leaf.props.allowsOverlap === true }
            : kind === "image"
              ? { radius: request?.role === "full-bleed-background" ? 0 : input.tokens.radius }
              : { fill: input.tokens.primary, stroke: input.tokens.secondary, color: input.tokens.text };
        const contentHash = hashContent({ content, style, bounds: leaf.bounds });
        return { id: leaf.id, kind, sourceIds: leaf.sourceIds, bounds: leaf.bounds, zIndex, style, content, locked: false, contentHash };
      });
    const riskFlags: Array<"opening" | "closing" | "full-bleed" | "comparison" | "reveal" | "low-confidence"> = [];
    if (pageIndex === 0) riskFlags.push("opening");
    if (pageIndex === input.outline.pages.length - 1) riskFlags.push("closing");
    if (intent.visualStrategy === "full-bleed-background" || nodes.some((node) => node.kind === "image" && node.content.mediaRole === "full-bleed-background")) riskFlags.push("full-bleed");
    if (page.contentGroups.some((group) => group.kind === "comparison")) riskFlags.push("comparison");
    const pageLinks = input.outline.arc.pageLinks.filter((link) => link.fromPageId === page.id || link.toPageId === page.id);
    if (pageLinks.some((link) => link.predicates.some((predicate) => predicate.kind === "conceal" || predicate.kind === "introduce"))) riskFlags.push("reveal");
    return {
      id: page.id,
      width: input.canvas.width,
      height: input.canvas.height,
      background: input.tokens.background,
      speakerNotes: page.speakerNotes,
      nodes,
      requiredSourceIds: [page.id, ...page.contentGroups.filter((group) => group.required).map((group) => group.id), ...intent.mediaRequests.filter((request) => request.required).map((request) => request.id)],
      selectedCandidateId: selected.id,
      alternativeCandidateIds: set.filter((candidate) => candidate.id !== selected.id).map((candidate) => candidate.id),
      pageLinkIds: pageLinks.map((link) => link.id),
      riskFlags
    };
  });
  return SceneGraphSchema.parse(versioned({
    presentationId: input.presentationId,
    canvas: { ...input.canvas, unit: "pt" as const },
    theme: input.tokens,
    pages
  }, input.revision ?? 0, { outline: input.outline.contentHash, ...(input.assetPlan ? { assets: input.assetPlan.contentHash } : {}) }));
}

export function sceneSemanticFingerprint(scene: SceneGraph) {
  return hashContent({
    canvas: scene.canvas,
    theme: scene.theme,
    pages: scene.pages.map((page) => ({
      id: page.id,
      selectedCandidateId: page.selectedCandidateId,
      nodes: page.nodes.map((node) => ({ id: node.id, kind: node.kind, sourceIds: node.sourceIds, bounds: node.bounds, contentHash: node.contentHash }))
    }))
  });
}

export type SceneCommand = {
  type: "set-text" | "set-style" | "set-bounds" | "set-z" | "set-rotation" | "set-asset" | "set-crop" | "set-locked" | "duplicate-node" | "add-text" | "add-shape" | "add-image" | "delete-node" | "add-page" | "duplicate-page" | "delete-page" | "reorder-page" | "align-nodes" | "distribute-nodes" | "set-theme";
  pageId: string;
  nodeId: string;
  value?: unknown;
  expectedRevision: number;
};

export function applySceneCommand(scene: SceneGraph, command: SceneCommand): SceneGraph {
  if (scene.revision !== command.expectedRevision) throw new Error("REVISION_CONFLICT");
  if (command.type === "set-theme") {
    const update = command.value as Record<string, unknown>;
    const allowed = new Set(["background", "text", "primary", "secondary", "accent", "headingFontFamily", "bodyFontFamily"]);
    if (Object.keys(update).some((key) => !allowed.has(key))) throw new Error("THEME_PROPERTY_INVALID");
    const theme = { ...scene.theme, ...update };
    const pages = scene.pages.map((page) => ({
      ...page,
      background: page.background === scene.theme.background && typeof update.background === "string" ? update.background : page.background,
      nodes: page.nodes.map((node) => {
        const style = { ...node.style };
        if (style.color === scene.theme.text && update.text) style.color = update.text;
        if (style.fill === scene.theme.primary && update.primary) style.fill = update.primary;
        if (style.stroke === scene.theme.primary && update.primary) style.stroke = update.primary;
        if (node.kind === "text" && node.content.semantic === "title" && update.headingFontFamily) style.fontFamily = update.headingFontFamily;
        if (node.kind === "text" && node.content.semantic !== "title" && update.bodyFontFamily) style.fontFamily = update.bodyFontFamily;
        return { ...node, style, contentHash: hashContent({ content: node.content, style, bounds: node.bounds }) };
      })
    }));
    return SceneGraphSchema.parse(versioned({ presentationId: scene.presentationId, canvas: scene.canvas, theme, pages }, scene.revision + 1, scene.upstreamHashes));
  }
  if (command.type === "add-page") {
    const id = `manual-page-${hashContent({ revision: scene.revision + 1, type: command.type }).slice(0, 14)}`;
    const page = { id, width: scene.canvas.width, height: scene.canvas.height, background: String(scene.theme.background ?? "#FFFFFF"), speakerNotes: [], nodes: [], requiredSourceIds: [], selectedCandidateId: `manual-${id}`, alternativeCandidateIds: [], pageLinkIds: [], riskFlags: [] };
    return SceneGraphSchema.parse(versioned({ presentationId: scene.presentationId, canvas: scene.canvas, theme: scene.theme, pages: [...scene.pages, page] }, scene.revision + 1, scene.upstreamHashes));
  }
  if (command.type === "duplicate-page" || command.type === "delete-page" || command.type === "reorder-page") {
    const sourceIndex = scene.pages.findIndex((page) => page.id === command.pageId);
    if (sourceIndex < 0) throw new Error("PAGE_NOT_FOUND");
    const source = scene.pages[sourceIndex]!;
    if (source.pageLinkIds.length) throw new Error("LINKED_PAGE_PROTECTED");
    let pages = [...scene.pages];
    if (command.type === "delete-page") {
      if (pages.length === 1) throw new Error("LAST_PAGE_PROTECTED");
      pages.splice(sourceIndex, 1);
    } else if (command.type === "reorder-page") {
      const targetIndex = Math.max(0, Math.min(pages.length - 1, Math.trunc(Number(command.value))));
      pages.splice(sourceIndex, 1); pages.splice(targetIndex, 0, source);
    } else {
      const id = `manual-page-${hashContent({ revision: scene.revision + 1, pageId: source.id }).slice(0, 14)}`;
      const nodes = source.nodes.map((node) => ({ ...node, id: `${id}-${hashContent(node.id).slice(0, 10)}`, sourceIds: node.sourceIds.filter((sourceId) => source.requiredSourceIds.includes(sourceId) === false) }));
      pages.splice(sourceIndex + 1, 0, { ...source, id, nodes, requiredSourceIds: [], selectedCandidateId: `manual-${id}`, alternativeCandidateIds: [], pageLinkIds: [], riskFlags: [] });
    }
    return SceneGraphSchema.parse(versioned({ presentationId: scene.presentationId, canvas: scene.canvas, theme: scene.theme, pages }, scene.revision + 1, scene.upstreamHashes));
  }
  let found = false;
  const pages = scene.pages.map((page) => {
    if (page.id !== command.pageId) return page;
    if (command.type === "align-nodes" || command.type === "distribute-nodes") {
      const value = command.value as { nodeIds?: string[]; axis?: "horizontal" | "vertical"; mode?: "start" | "center" | "end" };
      const selected = page.nodes.filter((node) => value.nodeIds?.includes(node.id));
      if (selected.length < 2) throw new Error("MULTI_SELECTION_REQUIRED");
      found = true;
      const axis = value.axis ?? "horizontal";
      const ordered = [...selected].sort((left, right) => axis === "horizontal" ? left.bounds.x - right.bounds.x : left.bounds.y - right.bounds.y);
      const first = ordered[0]!;
      const last = ordered.at(-1)!;
      const updatedBounds = new Map<string, SceneNode["bounds"]>();
      if (command.type === "align-nodes") {
        const coordinate = axis === "horizontal"
          ? value.mode === "end" ? Math.max(...selected.map((node) => node.bounds.x + node.bounds.width)) : value.mode === "center" ? selected.reduce((sum, node) => sum + node.bounds.x + node.bounds.width / 2, 0) / selected.length : Math.min(...selected.map((node) => node.bounds.x))
          : value.mode === "end" ? Math.max(...selected.map((node) => node.bounds.y + node.bounds.height)) : value.mode === "center" ? selected.reduce((sum, node) => sum + node.bounds.y + node.bounds.height / 2, 0) / selected.length : Math.min(...selected.map((node) => node.bounds.y));
        for (const node of selected) updatedBounds.set(node.id, axis === "horizontal" ? { ...node.bounds, x: coordinate - (value.mode === "center" ? node.bounds.width / 2 : value.mode === "end" ? node.bounds.width : 0) } : { ...node.bounds, y: coordinate - (value.mode === "center" ? node.bounds.height / 2 : value.mode === "end" ? node.bounds.height : 0) });
      } else {
        const start = axis === "horizontal" ? first.bounds.x + first.bounds.width / 2 : first.bounds.y + first.bounds.height / 2;
        const end = axis === "horizontal" ? last.bounds.x + last.bounds.width / 2 : last.bounds.y + last.bounds.height / 2;
        ordered.forEach((node, index) => { const center = start + (end - start) * index / (ordered.length - 1); updatedBounds.set(node.id, axis === "horizontal" ? { ...node.bounds, x: center - node.bounds.width / 2 } : { ...node.bounds, y: center - node.bounds.height / 2 }); });
      }
      return { ...page, nodes: page.nodes.map((node) => { const bounds = updatedBounds.get(node.id); return bounds ? { ...node, bounds, contentHash: hashContent({ content: node.content, style: node.style, bounds }) } : node; }) };
    }
    if (command.type === "add-text" || command.type === "add-shape" || command.type === "add-image") {
      found = true;
      const id = `manual-${hashContent({ revision: scene.revision + 1, pageId: page.id, type: command.type, value: command.value }).slice(0, 14)}`;
      const isText = command.type === "add-text";
      const isImage = command.type === "add-image";
      const bounds = isText
        ? { x: page.width * 0.15, y: page.height * 0.42, width: page.width * 0.7, height: page.height * 0.14 }
        : { x: page.width * 0.25, y: page.height * 0.25, width: page.width * 0.5, height: page.height * 0.5 };
      const content = isText ? { text: String(command.value ?? ""), semantic: "body", contentKind: "manual" } : isImage ? { url: String(command.value ?? ""), alt: "", fit: "contain", focalPolicy: "auto", mediaRole: "subject", assetId: String(command.value ?? "") ? `user-${id}` : undefined } : {};
      const style = isText ? { fontFamily: String(scene.theme.bodyFontFamily ?? "Microsoft YaHei"), fontSize: Number(scene.theme.bodyPt ?? 20), fontWeight: Number(scene.theme.bodyWeight ?? 400), color: String(scene.theme.text ?? "#111111"), lineHeight: Number(scene.theme.lineHeight ?? 1.2), align: "left", verticalAlign: "middle" } : isImage ? {} : { fill: String(scene.theme.primary ?? "#2D7A50"), opacity: 1, radius: Number(scene.theme.radius ?? 0), stroke: String(scene.theme.primary ?? "#2D7A50") };
      const node: SceneNode = { id, kind: isText ? "text" : isImage ? "image" : "shape", sourceIds: [id], bounds, zIndex: page.nodes.length ? Math.max(...page.nodes.map((item) => item.zIndex)) + 1 : 0, style, content, locked: false, contentHash: hashContent({ content, style, bounds }) };
      return { ...page, nodes: [...page.nodes, node] };
    }
    if (command.type === "duplicate-node") {
      const source = page.nodes.find((node) => node.id === command.nodeId);
      if (!source) throw new Error("NODE_NOT_FOUND");
      found = true;
      const id = `manual-${hashContent({ revision: scene.revision + 1, source: source.id }).slice(0, 14)}`;
      const bounds = { ...source.bounds, x: Math.min(page.width - source.bounds.width, source.bounds.x + 18), y: Math.min(page.height - source.bounds.height, source.bounds.y + 18) };
      const copy = { ...source, id, sourceIds: [id], bounds, zIndex: Math.max(...page.nodes.map((node) => node.zIndex), 0) + 1, locked: false, contentHash: hashContent({ content: source.content, style: source.style, bounds }) };
      return { ...page, nodes: [...page.nodes, copy] };
    }
    return {
      ...page,
      nodes: page.nodes.flatMap((node) => {
        if (node.id !== command.nodeId) return [node];
        found = true;
        if (node.locked && command.type !== "set-locked") throw new Error("NODE_LOCKED");
        if (command.type === "delete-node") return [];
        let changed = node;
        if (command.type === "set-text" && node.kind === "text") changed = { ...node, content: { ...node.content, text: String(command.value) } };
        if (command.type === "set-style") {
          const update = command.value as Record<string, unknown>;
          const allowed = new Set(["fontFamily", "fontSize", "fontWeight", "color", "lineHeight", "align", "fill", "stroke", "opacity", "radius"]);
          if (Object.keys(update).some((key) => !allowed.has(key))) throw new Error("STYLE_PROPERTY_INVALID");
          changed = { ...node, style: { ...node.style, ...update } };
        }
        if (command.type === "set-bounds") changed = { ...node, bounds: command.value as SceneNode["bounds"] };
        if (command.type === "set-z") changed = { ...node, zIndex: Number(command.value) };
        if (command.type === "set-rotation") changed = { ...node, style: { ...node.style, rotation: Number(command.value) } };
        if (command.type === "set-asset" && node.kind === "image") {
          const value = command.value as { url?: string; assetId?: string };
          changed = { ...node, content: { ...node.content, url: String(value.url ?? ""), assetId: String(value.assetId ?? "") } };
        }
        if (command.type === "set-crop" && node.kind === "image") changed = { ...node, content: { ...node.content, fit: String(command.value) } };
        if (command.type === "set-locked") changed = { ...node, locked: Boolean(command.value) };
        return [{ ...changed, contentHash: hashContent({ content: changed.content, style: changed.style, bounds: changed.bounds }) }];
      })
    };
  });
  if (!found) throw new Error("NODE_NOT_FOUND");
  const payload = {
    presentationId: scene.presentationId,
    canvas: scene.canvas,
    theme: scene.theme,
    pages
  };
  return SceneGraphSchema.parse(versioned(payload, scene.revision + 1, scene.upstreamHashes));
}
