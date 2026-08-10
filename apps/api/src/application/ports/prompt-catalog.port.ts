/** A versioned prompt contract loaded outside production source code. */
export type PromptContract = { id: string; version: string; content: string; contentHash: string };

/**
 * Supplies model instructions without embedding prompt prose in TypeScript.
 * Implementations must reject missing or empty contracts instead of falling back silently.
 */
export interface PromptCatalogPort {
  get(id: "narrative" | "design" | "image" | "visual-quality"): PromptContract;
}
