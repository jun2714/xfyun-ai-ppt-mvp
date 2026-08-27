import type { Presentation, PresentationOutline, TemplateItem } from "../../entities/types";

export const AUTO_TEMPLATE_ID = "general";

const AUTO_TEMPLATE_ORDER = [
  "dynamic",
  "modern",
  "swift",
  "momentum",
  "standard",
] as const;

const KEYWORDS: Record<(typeof AUTO_TEMPLATE_ORDER)[number], string[]> = {
  dynamic: [
    "科学",
    "探索",
    "自然",
    "观察",
    "发现",
    "植物",
    "动物",
    "实验",
    "季节",
    "天气",
    "环境",
    "昆虫",
    "宇宙",
    "生物",
    "种子",
    "叶子",
    "花朵",
  ],
  modern: [
    "绘本",
    "故事",
    "童话",
    "阅读",
    "语言",
    "讲述",
    "情绪",
    "情感",
    "角色",
    "睡前",
  ],
  swift: [
    "游戏",
    "互动",
    "猜一猜",
    "找一找",
    "说一说",
    "配对",
    "闯关",
    "选择",
    "问答",
    "律动",
  ],
  momentum: [
    "活动",
    "主题",
    "分享",
    "家园",
    "亲子",
    "节日",
    "手工",
    "艺术",
    "音乐",
    "社会",
    "健康",
    "运动",
  ],
  standard: [],
};

function searchableText(
  presentation: Presentation,
  outline: PresentationOutline,
) {
  return [
    presentation.title ?? "",
    presentation.content ?? "",
    ...outline.slides.map((slide) => slide.content ?? ""),
  ]
    .join("\n")
    .toLocaleLowerCase();
}

/**
 * Resolve the public "general / 自动匹配" option to one of the existing
 * kindergarten-oriented bundled templates.
 *
 * Manual selections never pass through this function: callers should invoke it
 * only when the selected template is AUTO_TEMPLATE_ID. The result is
 * deterministic so the same reviewed outline does not unexpectedly change
 * visual families between retries.
 */
export function resolveAutoTemplateId(
  presentation: Presentation,
  outline: PresentationOutline,
  templates: TemplateItem[],
): string {
  const available = new Set(templates.map((item) => item.id));
  const text = searchableText(presentation, outline);
  const scores = new Map<string, number>();

  for (const templateId of AUTO_TEMPLATE_ORDER) {
    if (!available.has(templateId)) continue;
    scores.set(templateId, templateId === "standard" ? 1 : 0);
    for (const keyword of KEYWORDS[templateId]) {
      if (text.includes(keyword.toLocaleLowerCase())) {
        scores.set(templateId, (scores.get(templateId) ?? 0) + 2);
      }
    }
  }

  let bestId: string | null = null;
  let bestScore = Number.NEGATIVE_INFINITY;
  for (const templateId of AUTO_TEMPLATE_ORDER) {
    const score = scores.get(templateId);
    if (score === undefined) continue;
    if (score > bestScore) {
      bestId = templateId;
      bestScore = score;
    }
  }

  // Keep the existing behaviour as the final compatibility fallback when the
  // expected bundled templates are not present in the current deployment.
  return bestId ?? AUTO_TEMPLATE_ID;
}
