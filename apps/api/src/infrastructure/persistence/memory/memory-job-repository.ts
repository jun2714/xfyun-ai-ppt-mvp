import type { JobRepositoryPort } from "../../../application/ports/job-repository.port.js";
import type { Job } from "../../../domain/jobs/job.js";
export class MemoryJobRepository implements JobRepositoryPort {
  private readonly jobs = new Map<string, Job>();
  async save(job: Job) { this.jobs.set(job.id, structuredClone(job)); }
  async findById(id: string) { const job = this.jobs.get(id); return job ? structuredClone(job) : null; }
  async findActive(scopeId: string, type: Job["type"]) { const job = [...this.jobs.values()].find((item) => item.scopeId === scopeId && item.type === type && (item.status === "queued" || item.status === "running")); return job ? structuredClone(job) : null; }
}
