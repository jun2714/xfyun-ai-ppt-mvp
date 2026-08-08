export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";
export type Job = {
  id: string; scopeId: string; type: string; status: JobStatus;
  progress: number; stage: string; resultRef: string | null;
  error: { code: string; message: string } | null;
};
