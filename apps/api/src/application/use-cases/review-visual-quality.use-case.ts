import type { ContactSheetPort } from "../ports/contact-sheet.port.js";
import type { VisualReviewPort } from "../ports/visual-review.port.js";
import type { SceneGraph } from "@sparkdeck/presentation-model";
import { ModelCostPolicy } from "../../domain/budget/model-cost-policy.js";
import type { PromptCatalogPort } from "../ports/prompt-catalog.port.js";

/** Combines versioned review instructions with one final-render contact sheet. */
export class ReviewVisualQualityUseCase {
  constructor(private readonly renderer: ContactSheetPort, private readonly reviewer: VisualReviewPort, private readonly prompts: PromptCatalogPort, private readonly costPolicy: ModelCostPolicy) {}
  async execute(scene: SceneGraph, pageIds: string[], dimensions: readonly string[], finalPptxContactSheetDataUri?: string) {
    const prompt = this.prompts.get("visual-quality");
    // Final PPTX pixels take precedence; Scene rendering is retained only for non-export diagnostics.
    const contactSheetDataUri = finalPptxContactSheetDataUri ?? await this.renderer.render(scene, pageIds);
    const contextJson = JSON.stringify({ pageIds, dimensions });
    const result = await this.reviewer.review({ contactSheetDataUri, pageIds, systemPrompt: prompt.content, contextJson });
    return { ...result, prompt: { id: prompt.id, version: prompt.version, contentHash: prompt.contentHash }, estimatedCostRmb: this.costPolicy.estimateText(result.inputTokens, result.outputTokens) };
  }
}
