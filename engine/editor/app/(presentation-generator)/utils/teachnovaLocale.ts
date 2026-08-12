import { LanguageType, ToneType, VerbosityType } from "../upload/type";

/** 内置模板展示名 / 说明（幼教向）；技术 id 仍用英文目录名 */
const TEMPLATE_DISPLAY: Record<string, { name: string; description: string }> = {
  momentum: {
    name: "活力课堂",
    description: "明亮活泼的幼教版式，适合主题教学、活动分享与家园共育演示。",
  },
  dynamic: {
    name: "探索发现",
    description: "对比鲜明、故事感强，适合科学探索、自然观察与主题探究课。",
  },
  executive: {
    name: "教研分享",
    description: "结构清晰、重点突出，适合教研汇报、培训分享与园务沟通。",
  },
  swift: {
    name: "趣味互动",
    description: "节奏轻快、视觉醒目，适合短时互动课与游戏化学习内容。",
  },
  standard: {
    name: "日常教学",
    description: "均衡通用的幼教版式，适合集体教学、区角介绍与常规课件。",
  },
  modern: {
    name: "温馨绘本",
    description: "留白舒适、排版简洁，适合绘本分享、故事讲述与情感主题。",
  },
  general: {
    name: "基础通用",
    description: "简洁干净的基础版式，适合入门课件与各类幼教演示。",
  },
};

export function localizeTemplateName(name?: string | null, id?: string | null) {
  const key = (id || name || "").trim().toLowerCase();
  if (TEMPLATE_DISPLAY[key]) return TEMPLATE_DISPLAY[key].name;
  const byName = Object.entries(TEMPLATE_DISPLAY).find(
    ([, meta]) => meta.name === name || key === meta.name.toLowerCase(),
  );
  if (byName) return byName[1].name;
  // 英文内置名回退
  const englishKey = (name || "").trim().toLowerCase();
  if (TEMPLATE_DISPLAY[englishKey]) return TEMPLATE_DISPLAY[englishKey].name;
  return name?.trim() || "未命名模板";
}

export function localizeTemplateDescription(
  description?: string | null,
  name?: string | null,
  id?: string | null,
) {
  const key = (id || name || "").trim().toLowerCase();
  if (TEMPLATE_DISPLAY[key]) return TEMPLATE_DISPLAY[key].description;
  const englishKey = (name || "").trim().toLowerCase();
  if (TEMPLATE_DISPLAY[englishKey]) return TEMPLATE_DISPLAY[englishKey].description;
  if (description && !/[A-Za-z]{4,}/.test(description)) return description;
  return description?.trim() || "适合幼儿园教学与家园共育的演示模板。";
}

const TONE_LABELS: Record<string, string> = {
  [ToneType.Default]: "默认",
  [ToneType.Casual]: "轻松",
  [ToneType.Professional]: "专业",
  [ToneType.Funny]: "幽默",
  [ToneType.Educational]: "教学",
  [ToneType.Sales_Pitch]: "推介",
};

const VERBOSITY_LABELS: Record<string, string> = {
  [VerbosityType.Concise]: "简洁",
  [VerbosityType.Standard]: "适中",
  [VerbosityType.Text_Heavy]: "详尽",
};

export function toneLabel(value: string) {
  return TONE_LABELS[value] || value;
}

export function verbosityLabel(value: string) {
  return VERBOSITY_LABELS[value] || value;
}

export function languageLabel(value: string | null | undefined) {
  if (!value) return "选择语言";
  if (value === LanguageType.ChineseSimplified || /Simplified/i.test(value)) {
    return "简体中文";
  }
  if (value === LanguageType.ChineseTraditional || /Traditional/i.test(value)) {
    return "繁体中文";
  }
  if (value === LanguageType.Auto || /^Auto/i.test(value)) return "自动";
  if (value === LanguageType.English || value === "English") return "英语";

  const localized: Record<string, string> = {
    [LanguageType.Japanese]: "日语",
    [LanguageType.Korean]: "韩语",
    [LanguageType.Spanish]: "西班牙语",
    [LanguageType.French]: "法语",
    [LanguageType.German]: "德语",
  };
  if (localized[value]) return localized[value];

  const beforeParen = value.split(" (")[0]?.trim();
  return beforeParen || value;
}

export function generationModeLabel(mode: "smart" | "standard" | string) {
  if (mode === "smart") return "智能";
  return "标准";
}
