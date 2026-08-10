import type { TextModelResult } from "../../domain/model-generation/model.types.js";

export interface TextModelCommand {
  systemPrompt: string;
  userPrompt: string;
  maxOutputTokens?: number;
  temperature: number;
  responseFormat: "text" | "json_object";
}

/** Sends one schema-constrained text request without automatic retries. */
export interface TextModelPort {
  generate(command: TextModelCommand): Promise<TextModelResult>;
}
