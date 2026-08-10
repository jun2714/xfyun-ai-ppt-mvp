import type { TextGenerationRequest, TextGenerationResponse } from "../../domain/model-generation/model.types.js";
import { ModelCostPolicy } from "../../domain/budget/model-cost-policy.js";
import type { TextModelPort } from "../ports/text-model.port.js";

/** Applies a hard cost ceiling before issuing one provider text request. */
export class GenerateTextUseCase {
  constructor(
    private readonly model: TextModelPort,
    private readonly costPolicy: ModelCostPolicy,
    private readonly defaultMaxOutputTokens: number
  ) {}

  async execute(input: TextGenerationRequest): Promise<TextGenerationResponse> {
    const maxOutputTokens = input.maxOutputTokens ?? this.defaultMaxOutputTokens;
    const estimatedInputTokens = Math.ceil((input.systemPrompt.length + input.userPrompt.length) / 2);
    this.costPolicy.assertWithinBudget(this.costPolicy.estimateText(estimatedInputTokens, maxOutputTokens));

    const result = await this.model.generate({
      systemPrompt: input.systemPrompt,
      userPrompt: input.userPrompt,
      maxOutputTokens,
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
