import type { ImageModelResult } from "../../domain/model-generation/model.types.js";

export interface ImageModelCommand {
  prompt: string;
  size: string;
}

export interface ImageModelPort {
  generate(command: ImageModelCommand): Promise<ImageModelResult>;
}
