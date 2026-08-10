export class AppError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly statusCode = 500,
    public readonly details: unknown[] = [],
    public readonly context: {
      stage?: string; presentationId?: string; pageId?: string; nodeIds?: string[];
      incurredCost?: boolean; manualRetryAllowed?: boolean;
      modelTelemetry?: { model: string; inputTokens: number; outputTokens: number; estimatedCostRmb: number; prompt: { id: string; version: string; contentHash: string } };
      modelResponseEvidence?: { contentHash: string; characterCount: number; validationIssues: unknown[] };
    } = {}
  ) {
    super(message);
    this.name = "AppError";
  }
}
