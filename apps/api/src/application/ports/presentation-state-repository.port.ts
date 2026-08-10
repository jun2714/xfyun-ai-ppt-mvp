import type { AssetPlan, DeckDesignPlan, NarrativeOutline, PageDesignIntent, PresentationBrief, QualityReport, SceneGraph } from "@sparkdeck/presentation-model";
import type { DesignTokens } from "@sparkdeck/design-language";
import type { ResolvedCandidate } from "@sparkdeck/composition-engine";
import type { buildVisualReviewBatch } from "@sparkdeck/quality-engine";

export type StoredAsset = { url?: string; base64?: string; alt: string; promptHash: string };
export type PresentationState = {
  brief: PresentationBrief;
  outline?: NarrativeOutline;
  design?: { plan: DeckDesignPlan; intents: PageDesignIntent[] };
  tokens?: DesignTokens;
  candidates?: ResolvedCandidate[][];
  assetPlan?: AssetPlan;
  assets: Record<string, StoredAsset>;
  scene?: SceneGraph;
  quality?: QualityReport;
  visualReview?: ReturnType<typeof buildVisualReviewBatch>;
  repairCount: number;
  history: SceneGraph[];
  future: SceneGraph[];
};

export interface PresentationStateRepositoryPort {
  save(state: PresentationState): void;
  get(id: string): PresentationState | undefined;
  list(): PresentationState[];
}
