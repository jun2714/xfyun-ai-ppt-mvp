import {
  AssetPlanSchema,
  hashContent,
  versioned,
  type AssetPlan,
  type NarrativeOutline,
  type PageDesignIntent
} from "@sparkdeck/presentation-model";
import type { ResolvedCandidate, ResolvedCompositionNode } from "@sparkdeck/composition-engine";

const findNode = (node: ResolvedCompositionNode, sourceId: string): ResolvedCompositionNode | undefined => {
  if (node.sourceIds.includes(sourceId)) return node;
  for (const child of node.children) {
    const match = findNode(child, sourceId);
    if (match) return match;
  }
  return undefined;
};

export function buildAssetPlan(input: {
  presentationId: string;
  outline: NarrativeOutline;
  intents: PageDesignIntent[];
  candidateSets: ResolvedCandidate[][];
}): AssetPlan {
  const selectedCompositionHashes: Record<string, string> = {};
  const placements = input.outline.pages.flatMap((page) => {
    const intent = input.intents.find((item) => item.pageId === page.id);
    const set = input.candidateSets[input.outline.pages.findIndex((item) => item.id === page.id)] ?? [];
    const selected = set.find((candidate) => candidate.selected);
    if (!intent || !selected) return [];
    selectedCompositionHashes[page.id] = hashContent(selected.resolved);
    return intent.mediaRequests.flatMap((request) => {
      const leaf = findNode(selected.resolved, request.id);
      if (!leaf) return [];
      const targetAspectRatio = leaf.bounds.width / leaf.bounds.height;
      return [{
        id: `placement-${hashContent({ pageId: page.id, requestId: request.id, candidateId: selected.id }).slice(0, 16)}`,
        pageId: page.id,
        requestId: request.id,
        claimIds: request.claimIds,
        role: request.role,
        boundsRef: leaf.id,
        targetAspectRatio,
        fit: request.fit,
        focalPolicy: request.focalPolicy,
        required: request.required,
        source: "none" as const,
        ...(request.textSafeArea ? { textSafeArea: request.textSafeArea } : {}),
        ...(request.continuityKey ? { continuityKey: request.continuityKey } : {})
      }];
    });
  });
  return AssetPlanSchema.parse(versioned({
    presentationId: input.presentationId,
    selectedCompositionHashes,
    placements,
    resolvedAssetIds: []
  }, 0, { outline: input.outline.contentHash }));
}

export type ImageRequestSpec = { prompt: string; size: "1024x1024" | "1536x1024" | "1024x1536"; promptHash: string };
export function selectImageSize(aspectRatio: number): ImageRequestSpec["size"] {
  if (aspectRatio >= 1.35) return "1536x1024";
  if (aspectRatio <= 0.74) return "1024x1536";
  return "1024x1024";
}

export function buildImageRequest(input: {
  request: PageDesignIntent["mediaRequests"][number];
  targetAspectRatio: number;
  illustrationDirection?: string | undefined;
}): ImageRequestSpec {
  const roleInstruction: Record<typeof input.request.role, string> = {
    background: "Create a full-bleed scene, preserve the requested text-safe area, and keep important subjects away from that area.",
    subject: "Create one clearly framed subject with a clean surrounding field.",
    cutout: "Create one isolated subject on a plain background suitable for cutout use.",
    detail: "Create a close detail that remains legible at presentation size.",
    evidence: "Create a truthful explanatory visual with no invented labels or text."
  };
  const prompt = [
    input.illustrationDirection,
    input.request.description,
    roleInstruction[input.request.role],
    `Target aspect ratio ${input.targetAspectRatio.toFixed(3)}.`,
    input.request.textSafeArea && input.request.textSafeArea !== "none" ? `Keep a calm text-safe area on the ${input.request.textSafeArea}.` : undefined,
    "Do not render words, captions, watermarks, logos, borders, slide frames, or UI."
  ].filter(Boolean).join(" ");
  return { prompt, size: selectImageSize(input.targetAspectRatio), promptHash: hashContent({ version: "007.2", prompt }) };
}
