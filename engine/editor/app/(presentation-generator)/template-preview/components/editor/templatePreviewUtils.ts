import type { TemplateV2Layout } from "@/components/slide-editor/importing/template-v2-import";

export type UnknownRecord = Record<string, unknown>;
export type TemplateSavePayload = UnknownRecord & {
  id: string;
  name: string;
  layout_count: number;
  layouts: unknown;
};
export type PanelMode =
  | "blocks"
  | "texts"
  | "charts"
  | "tables"
  | "images"
  | "elements"
  | "schema"
  | "layouts";
export type Density = "" | "Low" | "Medium" | "High";
export type LayoutPath = Array<string | number>;
export type HistoryCommand = { action: "undo" | "redo"; token: number };
export type HistoryAvailability = { canUndo: boolean; canRedo: boolean };

export type CreatedTemplateLayout = {
  index: number;
  layout: TemplateV2Layout;
};

export type SchemaField = {
  decorative: boolean;
  elementType: string;
  id: string;
  label: string;
  type: "text" | "text-list" | "image" | "element";
  path: LayoutPath;
  value: string;
  minChars?: number;
  maxChars?: number;
};

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readString(value: unknown) {
  return typeof value === "string" ? value : "";
}

function readNumber(value: unknown) {
  return typeof value === "number" && Number.isFinite(value)
    ? value
    : undefined;
}

function readArray(value: unknown) {
  return Array.isArray(value) ? value : [];
}

export function cloneLayout<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

type ContentDensity = Exclude<Density, "">;

const MAX_PREVIEW_ITEMS = 24;
const MAX_PREVIEW_TEXT_LENGTH = 10_000;
const DENSE_CONTENT_SENTENCES = [
  "团队需要清晰背景、可衡量进展，以及每个决策对应的下一步行动。",
  "这段加长示例文案用于观察字段在高密度内容下的换行、对齐与溢出表现。",
  "可用此模拟内容检查间距、层次与整页视觉平衡，便于导出前发现问题。",
  "每句都贴近真实演示稿语气，让较长文本块更接近生成后的呈现效果。",
  "预览会尽量填满字段字数上限，提前暴露版式压力。",
];

/**
 * Build a density preview without changing the layout that will be saved.
 * Low and High mirror the reference editor's min/max schema previews, while
 * Medium uses the midpoint between the configured bounds.
 */
export function applyTemplateContentDensity(
  layout: TemplateV2Layout,
  density: Density,
) {
  if (!density) return layout;

  const nextLayout = cloneLayout(layout);
  const layoutRecord = nextLayout as UnknownRecord;

  applyDensityToElements(layoutRecord.elements, density);
  readArray(layoutRecord.components).forEach((component) => {
    if (isRecord(component)) {
      applyDensityToElements(component.elements, density);
    }
  });

  return nextLayout;
}

/**
 * Density content is synthetic, so only copy canvas/layout edits back into the
 * stored layout while a density preview is active.
 */
export function mergeDensityPreviewCanvasEdits(
  storedLayout: TemplateV2Layout,
  editedPreviewLayout: TemplateV2Layout,
) {
  const nextLayout = cloneLayout(storedLayout);
  const target = nextLayout as UnknownRecord;
  const source = editedPreviewLayout as UnknownRecord;

  syncComponentCanvasFields(target.components, source.components);
  syncElementCanvasFields(target.elements, source.elements);
  return nextLayout;
}

function applyDensityToElements(elements: unknown, density: ContentDensity) {
  readArray(elements).forEach((element) => {
    if (isRecord(element)) applyDensityToElement(element, density);
  });
}

function applyDensityToElement(
  element: UnknownRecord,
  density: ContentDensity,
) {
  const type = readString(element.type);
  const name = readString(element.name).trim();
  const isEditableContent = element.decorative === false && Boolean(name);

  if (isEditableContent && type === "text") {
    const targetLength = densityTextLength(element, density);
    setElementRunsText(element, exactDensityText(name, targetLength, density));
  } else if (isEditableContent && type === "text-list") {
    applyTextListDensity(element, name, density);
  } else if (isEditableContent && type === "image") {
    const promptLabel =
      element.is_icon === true ? `${name} 图标` : `${name} 图片`;
    element.prompt = exactDensityText(
      promptLabel,
      densityTextLength({}, density),
      density,
    );
  } else if (isEditableContent && type === "table") {
    applyTableDensity(element, name, density);
  }

  resizeRepeatedChildren(element, density);

  if (isRecord(element.child)) {
    applyDensityToElement(element.child, density);
  }
  applyDensityToElements(element.children, density);
  applyDensityToElements(element.elements, density);
}

