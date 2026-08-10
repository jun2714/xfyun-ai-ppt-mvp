export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";
export type JobStage = "queued"|"planning"|"generating_candidates"|"scoring"|"resolving_assets"|"regenerating_asset"|"rendering"|"rule_quality"|"visual_quality"|"repairing"|"exporting"|"completed"|"failed";
export type Job = {
  id: string; scopeId: string; type: string; status: JobStatus;
  progress: number; stage: JobStage; resultRef: string | null;
  error: { code: string; message: string; incurredCost: boolean; manualRetryAllowed: boolean } | null;
};
