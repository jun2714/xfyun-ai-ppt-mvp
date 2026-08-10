import type { RenderEvidence, SceneGraph } from "@sparkdeck/presentation-model";

export type RenderEvidenceArtifact = { evidence: RenderEvidence; contactSheetDataUri: string };

/** Produces page-by-page evidence from the actual exported PPTX and the same Scene Graph. */
export interface RenderEvidencePort {
  create(scene: SceneGraph, pptxBytes: Uint8Array): Promise<RenderEvidenceArtifact>;
}
