import type { PresentationState, PresentationStateRepositoryPort } from "../../../application/ports/presentation-state-repository.port.js";

export class MemoryPresentationStateRepository implements PresentationStateRepositoryPort {
  private readonly records = new Map<string, PresentationState>();
  /** Cloning prevents a failed job from leaking partially mutated state into the repository. */
  save(state: PresentationState) { this.records.set(state.brief.id, structuredClone(state)); }
  get(id: string) { const value = this.records.get(id); return value ? structuredClone(value) : undefined; }
  list() { return [...this.records.values()].map((value) => structuredClone(value)); }
}
