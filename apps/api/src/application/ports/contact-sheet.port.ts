import type { SceneGraph } from "@sparkdeck/presentation-model";
/** Renders diagnostic Scene pages when actual-office pixels are not yet available. */
export interface ContactSheetPort { render(scene: SceneGraph, pageIds: string[]): Promise<string> }
