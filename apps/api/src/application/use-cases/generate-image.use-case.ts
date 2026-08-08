import type { ImageGenerationRequest, ImageGenerationResponse } from "../../domain/model-generation/model.types.js";
import { ModelCostPolicy } from "../../domain/budget/model-cost-policy.js";
import type { ImageModelPort } from "../ports/image-model.port.js";

export class GenerateImageUseCase {
  constructor(
    private readonly model: ImageModelPort,
    private readonly costPolicy: ModelCostPolicy
  ) {}

  async execute(input: ImageGenerationRequest): Promise<ImageGenerationResponse> {
    const estimatedCostRmb = this.costPolicy.estimateImage();
    this.costPolicy.assertWithinBudget(estimatedCostRmb);
    const result = await this.model.generate(input);
    return { ...result, estimatedCostRmb };
  }
}
