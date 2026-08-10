export type VisualReviewIssue = {
  pageId: string;
  dimension: "Content" | "Design" | "Coherence";
  severity: "warning" | "error";
  message: string;
  repairIntent: string;
};
export type VisualReviewCommand = { contactSheetDataUri: string; pageIds: string[]; instructions: string; maxOutputTokens: number };
export type VisualReviewResult = { model: string; inputTokens: number; outputTokens: number; issues: VisualReviewIssue[] };
export interface VisualReviewPort { review(command: VisualReviewCommand): Promise<VisualReviewResult> }