function applyTextListDensity(
  element: UnknownRecord,
  name: string,
  density: ContentDensity,
) {
  const itemCount = densityCount(
    element.min_items,
    element.max_items,
    density,
  );
  const currentItems = readArray(element.items);
  const itemLength = densityLength(
    element.min_item_length,
    element.max_item_length,
    density,
  );

  element.items = Array.from({ length: itemCount }, (_, index) => {
    const source =
      currentItems[index] ??
      currentItems[currentItems.length - 1] ??
      currentItems[0] ??
      [{ text: "" }];
    const nextItem = cloneLayout(source);
    setRunsTextOnValue(
      nextItem,
      exactDensityText(`${name} ${index + 1}`, itemLength, density),
    );
    return nextItem;
  });
}

function applyTableDensity(
  element: UnknownRecord,
  name: string,
  density: ContentDensity,
) {
  const columnCount = densityCount(
    element.min_columns,
    element.max_columns,
    density,
  );
  const rowCount = densityCount(
    element.min_rows,
    element.max_rows,
    density,
  );
  const cellTextLength = densityTextLength({}, density);
  const currentColumns = readArray(element.columns);
  const currentRows = readArray(element.rows);

  element.columns = Array.from({ length: columnCount }, (_, columnIndex) =>
    cellWithText(
      currentColumns[columnIndex] ??
        currentColumns[currentColumns.length - 1],
      exactDensityText(
        `${name} 列 ${columnIndex + 1}`,
        cellTextLength,
        density,
      ),
    ),
  );
  element.rows = Array.from({ length: rowCount }, (_, rowIndex) => {
    const sourceRow = readArray(
      currentRows[rowIndex] ?? currentRows[currentRows.length - 1],
    );
    return Array.from({ length: columnCount }, (_, columnIndex) =>
      cellWithText(
        sourceRow[columnIndex] ??
          sourceRow[sourceRow.length - 1] ??
          currentColumns[columnIndex],
        exactDensityText(
          `${name} 第 ${rowIndex + 1} 行第 ${columnIndex + 1} 列`,
          cellTextLength,
          density,
        ),
      ),
    );
  });
}

function resizeRepeatedChildren(
  element: UnknownRecord,
  density: ContentDensity,
) {
  const type = readString(element.type);
  if (type !== "flex" && type !== "grid") return;

  const children = readArray(element.children);
  const minChildren = readNumber(element.min_children);
  const maxChildren = readNumber(element.max_children);
  if (minChildren === undefined && maxChildren === undefined) return;

  const targetCount = densityCount(minChildren, maxChildren, density);
  if (targetCount === children.length) return;
  if (!childrenCanRepeat(children, maxChildren)) return;

  const nextChildren = children.slice(0, targetCount).map(cloneLayout);
  while (nextChildren.length < targetCount) {
    const index = nextChildren.length;
    const source =
      children[index] ??
      children[children.length - 1] ??
      children[0] ??
      { type: "group", children: [] };
    const nextChild = cloneLayout(source);
    normalizeRepeatedNames(nextChild, index);
    nextChildren.push(nextChild);
  }
  element.children = nextChildren;
}

function childrenCanRepeat(children: unknown[], maxChildren?: number) {
  if (children.length === 0) return false;
  if (children.length === 1) {
    return maxChildren !== undefined && maxChildren > 1;
  }

  return (["none", "numeric"] as const).some((strategy) => {
    const signatures = children.map((child) =>
      JSON.stringify(contentShape(child, strategy)),
    );
    return (
      signatures[0] !== "null" &&
      signatures.every((signature) => signature === signatures[0])
    );
  });
}

