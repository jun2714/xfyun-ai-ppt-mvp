import type { AssetBundlePlan, DeckDesignPlan, LayoutDecisionTrace, MediaRole, NarrativeOutline, PageDesignIntent, PresentationBrief, QualityReport, RenderEvidence, SceneGraph } from "@sparkdeck/presentation-model";
import type { DesignTokens } from "@sparkdeck/design-language";
import type { ResolvedCandidate } from "@sparkdeck/composition-engine";
import type { buildVisualReviewBatch } from "@sparkdeck/quality-engine";
import type { Job } from "../../domain/jobs/job.js";

export type StoredAsset = { url?: string; base64?: string; alt: string; promptHash: string; identityId: string; role: MediaRole; width?: number; height?: number; qualityStatus: "pending" | "passed" | "failed" };
export type AssetResolutionTrace = { placementId: string; identityId: string; requestHash: string; source: string; cacheHit: boolean; assetId?: string };
export type UsageLedgerEntry = { id: string; provider: string; model: string; purpose: string; scopeId: string; requestHash: string; estimatedCostRmb: number; success: boolean; parentJob: string };
export type PresentationState = {
  brief: PresentationBrief;
  outline?: NarrativeOutline;
  design?: { plan: DeckDesignPlan; intents: PageDesignIntent[] };
  tokens?: DesignTokens;
  canvas?: { width: number; height: number };
  candidates?: ResolvedCandidate[][];
  assetBundle?: AssetBundlePlan;
  assets: Record<string, StoredAsset>;
  scene?: SceneGraph;
  quality?: QualityReport;
  renderEvidence?: RenderEvidence;
  layoutTraces: Record<string, LayoutDecisionTrace>;
  assetTraces: AssetResolutionTrace[];
  visualReview?: ReturnType<typeof buildVisualReviewBatch>;
  repairCount: number;
  history: SceneGraph[];
  future: SceneGraph[];
  jobs: Job[];
  idempotency: Record<string, string>;
  usage: UsageLedgerEntry[];
};

/** Atomically persists the complete presentation aggregate and restart evidence. */
export interface PresentationStateRepositoryPort {
  /** Atomically replaces one complete state revision. */
  save(state: PresentationState): void;
  get(id: string): PresentationState | undefined;
  list(): PresentationState[];
}
