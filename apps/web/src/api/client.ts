import type { Job } from "../entities/types";

const API = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";
export const requestKey = () => crypto.randomUUID();

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, { headers: { "content-type": "application/json", ...(init?.headers ?? {}) }, ...init });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error?.message ?? response.statusText);
  return body.data ?? body;
}

export async function startJob(path: string, payload: Record<string, unknown> = {}) {
  const job = await api<Job>(path, { method: "POST", body: JSON.stringify({ idempotencyKey: requestKey(), ...payload }) });
  return waitForJob(job.id);
}

export async function waitForJob(jobId: string, onProgress?: (job: Job) => void): Promise<Job> {
  for (let attempt = 0; attempt < 300; attempt += 1) {
    const job = await api<Job>(`/jobs/${jobId}`);
    onProgress?.(job);
    if (job.status === "succeeded") return job;
    if (job.status === "failed") throw new Error(job.error?.message ?? "生成失败");
    await new Promise((resolve) => window.setTimeout(resolve, 500));
  }
  throw new Error("生成任务超时，请检查服务状态后重试");
}

export async function downloadExport(presentationId: string, revision: number) {
  const response = await fetch(`${API}/presentations/${presentationId}/exports`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ expectedRevision: revision, idempotencyKey: requestKey() })
  });
  if (!response.ok) {
    const body = await response.json();
    throw new Error(body.error?.message ?? "导出失败");
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${presentationId}.pptx`;
  anchor.click();
  URL.revokeObjectURL(url);
}