function contentShape(
  value: unknown,
  nameStrategy: "none" | "numeric",
): unknown {
  if (!isRecord(value)) return null;

  const type = readString(value.type);
  const name = normalizedContentName(readString(value.name), nameStrategy);
  if (
    value.decorative === false &&
    name &&
    ["text", "image", "text-list", "table", "chart", "infographic"].includes(
      type,
    )
  ) {
    return {
      type,
      name,
      min_length: value.min_length,
      max_length: value.max_length,
      min_items: value.min_items,
      max_items: value.max_items,
      min_item_length: value.min_item_length,
      max_item_length: value.max_item_length,
    };
  }

  const childShape = contentShape(value.child, nameStrategy);
  const childrenShapes = readArray(value.children)
    .map((child) => contentShape(child, nameStrategy))
    .filter((shape) => shape !== null);
  const elementShapes = readArray(value.elements)
    .map((child) => contentShape(child, nameStrategy))
    .filter((shape) => shape !== null);

  if (!childShape && childrenShapes.length === 0 && elementShapes.length === 0) {
    return null;
  }
  return {
    type,
    name: name || undefined,
    child: childShape || undefined,
    children: childrenShapes.length ? childrenShapes : undefined,
    elements: elementShapes.length ? elementShapes : undefined,
  };
}

function normalizedContentName(
  name: string,
  strategy: "none" | "numeric",
) {
  const trimmedName = name.trim();
  if (strategy === "none") return trimmedName;
  return trimmedName.replace(/_\d+(?=_|$)/, "").replace(/_\d+$/, "");
}

function normalizeRepeatedNames(value: unknown, index: number): void {
  if (Array.isArray(value)) {
    value.forEach((item) => normalizeRepeatedNames(item, index));
    return;
  }
  if (!isRecord(value)) return;

  if (typeof value.name === "string") {
    value.name = value.name
      .replace(/_\d+(?=_|$)/, `_${index + 1}`)
      .replace(/_\d+$/, `_${index + 1}`);
  }
  Object.values(value).forEach((item) => normalizeRepeatedNames(item, index));
}

function densityTextLength(
  schema: UnknownRecord,
  density: ContentDensity,
) {
  return densityLength(schema.min_length, schema.max_length, density);
}

function densityLength(
  minValue: unknown,
  maxValue: unknown,
  density: ContentDensity,
) {
  const minLength = nonNegativeInteger(minValue, 8);
  const maxLength = Math.max(
    minLength,
    nonNegativeInteger(maxValue, Math.max(160, minLength)),
  );
  return Math.min(
    MAX_PREVIEW_TEXT_LENGTH,
    densityValue(minLength, maxLength, density),
  );
}

function densityCount(
  minValue: unknown,
  maxValue: unknown,
  density: ContentDensity,
) {
  const minCount = nonNegativeInteger(minValue, 1);
  const maxCount = Math.max(
    minCount,
    nonNegativeInteger(maxValue, Math.max(2, minCount)),
  );
  return Math.min(
    MAX_PREVIEW_ITEMS,
    densityValue(minCount, maxCount, density),
  );
}

function densityValue(
  minValue: number,
  maxValue: number,
  density: ContentDensity,
) {
  if (density === "Low") return minValue;
  if (density === "High") return maxValue;
  return Math.round((minValue + maxValue) / 2);
}

function nonNegativeInteger(value: unknown, fallback: number) {
  const number = readNumber(value);
  return Math.max(0, Math.floor(number ?? fallback));
}

function exactDensityText(
  label: string,
  targetLength: number,
  density: ContentDensity,
) {
  if (targetLength <= 0) return "";

  const title =
    localizeSchemaLabel(
      label.replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim() || "内容",
    ) || "内容";
  const candidates =
    density === "Low"
      ? [
          `${title}。`,
          `${title}已准备就绪。`,
          `${title}表达清晰。`,
          "下一步明确。",
          "团队已有清晰的下一步。",
          "方案已可审阅。",
          "本段内容足以检查间距与排版。",
        ]
      : [
          `${title}概要展示稳定进展，并给出清晰下一步。`,
          ...DENSE_CONTENT_SENTENCES,
          "相关方可以比较方案、识别风险，并对齐最优路径。",
          "最终文案保持可复现，同时贴近真实演示稿语气。",
        ];
  const seed = candidates.join("").replace(/\s+/g, "").trim();
  if (seed.length >= targetLength) return seed.slice(0, targetLength);

  const filler = `${DENSE_CONTENT_SENTENCES.join("")}${seed}`;
  let text = seed;
  while (text.length < targetLength) text += filler;
  return text.slice(0, targetLength);
}

function setElementRunsText(element: UnknownRecord, text: string) {
  const runs = readArray(element.runs).filter(isRecord);
  if (runs.length === 0) {
    element.runs = [{ text }];
    return;
  }
  element.runs = runs.map((run, index) => ({
    ...run,
    text: index === 0 ? text : "",
  }));
}

