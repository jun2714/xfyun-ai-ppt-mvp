export interface CostPolicyConfig {
  textInputRmbPerMillion: number;
  textOutputRmbPerMillion: number;
  imageRmbPerCall: number;
}

export class ModelCostPolicy {
  constructor(private readonly config: CostPolicyConfig) {}

  estimateText(inputTokens: number, outputTokens: number): number {
    return this.round(inputTokens * this.config.textInputRmbPerMillion / 1_000_000 + outputTokens * this.config.textOutputRmbPerMillion / 1_000_000);
  }
  estimateImage(): number { return this.round(this.config.imageRmbPerCall); }
  private round(value: number): number { return Math.round(value * 1_000_000) / 1_000_000; }
}
