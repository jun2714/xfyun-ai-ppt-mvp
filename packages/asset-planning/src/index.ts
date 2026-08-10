import {
  AssetBundlePlanSchema,
  hashContent,
  versioned,
  type AssetBundlePlan,
  type DeckDesignPlan,
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

/**
 * Builds one deck-wide bundle after composition selection.
 * Asset identities are deduplicated before any paid generation call is allowed.
 */
export function buildAssetBundlePlan(input: {
  presentationId: string;
  outline: NarrativeOutline;
  design: DeckDesignPlan;
  intents: PageDesignIntent[];
  candidateSets: ResolvedCandidate[][];
}): AssetBundlePlan {
  const selectedCompositionHashes: Record<string, string> = {};
  const placements = input.outline.pages.flatMap((page, pageIndex) => {
    const intent = input.intents.find((item) => item.pageId === page.id);
    const selected = input.candidateSets[pageIndex]?.find((candidate) => candidate.selected);
    if (!intent || !selected) return [];
    selectedCompositionHashes[page.id] = hashContent(selected.resolved);
    return intent.mediaRequests.flatMap((request) => {
      const leaf = findNode(selected.resolved, request.id);
      if (!leaf) return [];
      return [{
        id: `placement-${hashContent({ pageId: page.id, requestId: request.id, candidateId: selected.id }).slice(0, 16)}`,
        pageId: page.id,
        requestId: request.id,
        identityId: request.identityId,
        claimIds: request.claimIds,
        role: request.role,
        boundsRef: leaf.id,
        targetAspectRatio: leaf.bounds.width / leaf.bounds.height,
        fit: request.fit,
        focalPolicy: request.focalPolicy,
        required: request.required,
        source: "none" as const,
        ...(request.textSafeArea ? { textSafeArea: request.textSafeArea } : {})
      }];
    });
  });
  const usedIdentityIds = new Set(placements.map((placement) => placement.identityId));
  const identities = input.design.assetIdentities.filter((identity) => usedIdentityIds.has(identity.id));
  if (identities.length !== usedIdentityIds.size) throw new Error("ASSET_IDENTITY_REFERENCE_INVALID");
  return AssetBundlePlanSchema.parse(versioned({ presentationId: input.presentationId, selectedCompositionHashes, identities, placements, resolvedAssetIds: [] }, 0, { outline: input.outline.contentHash, design: input.design.contentHash }));
}

export type ImageRequestContext = {
  identityId: string;
  semanticEntityId: string;
  visualIdentityKey: string;
  role: PageDesignIntent["mediaRequests"][number]["role"];
  description: string;
  variantIntent?: string;
  reusePolicy: PageDesignIntent["mediaRequests"][number]["reusePolicy"];
  targetAspectRatio: number;
  focalPolicy: PageDesignIntent["mediaRequests"][number]["focalPolicy"];
  textSafeArea?: PageDesignIntent["mediaRequests"][number]["textSafeArea"];
  mediaLanguage?: DeckDesignPlan["visualGrammar"]["mediaLanguage"];
};
export type ImageRequestSpec = { context: ImageRequestContext; size: "1024x1024" | "1536x1024" | "1024x1536"; requestHash: string };

/** Maps solved aspect ratio to the provider's supported size grid. */
export function selectImageSize(aspectRatio: number): ImageRequestSpec["size"] {
  if (aspectRatio >= 1.35) return "1536x1024";
  if (aspectRatio <= 0.74) return "1024x1536";
  return "1024x1024";
}

/** Returns structured generation context; prompt prose is assembled by an external prompt contract. */
export function buildImageRequest(input: {
  request: PageDesignIntent["mediaRequests"][number];
  targetAspectRatio: number;
  mediaLanguage?: DeckDesignPlan["visualGrammar"]["mediaLanguage"] | undefined;
}): ImageRequestSpec {
  const context: ImageRequestContext = {
    identityId: input.request.identityId,
    semanticEntityId: input.request.semanticEntityId,
    visualIdentityKey: input.request.visualIdentityKey,
    role: input.request.role,
    description: input.request.description,
    reusePolicy: input.request.reusePolicy,
    targetAspectRatio: input.targetAspectRatio,
    focalPolicy: input.request.focalPolicy,
    ...(input.request.variantIntent ? { variantIntent: input.request.variantIntent } : {}),
    ...(input.request.textSafeArea ? { textSafeArea: input.request.textSafeArea } : {}),
    ...(input.mediaLanguage ? { mediaLanguage: input.mediaLanguage } : {})
  };
  return { context, size: selectImageSize(input.targetAspectRatio), requestHash: hashContent({ version: "008.0", context }) };
}