function setRunsTextOnValue(value: unknown, text: string) {
  if (Array.isArray(value)) {
    if (value.length === 0) value.push({ text });
    value.forEach((run, index) => {
      if (isRecord(run)) run.text = index === 0 ? text : "";
    });
    return;
  }

  if (!isRecord(value)) return;
  if (!Array.isArray(value.runs)) value.runs = [{ text }];
  setElementRunsText(value, text);
}

function cellWithText(source: unknown, text: string) {
  const cell = cloneLayout(isRecord(source) ? source : { runs: [{ text: "" }] });
  setElementRunsText(cell, text);
  return cell;
}

function syncComponentCanvasFields(
  targetComponents: unknown,
  sourceComponents: unknown,
) {
  if (!Array.isArray(targetComponents) || !Array.isArray(sourceComponents)) {
    return;
  }

  targetComponents.forEach((targetComponent, index) => {
    const sourceComponent = sourceComponents[index];
    if (!isRecord(targetComponent) || !isRecord(sourceComponent)) return;
    syncObjectFields(targetComponent, sourceComponent, [
      "position",
      "size",
      "rotation",
    ]);
    syncElementCanvasFields(targetComponent.elements, sourceComponent.elements);
  });
}

function syncElementCanvasFields(
  targetElements: unknown,
  sourceElements: unknown,
) {
  if (!Array.isArray(targetElements) || !Array.isArray(sourceElements)) return;

  targetElements.forEach((targetElement, index) => {
    const sourceElement = sourceElements[index];
    if (!isRecord(targetElement) || !isRecord(sourceElement)) return;
    syncObjectFields(targetElement, sourceElement, [
      "position",
      "size",
      "rotation",
      "points",
      "__presenton_manual_position",
    ]);
    syncElementCanvasFields(targetElement.children, sourceElement.children);
    syncElementCanvasFields(targetElement.elements, sourceElement.elements);
    if (isRecord(targetElement.child) && isRecord(sourceElement.child)) {
      syncElementCanvasFields([targetElement.child], [sourceElement.child]);
    }
  });
}

function syncObjectFields(
  target: UnknownRecord,
  source: UnknownRecord,
  fields: string[],
) {
  fields.forEach((field) => {
    if (field in source) target[field] = cloneLayout(source[field]);
    else delete target[field];
  });
}

function withEditedLayouts(
  currentLayoutsValue: unknown,
  layouts: TemplateV2Layout[],
) {
  if (Array.isArray(currentLayoutsValue)) {
    return layouts;
  }

  if (isRecord(currentLayoutsValue)) {
    return {
      ...currentLayoutsValue,
      layouts,
    };
  }

  return { layouts };
}

export function buildTemplateSavePayload({
  layouts,
  name,
  targetTemplateId,
  template,
}: {
  layouts: TemplateV2Layout[];
  name: string;
  targetTemplateId: string;
  template: unknown;
}): TemplateSavePayload {
  const templateRecord = isRecord(template) ? template : {};
  const payload = cloneLayout(templateRecord);

  payload.id = targetTemplateId;
  payload.name = name;
  payload.layout_count = layouts.length;
  payload.layouts = withEditedLayouts(templateRecord.layouts, layouts);

  return payload as TemplateSavePayload;
}

export function hashKey(value: string) {
  let hash = 0;
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash * 31 + value.charCodeAt(i)) | 0;
  }
  return Math.abs(hash).toString(36);
}

