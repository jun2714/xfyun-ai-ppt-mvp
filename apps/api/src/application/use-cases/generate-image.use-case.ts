import type { ImageGenerationRequest, ImageGenerationResponse } from "../../domain/model-generation/model.types.js";
import { ModelCostPolicy } from "../../domain/budget/model-cost-policy.js";
import type { ImageModelPort } from "../ports/image-model.port.js";
import type { PromptCatalogPort } from "../ports/prompt-catalog.port.js";
import { hashContent } from "@sparkdeck/presentation-model";

/** Applies cost policy and a versioned external prompt contract to one unique asset request. */
export class GenerateImageUseCase {
  constructor(
    private readonly model: ImageModelPort,
    private readonly prompts: PromptCatalogPort,
    private readonly costPolicy: ModelCostPolicy
  ) {}

  /** Computes the provider request identity before a paid call so cache lookup is possible. */
  requestHash(input: ImageGenerationRequest): string {
    const prompt = this.prompts.get("image");
    return hashContent({ prompt: prompt.contentHash, context: input.context, size: input.size });
  }

  async execute(input: ImageGenerationRequest): Promise<ImageGenerationResponse> {
    const estimatedCostRmb = this.costPolicy.estimateImage();
    this.costPolicy.assertWithinBudget(estimatedCostRmb);
    const prompt = this.prompts.get("image");
    const contextJson = JSON.stringify(input.context);
    const requestHash = this.requestHash(input);
    const result = await this.model.generate({ prompt: `${prompt.content}\n${contextJson}`, size: input.size });
    return { ...result, requestHash, prompt: { id: prompt.id, version: prompt.version, contentHash: prompt.contentHash }, estimatedCostRmb };
  }
}
