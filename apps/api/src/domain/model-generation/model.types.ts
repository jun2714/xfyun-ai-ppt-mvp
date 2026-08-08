export interface TokenUsage {
  inputTokens: number;
  outputTokens: number;
}

export interface TextModelResult {
  content: string;
  model: string;
  usage: TokenUsage;
}

export interface ImageModelResult {
  model: string;
  url?: string;
  base64?: string;
}

export interface TextGenerationRequest {
  systemPrompt: string;
  userPrompt: string;
  maxOutputTokens?: number;
  temperature?: number;
  responseFormat: "text" | "json_object";
}

export interface TextGenerationResponse extends TextModelResult {
  usage: TokenUsage & { estimatedCostRmb: number };
}

export interface ImageGenerationRequest {
  prompt: string;
  size: string;
}

export interface ImageGenerationResponse extends ImageModelResult {
  estimatedCostRmb: number;
}