function humanize(value: string) {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

const WORD_TRANSLATIONS: Record<string, string> = {
  section: "章节",
  heading: "标题",
  theme: "主题",
  statement: "陈述",
  supporting: "辅助",
  copy: "文案",
  presenter: "主讲人",
  date: "日期",
  field: "字段",
  fields: "字段",
  header: "页眉",
  title: "标题",
  titles: "标题",
  subtitle: "副标题",
  illustrated: "插画",
  illustration: "插画",
  scene: "场景",
  scenes: "场景",
  detail: "细节",
  details: "细节",
  image: "图片",
  images: "图片",
  icon: "图标",
  icons: "图标",
  text: "文本",
  body: "正文",
  description: "说明",
  content: "内容",
  contents: "内容",
  caption: "说明文字",
  label: "标签",
  labels: "标签",
  metric: "指标",
  callout: "要点卡片",
  chart: "图表",
  table: "表格",
  background: "背景",
  backdrop: "背景",
  footer: "页脚",
  logo: "标志",
  slide: "页面",
  main: "主",
  bullet: "要点",
  bullets: "要点列表",
  card: "卡片",
  display: "展示",
  entry: "条目",
  entries: "条目",
  number: "序号",
  num: "序号",
  index: "序号",
  agenda: "议程",
  item: "项",
  items: "项",
  woodland: "林地",
  forest: "森林",
  earth: "地球",
  day: "日",
  event: "活动",
  events: "活动",
  cover: "封面",
  story: "故事",
  panel: "图文页",
  panels: "图文页",
  layout: "布局",
  layouts: "布局",
  intro: "引入",
  overview: "概览",
  summary: "总结",
  process: "流程",
  step: "步骤",
  steps: "步骤",
  activity: "活动",
  craft: "手工",
  nature: "自然",
  themed: "主题",
  animal: "动物",
  ocean: "海洋",
  garden: "花园",
  classroom: "课堂",
  parent: "家长",
  meeting: "会议",
  closing: "结尾",
  opening: "开场",
  directory: "目录",
  board: "看板",
  framed: "框式",
  frame: "框",
  flexible: "弹性",
  bilingual: "中英",
  grid: "网格",
  editorial: "编辑式",
  educational: "教学",
  environment: "环境",
  environmental: "环境",
  central: "居中",
  centered: "居中",
  rounded: "圆角",
  corner: "角",
  corners: "圆角",
  full: "全幅",
  bleed: "铺满",
  stack: "组合",
  decorative: "装饰",
  decor: "装饰",
  two: "双",
  column: "栏",
  columns: "栏",
  row: "行",
  rows: "行",
  left: "左侧",
  right: "右侧",
  top: "顶部",
  bottom: "底部",
  center: "居中",
  list: "列表",
  info: "信息",
  note: "备注",
  notes: "备注",
  tip: "提示",
  tips: "提示",
  quote: "引言",
  name: "名称",
  author: "作者",
  teacher: "教师",
  student: "学生",
  kids: "幼儿",
  child: "幼儿",
  children: "幼儿",
  preschool: "学前",
  kindergarten: "幼儿园",
  season: "季节",
  spring: "春天",
  summer: "夏天",
  autumn: "秋天",
  winter: "冬天",
  plant: "植物",
  water: "水",
  land: "陆地",
  sky: "天空",
  sun: "太阳",
  moon: "月亮",
  star: "星星",
  tree: "树",
  flower: "花",
  leaf: "叶子",
  bird: "鸟",
  fish: "鱼",
  octopus: "章鱼",
  sea: "海",
  beach: "沙滩",
  mountain: "山",
  park: "公园",
  home: "家园",
  family: "家庭",
  friend: "朋友",
  share: "分享",
  discuss: "讨论",
  observe: "观察",
  create: "创作",
  make: "制作",
  play: "游戏",
  learn: "学习",
  teach: "教学",
  guide: "引导",
  goal: "目标",
  result: "结果",
  next: "下一步",
  previous: "上一步",
  blank: "空白",
  empty: "空白",
  photo: "照片",
  picture: "图片",
  graphic: "图形",
  shape: "形状",
  vector: "矢量",
  group: "编组",
  container: "容器",
  flex: "弹性",
  of: "",
  the: "",
  a: "",
  an: "",
  to: "",
  for: "",
  in: "",
  on: "",
  at: "",
  by: "",
  or: "",
  and: "",
  with: "",
  from: "",
  into: "",
  over: "",
  under: "",
  across: "",
  around: "",
  about: "",
  as: "",
};

const PHRASE_TRANSLATIONS: Array<[string, string]> = [
  ["illustrated woodland directory layout", "插画式林地目录布局"],
  ["illustrated woodland directory", "插画式林地目录"],
  ["nature-themed", "自然主题"],
  ["nature themed", "自然主题"],
  ["full-bleed", "全幅"],
  ["full bleed", "全幅"],
  ["illustrated event cover layout", "插画活动封面布局"],
  ["illustrated event cover", "插画活动封面"],
  ["woodland directory board", "林地目录看板"],
  ["directory board", "目录看板"],
  ["framed title", "框式标题"],
  ["flexible grid", "弹性网格"],
  ["bilingual agenda entries", "中英议程条目"],
  ["bilingual agenda", "中英议程"],
  ["agenda entries", "议程条目"],
  ["editorial panel", "编辑式图文页"],
  ["educational panel", "教学图文页"],
  ["environmental panel", "环境图文页"],
  ["central panel", "居中图文页"],
  ["closing panel", "结尾图文页"],
  ["opening panel", "开场图文页"],
  ["story panel", "故事图文页"],
  ["section heading", "章节标题"],
  ["theme statement", "主题陈述"],
  ["supporting copy", "辅助文案"],
  ["presenter field", "主讲人"],
  ["date field", "日期"],
  ["header title", "页眉标题"],
  ["illustrated scene", "插画场景"],
  ["illustrated backdrop", "插画背景"],
  ["detail fields", "细节字段"],
  ["entry number", "条目序号"],
  ["entry title", "条目标题"],
  ["entry subtitle", "条目副标题"],
  ["display title", "展示标题"],
  ["agenda entry", "议程条目"],
  ["agenda entries", "议程条目"],
  ["slide title", "页面标题"],
  ["main title", "主标题"],
  ["main heading", "主标题"],
  ["body text", "正文"],
  ["supporting text", "辅助文字"],
  ["card title", "卡片标题"],
  ["card body", "卡片正文"],
  ["text stack", "文字组合"],
  ["rounded corners", "圆角"],
  ["rounded corner", "圆角"],
  ["blank slide layout", "空白页布局"],
  ["blank slide", "空白页"],
  ["full slide rectangle", "整页矩形"],
  ["full-slide rectangle", "整页矩形"],
];

function hasLatin(value: string) {
  return /[A-Za-z]/.test(value);
}

function hasChinese(value: string) {
  return /[\u4e00-\u9fff]/.test(value);
}

function tokenizeForTranslation(value: string) {
  return value
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/([A-Za-z])([\u4e00-\u9fff])/g, "$1 $2")
    .replace(/([\u4e00-\u9fff])([A-Za-z])/g, "$1 $2")
    .replace(/[_./\\-]+/g, " ")
    .replace(/[^\w\u4e00-\u9fff\s，。；、]+/g, " ")
    .split(/\s+/)
    .map((token) => token.trim())
    .filter(Boolean);
}

