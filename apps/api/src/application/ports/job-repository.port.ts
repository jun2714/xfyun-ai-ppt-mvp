import type { Job } from "../../domain/jobs/job.js";
export interface JobRepositoryPort { save(job: Job): Promise<void>; findById(id: string): Promise<Job | null>; findActive(scopeId: string, type: Job["type"]): Promise<Job | null> }
