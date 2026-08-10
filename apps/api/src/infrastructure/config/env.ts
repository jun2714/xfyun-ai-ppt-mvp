import { AppError } from "../../shared/errors/app-error.js";

export interface AppConfig {
  dataDirectory: string;
  promptDirectory: string;
  officeRenderProgramId: string;
  dmxApiBaseUrl: string;
  dmxApiKey: string;
  textModel: string;
  imageModel: string;
  imageApiStyle: "responses" | "images";
  visionModel: string;
  textInputRmbPerMillion: number;
  textOutputRmbPerMillion: number;
  imageRmbPerCall: number;
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
    promptDirectory: process.env.PROMPT_DIRECTORY ?? "apps/api/prompts/008",
    officeRenderProgramId: process.env.OFFICE_RENDER_PROG_ID ?? "KWPP.Application",
    dmxApiBaseUrl: (process.env.DMX_API_BASE_URL ?? "https://www.dmxapi.cn/v1").replace(/\/$/, ""),
    dmxApiKey: process.env.DMX_API_KEY?.trim() ?? "",
    textModel: process.env.DMX_TEXT_MODEL ?? "qwen3.5-plus",
    imageModel: process.env.DMX_IMAGE_MODEL ?? "qwen-image-2.0",
    imageApiStyle: process.env.DMX_IMAGE_API_STYLE === "images" ? "images" : "responses",
    visionModel: process.env.DMX_VISION_MODEL ?? "gemini-2.5-flash",
    textInputRmbPerMillion: numberFromEnv("DMX_TEXT_INPUT_RMB_PER_MILLION", 0.4),
    textOutputRmbPerMillion: numberFromEnv("DMX_TEXT_OUTPUT_RMB_PER_MILLION", 2.4),
    imageRmbPerCall: numberFromEnv("DMX_IMAGE_RMB_PER_CALL", 0.158)
  };
}
