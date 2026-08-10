import { AppError } from "../../shared/errors/app-error.js";

export interface CostPolicyConfig {
  textInputRmbPerMillion: number;
  textOutputRmbPerMillion: number;
  imageRmbPerCall: number;
  maxRequestRmb: number;
}

export class ModelCostPolicy {
  constructor(private readonly config: CostPolicyConfig) {}

  estimateText(inputTokens: number, outputTokens: number): number {
    return this.round(inputTokens * this.config.textInputRmbPerMillion / 1_000_000 + outputTokens * this.config.textOutputRmbPerMillion / 1_000_000);
  }
  estimateImage(): number { return this.round(this.config.imageRmbPerCall); }
  assertWithinBudget(estimatedRmb: number): void {
    if (estimatedRmb > this.config.maxRequestRmb) throw new AppError("BUDGET_EXCEEDED", `Estimated model cost RMB ${estimatedRmb} exceeds request limit RMB ${this.config.maxRequestRmb}`, 402);
  }
  private round(value: number): number { return Math.round(value * 1_000_000) / 1_000_000; }
}
