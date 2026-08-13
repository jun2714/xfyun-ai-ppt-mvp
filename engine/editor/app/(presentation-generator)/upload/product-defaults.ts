import {
  LanguageType,
  type PresentationConfig,
  ToneType,
  VerbosityType,
} from "./type";

/** 与旧 Web 创建页一致的幼教生成约束 */
export const TEACHNOVA_DEFAULT_INSTRUCTIONS =
  "保持中文自然、简洁、适龄；页面结构由内容决定，不套用固定流程。" +
  "配图提示词必须使用中文；若画面出现人物，必须全部为中国人面孔与形象，符合中国幼教场景，不要出现欧美面孔。";

/** 旧产品创建接口使用的语言字段 */
export const TEACHNOVA_API_LANGUAGE = "Chinese";

export const createTeachnovaDefaultConfig = (): PresentationConfig => ({
  slides: null,
  language: LanguageType.ChineseSimplified,
  prompt: "",
  tone: ToneType.Educational,
  verbosity: VerbosityType.Standard,
  instructions: TEACHNOVA_DEFAULT_INSTRUCTIONS,
  includeTableOfContents: false,
  includeTitleSlide: true,
  webSearch: false,
});

/**
 * 拼装方式对齐旧 Web CreatePage：
 * 主题 / 观众 / 年龄 / 使用场景 / 视觉偏好 + 固定尾句。
 */
export function buildTeachnovaPrompt(
  prompt: string,
  teachingContext: {
    audience?: string;
    age?: string;
    scene?: string;
    style?: string;
  } = {},
) {
  const audience = teachingContext.audience?.trim() || "";
  const age = teachingContext.age?.trim() || "";
  const scene = teachingContext.scene?.trim() || "";
  const style = teachingContext.style?.trim() || "";

  return [
    prompt.trim() ? `主题：${prompt.trim()}` : "",
    audience
      ? `观众：${audience}${age ? `（${age}）` : ""}`
      : age
        ? `观众：${age}`
        : "",
    scene ? `使用场景：${scene}` : "",
    style ? `视觉偏好：${style}` : "",
    "请生成适合实际教学或沟通使用的中文演示文稿。内容必须面向观众，不要输出制作说明、图片提示词或设计备注。",
  ]
    .filter(Boolean)
    .join("\n");
}

export function parseTeachnovaPrompt(content: string) {
  const normalized = content.trim();
  const lines = normalized.split(/\r?\n/).map((line) => line.trim());
  const pick = (prefix: string) =>
    lines
      .find((line) => line.startsWith(prefix))
      ?.slice(prefix.length)
      .trim() || "";

  const topic = pick("主题：") || normalized;
  const audienceLine = pick("观众：");
  const audienceMatch = audienceLine.match(/^(.*?)（(.+?)）$/);
  const audience = audienceMatch?.[1]?.trim() || audienceLine;
  const age = audienceMatch?.[2]?.trim() || "";
  const scene = pick("使用场景：");
  const style = pick("视觉偏好：");

  return {
    topic,
    teachingContext: {
      ...(audience ? { audience } : {}),
      ...(age ? { age } : {}),
      ...(scene ? { scene } : {}),
      ...(style ? { style } : {}),
    },
  };
}

export function getTeachnovaWebOutlineUrl(
  presentationId: string,
  options: {
    templateId?: string | null;
    createMode?: "topic" | "template";
  } = {},
) {
  const base =
    (typeof window !== "undefined" &&
      (window as Window & { env?: { NEXT_PUBLIC_WEB_APP_URL?: string } }).env
        ?.NEXT_PUBLIC_WEB_APP_URL) ||
    process.env.NEXT_PUBLIC_WEB_APP_URL ||
    "http://127.0.0.1:5173";
  const url = new URL(
    `${base.replace(/\/$/, "")}/presentations/${presentationId}/outline`,
  );
  if (options.createMode) {
    url.searchParams.set("mode", options.createMode);
  }
  if (options.templateId) {
    url.searchParams.set("template", options.templateId);
  }
  return url.toString();
}
