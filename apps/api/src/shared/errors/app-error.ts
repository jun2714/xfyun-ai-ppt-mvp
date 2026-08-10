export class AppError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly statusCode = 500,
    public readonly details: unknown[] = [],
    public readonly context: { stage?: string; presentationId?: string; pageId?: string; nodeIds?: string[]; incurredCost?: boolean; manualRetryAllowed?: boolean } = {}
  ) {
    super(message);
    this.name = "AppError";
  }
}
