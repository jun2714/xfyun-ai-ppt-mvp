import type { SceneGraph } from "@sparkdeck/presentation-model";
export interface ContactSheetPort { render(scene: SceneGraph, pageIds: string[]): Promise<string> }
