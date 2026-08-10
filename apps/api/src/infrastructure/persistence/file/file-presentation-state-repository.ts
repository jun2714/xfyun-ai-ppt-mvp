import { existsSync, mkdirSync, readFileSync, readdirSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import type { PresentationState, PresentationStateRepositoryPort } from "../../../application/ports/presentation-state-repository.port.js";

/** Stores each aggregate as one atomically replaced JSON document, so a process restart cannot erase projects. */
export class FilePresentationStateRepository implements PresentationStateRepositoryPort {
  private readonly root: string;

  constructor(directory: string) {
    this.root = resolve(directory, "presentations");
    mkdirSync(this.root, { recursive: true });
    for (const entry of readdirSync(this.root)) if (entry.endsWith(".json.bak")) {
      const backup = join(this.root, entry);
      const target = backup.slice(0, -4);
      if (!existsSync(target)) renameSync(backup, target); else rmSync(backup, { force: true });
    }
  }

  save(state: PresentationState): void {
    const target = this.pathFor(state.brief.id);
    const temporary = `${target}.${process.pid}.${Date.now()}.tmp`;
    const backup = `${target}.bak`;
    mkdirSync(dirname(target), { recursive: true });
    try {
      writeFileSync(temporary, JSON.stringify(state), { encoding: "utf8", flag: "wx" });
      if (existsSync(target)) { rmSync(backup, { force: true }); renameSync(target, backup); }
      try { renameSync(temporary, target); rmSync(backup, { force: true }); }
      catch (error) { if (!existsSync(target) && existsSync(backup)) renameSync(backup, target); throw error; }
    } finally {
      rmSync(temporary, { force: true });
    }
  }

  get(id: string): PresentationState | undefined {
    try { return this.normalize(JSON.parse(readFileSync(this.pathFor(id), "utf8")) as PresentationState); }
    catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return undefined;
      throw error;
    }
  }

  list(): PresentationState[] {
    return readdirSync(this.root, { withFileTypes: true })
      .filter((entry) => entry.isFile() && entry.name.endsWith(".json"))
      .map((entry) => this.normalize(JSON.parse(readFileSync(join(this.root, entry.name), "utf8")) as PresentationState));
  }

  /** IDs are never interpreted as paths; this also blocks traversal in externally supplied route parameters. */
  private pathFor(id: string): string {
    if (!/^[a-z0-9_-]+$/i.test(id)) throw new Error("INVALID_PRESENTATION_ID");
    return join(this.root, `${id}.json`);
  }

  /** Runtime-only collections were added in 008; old project files receive empty durable defaults. */
  private normalize(state: PresentationState): PresentationState {
    return { ...state, jobs: state.jobs ?? [], idempotency: state.idempotency ?? {}, usage: state.usage ?? [] };
  }
}
