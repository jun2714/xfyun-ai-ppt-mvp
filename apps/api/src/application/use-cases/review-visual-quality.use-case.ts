import type { ContactSheetPort } from "../ports/contact-sheet.port.js";
import type { VisualReviewPort } from "../ports/visual-review.port.js";
import type { SceneGraph } from "@sparkdeck/presentation-model";
import { ModelCostPolicy } from "../../domain/budget/model-cost-policy.js";

export class ReviewVisualQualityUseCase {
  constructor(private readonly renderer: ContactSheetPort, private readonly reviewer: VisualReviewPort, private readonly costPolicy: ModelCostPolicy, private readonly maxOutputTokens: number) {}
  async execute(scene: SceneGraph, pageIds: string[], instructions: string) {
    const contactSheetDataUri = await this.renderer.render(scene, pageIds);
    const estimatedInputTokens = 1_500 + Math.ceil(instructions.length / 2);
    this.costPolicy.assertWithinBudget(this.costPolicy.estimateText(estimatedInputTokens, this.maxOutputTokens));
    const result = await this.reviewer.review({ contactSheetDataUri, pageIds, instructions, maxOutputTokens: this.maxOutputTokens });
    return { ...result, estimatedCostRmb: this.costPolicy.estimateText(result.inputTokens, result.outputTokens) };
  }
}
