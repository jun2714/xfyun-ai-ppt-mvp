import { AppError } from "../../shared/errors/app-error.js";

export interface AppConfig {
  dataDirectory: string;
  dmxApiBaseUrl: string;
  dmxApiKey: string;
  textModel: string;
  imageModel: string;
  visionModel: string;
  requestTimeoutMs: number;
  textMaxOutputTokens: number;
  textInputRmbPerMillion: number;
  textOutputRmbPerMillion: number;
  imageRmbPerCall: number;
  maxRequestRmb: number;
}

const numberFromEnv = (name: string, fallback: number): number => {
  const raw = process.env[name];
  if (!raw) return fallback;
  const value = Number(raw);
  if (!Number.isFinite(value) || value < 0) {
    throw new AppError("INVALID_CONFIG", `${name} must be a non-negative number`);
  }
  return value;
};

export function loadConfig(): AppConfig {
  return {
    dataDirectory: process.env.DATA_DIRECTORY ?? ".data",
    dmxApiBaseUrl: (process.env.DMX_API_BASE_URL ?? "https://www.dmxapi.cn/v1").replace(/\/$/, ""),
    dmxApiKey: process.env.DMX_API_KEY?.trim() ?? "",
    textModel: process.env.DMX_TEXT_MODEL ?? "qwen3.5-plus",
    imageModel: process.env.DMX_IMAGE_MODEL ?? "qwen-image-2.0",
    visionModel: process.env.DMX_VISION_MODEL ?? "gemini-2.5-flash",
    requestTimeoutMs: numberFromEnv("DMX_REQUEST_TIMEOUT_MS", 120_000),
    textMaxOutputTokens: numberFromEnv("DMX_TEXT_MAX_OUTPUT_TOKENS", 4_000),
    textInputRmbPerMillion: numberFromEnv("DMX_TEXT_INPUT_RMB_PER_MILLION", 0.4),
    textOutputRmbPerMillion: numberFromEnv("DMX_TEXT_OUTPUT_RMB_PER_MILLION", 2.4),
    imageRmbPerCall: numberFromEnv("DMX_IMAGE_RMB_PER_CALL", 0.158),
    maxRequestRmb: numberFromEnv("MODEL_MAX_REQUEST_RMB", 0.5)
  };
}
