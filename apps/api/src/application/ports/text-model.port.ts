import type { TextModelResult } from "../../domain/model-generation/model.types.js";

export interface TextModelCommand {
  systemPrompt: string;
  userPrompt: string;
  maxOutputTokens: number;
  temperature: number;
  responseFormat: "text" | "json_object";
}

export interface TextModelPort {
  generate(command: TextModelCommand): Promise<TextModelResult>;
}
