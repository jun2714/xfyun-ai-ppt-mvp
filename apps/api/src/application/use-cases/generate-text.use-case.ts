import type { TextGenerationRequest, TextGenerationResponse } from "../../domain/model-generation/model.types.js";
import { ModelCostPolicy } from "../../domain/budget/model-cost-policy.js";
import type { TextModelPort } from "../ports/text-model.port.js";

/** Issues one provider request and records returned usage without imposing a price or output cap. */
export class GenerateTextUseCase {
  constructor(
    private readonly model: TextModelPort,
    private readonly costPolicy: ModelCostPolicy
  ) {}

  async execute(input: TextGenerationRequest): Promise<TextGenerationResponse> {
    const result = await this.model.generate({
      systemPrompt: input.systemPrompt,
      userPrompt: input.userPrompt,
      ...(input.maxOutputTokens === undefined ? {} : { maxOutputTokens: input.maxOutputTokens }),
      temperature: input.temperature ?? 0.2,
      responseFormat: input.responseFormat
    });
    return {
      content: result.content,
      model: result.model,
      usage: {
        inputTokens: result.usage.inputTokens,
        outputTokens: result.usage.outputTokens,
        estimatedCostRmb: this.costPolicy.estimateText(result.usage.inputTokens, result.usage.outputTokens)
      }
    };
  }
}
