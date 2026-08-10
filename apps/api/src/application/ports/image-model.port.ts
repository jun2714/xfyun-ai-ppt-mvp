import type { ImageModelResult } from "../../domain/model-generation/model.types.js";

export interface ImageModelCommand {
  prompt: string;
  size: string;
}

/** Sends exactly one structured image command to a provider adapter. */
export interface ImageModelPort {
  generate(command: ImageModelCommand): Promise<ImageModelResult>;
}