function translateToken(token: string) {
  if (!token) return "";
  if (hasChinese(token) && !hasLatin(token)) return token;
  if (/^\d+$/.test(token)) return token;
  if (/^[，。；、]+$/.test(token)) return token;

  const mixedParts = token.match(/[\u4e00-\u9fff]+|[A-Za-z0-9]+|[，。；、]+/g) ?? [
    token,
  ];
  return mixedParts
    .map((part) => {
      if (hasChinese(part) && !hasLatin(part)) return part;
      if (/^[，。；、]+$/.test(part)) return part;
      if (/^\d+$/.test(part)) return part;
      const key = part.toLowerCase();
      if (Object.prototype.hasOwnProperty.call(WORD_TRANSLATIONS, key)) {
        return WORD_TRANSLATIONS[key];
      }
      return "";
    })
    .join("");
}

function applyPhraseTranslations(value: string) {
  let next = value;
  const phrases = [...PHRASE_TRANSLATIONS].sort(
    (left, right) => right[0].length - left[0].length,
  );
  for (const [phrase, translation] of phrases) {
    const pattern = new RegExp(
      phrase.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\s+/g, "[\\s_-]+"),
      "gi",
    );
    next = next.replace(pattern, ` ${translation}，`);
  }
  return next;
}

function finalizeLocalizedText(value: string) {
  return value
    .replace(/[A-Za-z]+/g, "")
    .replace(/\s+/g, "")
    .replace(/式与/g, "式")
    .replace(/与与+/g, "与")
    .replace(/，+/g, "，")
    .replace(/^[与，。；、]+|[与，。；、]+$/g, "")
    .replace(/([，。；、])[与]+/g, "$1")
    .replace(/与([，。；、])/g, "$1")
    .trim();
}

function translateEnglishText(value: string) {
  const raw = value.trim();
  if (!raw) return "";
  if (!hasLatin(raw)) return raw;

  // Repair earlier broken replacements like "woodl与directory"
  const repaired = raw.replace(/[A-Za-z]{2,}与(?=[A-Za-z\u4e00-\u9fff])/g, "");

  const withPhrases = applyPhraseTranslations(repaired);
  const translated = tokenizeForTranslation(withPhrases)
    .map(translateToken)
    .filter(Boolean)
    .join("");

  return finalizeLocalizedText(translated);
}

