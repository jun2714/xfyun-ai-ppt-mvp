import {
  SceneGraphSchema,
  hashContent,
  versioned,
  type AssetPlan,
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
  assetPlan?: AssetPlan | undefined;
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
                alt: asset?.alt ?? request?.description ?? "",
                fit: placement?.fit ?? request?.fit ?? "cover",
                focalPolicy: placement?.focalPolicy ?? request?.focalPolicy ?? "auto",
                mediaRole: placement?.role ?? request?.role ?? "subject"
              }
            : kind === "chart"
              ? { rows: group?.rows ?? [], label: group?.label ?? "" }
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
            ? shapeStyle(String(leaf.props.treatment ?? "surface"), input.tokens)
            : kind === "image"
              ? { radius: request?.role === "background" ? 0 : input.tokens.radius }
              : { fill: input.tokens.primary, stroke: input.tokens.secondary, color: input.tokens.text };
        const contentHash = hashContent({ content, style, bounds: leaf.bounds });
        return { id: leaf.id, kind, sourceIds: leaf.sourceIds, bounds: leaf.bounds, zIndex, style, content, locked: false, contentHash };
      });
    const riskFlags: Array<"opening" | "closing" | "full-bleed" | "comparison" | "reveal" | "low-confidence"> = [];
    if (pageIndex === 0) riskFlags.push("opening");
    if (pageIndex === input.outline.pages.length - 1) riskFlags.push("closing");
    if (intent.visualStrategy === "background" || nodes.some((node) => node.kind === "image" && node.content.mediaRole === "background")) riskFlags.push("full-bleed");
    if (page.contentGroups.some((group) => group.kind === "comparison")) riskFlags.push("comparison");
    if (intent.relationships.some((relationship) => relationship.kind === "reveals")) riskFlags.push("reveal");
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
  type: "set-text" | "set-bounds" | "set-z" | "set-asset" | "set-crop" | "add-text" | "add-shape" | "delete-node";
  pageId: string;
  nodeId: string;
  value: unknown;
  expectedRevision: number;
};

export function applySceneCommand(scene: SceneGraph, command: SceneCommand): SceneGraph {
  if (scene.revision !== command.expectedRevision) throw new Error("REVISION_CONFLICT");
  let found = false;
  const pages = scene.pages.map((page) => {
    if (page.id !== command.pageId) return page;
    if (command.type === "add-text" || command.type === "add-shape") {
      found = true;
      const id = `manual-${hashContent({ revision: scene.revision + 1, pageId: page.id, type: command.type, value: command.value }).slice(0, 14)}`;
      const isText = command.type === "add-text";
      const bounds = isText
        ? { x: page.width * 0.15, y: page.height * 0.42, width: page.width * 0.7, height: page.height * 0.14 }
        : { x: page.width * 0.25, y: page.height * 0.25, width: page.width * 0.5, height: page.height * 0.5 };
      const content = isText ? { text: String(command.value || "双击编辑文字"), semantic: "body", contentKind: "manual" } : {};
      const style = isText ? { fontFamily: String(scene.theme.bodyFontFamily ?? "Microsoft YaHei"), fontSize: Number(scene.theme.bodyPt ?? 20), fontWeight: Number(scene.theme.bodyWeight ?? 400), color: String(scene.theme.text ?? "#111111"), lineHeight: Number(scene.theme.lineHeight ?? 1.2), align: "left", verticalAlign: "middle" } : { fill: String(scene.theme.primary ?? "#2D7A50"), opacity: 1, radius: Number(scene.theme.radius ?? 0), stroke: String(scene.theme.primary ?? "#2D7A50") };
      const node: SceneNode = { id, kind: isText ? "text" : "shape", sourceIds: [id], bounds, zIndex: page.nodes.length ? Math.max(...page.nodes.map((item) => item.zIndex)) + 1 : 0, style, content, locked: false, contentHash: hashContent({ content, style, bounds }) };
      return { ...page, nodes: [...page.nodes, node] };
    }
    return {
      ...page,
      nodes: page.nodes.flatMap((node) => {
        if (node.id !== command.nodeId) return [node];
        found = true;
        if (command.type === "delete-node") return [];
        let changed = node;
        if (command.type === "set-text" && node.kind === "text") changed = { ...node, content: { ...node.content, text: String(command.value) } };
        if (command.type === "set-bounds") changed = { ...node, bounds: command.value as SceneNode["bounds"] };
        if (command.type === "set-z") changed = { ...node, zIndex: Number(command.value) };
        if (command.type === "set-asset" && node.kind === "image") changed = { ...node, content: { ...node.content, url: String(command.value), assetId: `user-${node.id}` } };
        if (command.type === "set-crop" && node.kind === "image") changed = { ...node, content: { ...node.content, fit: String(command.value) } };
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
