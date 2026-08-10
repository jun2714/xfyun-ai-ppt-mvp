import type { PresentationState, PresentationStateRepositoryPort } from "../../../application/ports/presentation-state-repository.port.js";

export class MemoryPresentationStateRepository implements PresentationStateRepositoryPort {
  private readonly records = new Map<string, PresentationState>();
  save(state: PresentationState) { this.records.set(state.brief.id, state); }
  get(id: string) { return this.records.get(id); }
  list() { return [...this.records.values()]; }
}