export function localizeSchemaLabel(label: string) {
  const raw = label.trim();
  if (!raw) return raw;
  if (!hasLatin(raw)) return raw;

  const translated = translateEnglishText(raw);
  if (translated) return translated;

  const fallback = humanize(raw);
  return translateEnglishText(fallback) || "字段";
}

export function localizeLayoutDescription(description: string) {
  const raw = description.trim();
  if (!raw) return raw;
  if (!hasLatin(raw)) return raw;

  const translated = translateEnglishText(raw);
  return translated || "模板页面布局";
}

export function localizeLayoutDisplayName(
  id: string,
  description: string,
  index: number,
) {
  const pagePrefix = `第 ${index + 1} 页`;
  const fromDescription = localizeLayoutDescription(description)
    .split(/[，。；、]/)[0]
    ?.trim();
  if (fromDescription && !hasLatin(fromDescription)) {
    const short =
      fromDescription.length > 16
        ? `${fromDescription.slice(0, 16)}…`
        : fromDescription;
    return `${pagePrefix} · ${short}`;
  }

  const fromId = localizeSchemaLabel(id.replace(/_\d+$/g, ""));
  if (fromId && !hasLatin(fromId) && fromId !== "字段") {
    return `${pagePrefix} · ${fromId}`;
  }

  return pagePrefix;
}

export function readLayoutId(layout: TemplateV2Layout, index: number) {
  const id = readString((layout as UnknownRecord).id).trim();
  return id || `slide-${index + 1}`;
}

export function readLayoutIdValue(layout: TemplateV2Layout, index: number) {
  const layoutRecord = layout as UnknownRecord;
  if (Object.prototype.hasOwnProperty.call(layoutRecord, "id")) {
    return readString(layoutRecord.id);
  }

  return readLayoutId(layout, index);
}

export function readLayoutDescription(layout: TemplateV2Layout) {
  return readString((layout as UnknownRecord).description);
}

export function updateLayoutMetadata(
  layout: TemplateV2Layout,
  field: "id" | "description",
  value: string,
) {
  const nextLayout = cloneLayout(layout) as UnknownRecord;
  nextLayout[field] = value;

  return nextLayout as TemplateV2Layout;
}

function schemaLabelForElement(
  element: UnknownRecord,
  fallback: string,
  parentLabel?: string,
) {
  const label =
    readString(element.component_slot) ||
    readString(element.name) ||
    readString(element.component_description) ||
    parentLabel ||
    fallback;
  return localizeSchemaLabel(humanize(label));
}

function textRunsToString(runs: unknown) {
  return readArray(runs)
    .map((run) => (isRecord(run) ? readString(run.text) : ""))
    .join("");
}

function textListItemsToString(items: unknown) {
  return readArray(items)
    .map((item) => textRunsToString(item))
    .filter((line) => line.trim().length > 0)
    .join("\n");
}

export function collectSchemaFields(layout: TemplateV2Layout) {
  const fields: SchemaField[] = [];

  const addElement = (
    element: unknown,
    path: LayoutPath,
    parentLabel?: string,
  ) => {
    if (!isRecord(element)) return;

    const type = readString(element.type);
    const decorative = element.decorative !== false;
    const label = schemaLabelForElement(
      element,
      `${type || "字段"} ${fields.length + 1}`,
      parentLabel,
    );

    if (type === "text") {
      const value = textRunsToString(element.runs);
      if (value || label) {
        fields.push({
          decorative,
          elementType: type,
          id: path.join("."),
          label,
          type: "text",
          path,
          value,
          minChars: readNumber(element.min_length),
          maxChars: readNumber(element.max_length),
        });
      }
    }

    if (type === "text-list") {
      const value = textListItemsToString(element.items);
      if (value || label) {
        fields.push({
          decorative,
          elementType: type,
          id: path.join("."),
          label,
          type: "text-list",
          path,
          value,
          minChars: readNumber(element.min_item_length),
          maxChars: readNumber(element.max_item_length),
        });
      }
    }

    if (type === "image") {
      fields.push({
        decorative,
        elementType: element.is_icon === true ? "icon" : type,
        id: path.join("."),
        label,
        type: "image",
        path,
        value: readString(element.data) || readString(element.prompt),
      });
    }

    if (type && type !== "text" && type !== "text-list" && type !== "image") {
      fields.push({
        decorative,
        elementType: type,
        id: path.join("."),
        label,
        type: "element",
        path,
        value: "",
      });
    }

    const childLabel =
      readString(element.component_slot) ||
      readString(element.name) ||
      parentLabel;

    if (isRecord(element.child)) {
      addElement(element.child, [...path, "child"], childLabel);
    }

    readArray(element.children).forEach((child, childIndex) => {
      addElement(child, [...path, "children", childIndex], childLabel);
    });

    readArray(element.elements).forEach((child, childIndex) => {
      addElement(child, [...path, "elements", childIndex], childLabel);
    });
  };

  const layoutRecord = layout as UnknownRecord;

  readArray(layoutRecord.elements).forEach((element, elementIndex) => {
    addElement(element, ["elements", elementIndex]);
  });

  readArray(layoutRecord.components).forEach((component, componentIndex) => {
    if (!isRecord(component)) return;
    const componentLabel =
      readString(component.component_slot) ||
      readString(component.id) ||
      readString(component.description);

    readArray(component.elements).forEach((element, elementIndex) => {
      addElement(
        element,
        ["components", componentIndex, "elements", elementIndex],
        componentLabel,
      );
    });
  });

  return fields;
}

function recordAtPath(root: unknown, path: LayoutPath) {
  let current: unknown = root;
  for (const segment of path) {
    if (typeof segment === "number") {
      if (!Array.isArray(current)) return null;
      current = current[segment];
      continue;
    }
    if (!isRecord(current)) return null;
    current = current[segment];
  }
  return isRecord(current) ? current : null;
}

function updateTextRuns(element: UnknownRecord, value: string) {
  const runs = readArray(element.runs).filter(isRecord);
  const firstRun = runs[0] ?? {};
  element.runs = [{ ...firstRun, text: value }];
}

function updateTextListItems(element: UnknownRecord, value: string) {
  const currentItems = readArray(element.items);
  const firstItem = readArray(currentItems[0]).filter(isRecord);
  const firstRun = firstItem[0] ?? {};
  const lines = value.split(/\r?\n/);
  element.items = lines.map((line) => [{ ...firstRun, text: line }]);
}

export function updateLayoutSchemaField(
  layout: TemplateV2Layout,
  field: SchemaField,
  value: string,
) {
  if (field.decorative) return layout;

  const nextLayout = cloneLayout(layout);
  const element = recordAtPath(nextLayout, field.path);
  if (!element) return layout;

  if (field.type === "text") {
    updateTextRuns(element, value);
  } else if (field.type === "text-list") {
    updateTextListItems(element, value);
  } else if (field.type === "image") {
    element.data = value;
  } else {
    return layout;
  }

  return nextLayout;
}

export function updateLayoutSchemaConstraint(
  layout: TemplateV2Layout,
  field: SchemaField,
  constraint: "min" | "max",
  value: string,
) {
  if (field.decorative) return layout;

  const nextLayout = cloneLayout(layout);
  const element = recordAtPath(nextLayout, field.path);
  if (
    !element ||
    field.type === "image" ||
    field.type === "element"
  ) {
    return layout;
  }

  const numericValue = value.trim() === "" ? null : Number.parseInt(value, 10);
  const key =
    field.type === "text-list"
      ? constraint === "min"
        ? "min_item_length"
        : "max_item_length"
      : constraint === "min"
        ? "min_length"
        : "max_length";

  if (numericValue === null || !Number.isFinite(numericValue)) {
    delete element[key];
  } else {
    element[key] = Math.max(0, numericValue);
  }

  return nextLayout;
}

export function updateLayoutSchemaDecoration(
  layout: TemplateV2Layout,
  field: SchemaField,
  decorative: boolean,
) {
  const nextLayout = cloneLayout(layout);
  const element = recordAtPath(nextLayout, field.path);
  if (!element) return layout;

  element.decorative = decorative;
  return nextLayout;
}

export function extractCreatedLayouts(value: unknown): CreatedTemplateLayout[] {
  if (!isRecord(value)) return [];
  const layoutsValue = value.layouts;
  if (!Array.isArray(layoutsValue)) return [];

  return layoutsValue.flatMap((item) => {
    if (!isRecord(item)) return [];
    const index = item.index;
    if (!Number.isInteger(index) || !item.layout) return [];
    return [
      {
        index: index as number,
        layout: item.layout as TemplateV2Layout,
      },
    ];
  });
}
