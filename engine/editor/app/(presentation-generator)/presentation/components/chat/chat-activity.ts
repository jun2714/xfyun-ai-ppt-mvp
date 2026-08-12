import type { ChatStreamTrace } from "../../../services/api/chat";
import type { AssistantActivity } from "./chat-types";

const TOOL_LABELS: Record<string, string> = {
  addOutline: "添加大纲页",
  updateOutline: "更新大纲页",
  deleteOutline: "删除大纲页",
  addNewSlide: "添加空白页",
  addNewSlideLayout: "按布局添加页面",
  getAvailableLayouts: "查找可用布局",
  getTemplateSummary: "读取模板信息",
  readSourceDocuments: "读取源文档",
  searchSlide: "搜索页面",
  getSlideAtIndex: "读取页面",
  saveSlide: "保存页面",
  updateSlide: "更新页面",
  deleteSlide: "删除页面",
  addElement: "添加元素",
  updateElement: "更新元素",
  deleteElement: "删除元素",
  addComponent: "添加组件",
  createComponent: "创建组件",
  updateComponent: "更新组件",
  deleteComponent: "删除组件",
  getPresentationTheme: "读取主题",
  setPresentationTheme: "应用主题",
  generateAssets: "生成素材",
};

export const MUTATING_TOOLS = new Set([
  "addOutline",
  "updateOutline",
  "deleteOutline",
  "addNewSlide",
  "addNewSlideLayout",
  "saveSlide",
  "updateSlide",
  "deleteSlide",
  "addElement",
  "updateElement",
  "deleteElement",
  "addComponent",
  "createComponent",
  "updateComponent",
  "deleteComponent",
  "setPresentationTheme",
]);

// Read/open traces can happen ahead of edits and would make follow mode jumpy.
export const SLIDE_FOCUS_TOOLS = new Set([
  "addNewSlide",
  "addNewSlideLayout",
  "saveSlide",
  "updateSlide",
  "deleteSlide",
  "addElement",
  "updateElement",
  "deleteElement",
  "addComponent",
  "createComponent",
  "updateComponent",
  "deleteComponent",
]);

export const SLIDE_FOCUS_STATUSES = new Set(["start"]);
export const MIN_SLIDE_FOCUS_DWELL_MS = 700;

const getToolLabel = (tool?: string) => {
  if (!tool) return "";
  return TOOL_LABELS[tool] ?? tool;
};

const localizeEnglishToolMessages = (message: string) => {
  const patterns: Array<[RegExp, (match: RegExpMatchArray) => string]> = [
    [
      /^Slide at index (\d+) was replaced successfully\.?$/i,
      (match) => `第 ${Number(match[1]) + 1} 页已成功替换。`,
    ],
    [
      /^Slide at index (\d+) was deleted successfully\.?$/i,
      (match) => `第 ${Number(match[1]) + 1} 页已成功删除。`,
    ],
    [
      /^No slide found at index (\d+)\.?$/i,
      (match) => `未找到第 ${Number(match[1]) + 1} 页。`,
    ],
    [
      /^Slide not found\.?$/i,
      () => "未找到对应页面。",
    ],
    [
      /^Presentation not found\.?$/i,
      () => "未找到演示文稿。",
    ],
    [
      /^Generated (\d+) asset\(s\)\.?$/i,
      (match) => `已生成 ${match[1]} 个素材。`,
    ],
    [
      /^New slide saved at index (\d+)\.?$/i,
      (match) => `新页面已保存到第 ${Number(match[1]) + 1} 页。`,
    ],
    [
      /^Blank slide added at index (\d+)\.?$/i,
      (match) => `已在第 ${Number(match[1]) + 1} 页添加空白页。`,
    ],
  ];

  for (const [pattern, builder] of patterns) {
    const match = message.match(pattern);
    if (match) return builder(match);
  }
  return message;
};

const humanizeTraceMessage = (message: string, tool?: string) => {
  const trimmed = message.trim();
  if (!trimmed) return "";

  const lower = trimmed.toLowerCase();
  const exactMessages: Record<string, string> = {
    "reading deck context": "正在查看演示文稿上下文",
    "reading the presentation outline": "正在读取演示大纲",
    "reading the outline draft": "正在读取大纲草稿",
    "adding an outline slide": "正在添加大纲页",
    "updating the outline slide": "正在更新大纲页",
    "deleting the outline slide": "正在删除大纲页",
    "reordering outline slides": "正在调整大纲顺序",
    "searching relevant slides": "正在搜索相关页面",
    "opening the requested slide": "正在打开目标页面",
    "checking available themes": "正在查看可用主题",
    "checking available layouts": "正在查看可用布局",
    "checking the layout schema": "正在校验页面结构",
    "generating slide assets": "正在生成图片和素材",
    "saving the slide": "正在保存页面",
    "deleting the slide": "正在删除页面",
    "applying presentation theme": "正在应用主题",
    "reading template structure": "正在读取模板结构",
    "reading source documents": "正在读取源文档",
    "opening the requested template slide": "正在打开模板页面",
    "searching template content": "正在搜索模板内容",
    "finding editable elements": "正在查找可编辑元素",
    "updating template content": "正在更新模板内容",
    "deleting the template component": "正在删除组件",
    "swapping component variant": "正在切换组件样式",
    "saving chat": "正在保存对话",
    "finalizing response": "正在整理回复",
    "adding a blank slide": "正在添加空白页",
    "adding slide from layout": "正在按布局添加页面",
    "reading template summary": "正在读取模板摘要",
    "updating the slide": "正在更新页面",
    "adding slide element": "正在添加元素",
    "updating slide element": "正在更新元素",
    "removing slide element": "正在删除元素",
    "adding slide component": "正在添加组件",
    "creating slide component": "正在创建组件",
    "updating slide component": "正在更新组件",
    "removing slide component": "正在删除组件",
  };
  if (exactMessages[lower]) return exactMessages[lower];

  if (lower.startsWith("using tools:")) {
    const toolNames = trimmed
      .slice("using tools:".length)
      .split(",")
      .map((entry) => entry.trim())
      .filter(Boolean)
      .map((entry) => getToolLabel(entry));
    return toolNames.length === 0
      ? "正在规划下一步"
      : `正在调用：${toolNames.join("、")}`;
  }
  if (lower.includes("found requested data")) {
    return tool === "getSlideAtIndex"
      ? "已找到目标页面信息"
      : "已找到所需信息";
  }

  return localizeEnglishToolMessages(trimmed);
};

export const inferStatusState = (
  status: string,
): AssistantActivity["state"] => {
  const normalized = status.trim().toLowerCase();
  if (
    [
      "preparing",
      "thinking",
      "reading",
      "searching",
      "opening",
      "generating",
      "processing",
      "finalizing",
      "saving",
      "正在",
      "读取",
      "生成",
      "保存",
      "查找",
      "更新",
      "删除",
    ].some((term) => normalized.includes(term))
  ) {
    return "running";
  }
  return "info";
};

export const isAbortError = (error: unknown) =>
  (error instanceof DOMException && error.name === "AbortError") ||
  (error instanceof Error &&
    error.message.toLowerCase().includes("aborted") &&
    error.message.toLowerCase().includes("request"));

export const stripBackendContextFromUserMessage = (rawMessage: string) => {
  const message = rawMessage ?? "";
  if (!message.startsWith("UI context:")) return message;

  const marker = "\nUser message:";
  const markerIndex = message.indexOf(marker);
  if (markerIndex === -1) return message;
  return message.slice(markerIndex + marker.length).trimStart();
};

const humanActivityForTool = (
  tool: string | undefined,
  state: "start" | "success",
) => {
  const isDone = state === "success";
  switch (tool) {
    case "searchSlide":
      return isDone ? "已找到相关内容" : "正在查找相关内容";
    case "getSlideAtIndex":
      return isDone ? "已查看该页" : "正在查看该页";
    case "addNewSlide":
    case "addNewSlideLayout":
    case "updateElement":
    case "updateComponent":
    case "addElement":
    case "addComponent":
    case "createComponent":
    case "updateSlide":
    case "saveSlide":
      return isDone ? "已应用修改" : "正在应用修改";
    case "deleteComponent":
    case "deleteElement":
    case "deleteSlide":
      return isDone ? "已删除所选内容" : "正在删除所选内容";
    case "generateAssets":
      return isDone ? "素材已准备好" : "正在生成素材";
    case "setPresentationTheme":
      return isDone ? "主题已更新" : "正在更新主题";
    default:
      return isDone ? "该步骤已完成" : "正在处理";
  }
};

export const formatTraceActivity = (
  trace: ChatStreamTrace,
): Omit<AssistantActivity, "id"> | null => {
  if (typeof trace.message === "string" && trace.message.trim().length > 0) {
    return {
      label: humanizeTraceMessage(trace.message, trace.tool),
      kind: trace.kind,
      round: trace.round,
      tool: trace.tool,
      state:
        trace.status === "error"
          ? "error"
          : trace.status === "success"
            ? "success"
            : trace.status === "ready" || trace.status === "info"
              ? "info"
              : "running",
    };
  }
  if (trace.tool && trace.status === "start") {
    return {
      label: humanActivityForTool(trace.tool, "start"),
      kind: trace.kind,
      round: trace.round,
      tool: trace.tool,
      state: "running",
    };
  }
  if (trace.tool && trace.status === "success") {
    return {
      label: humanActivityForTool(trace.tool, "success"),
      kind: trace.kind,
      round: trace.round,
      tool: trace.tool,
      state: "success",
    };
  }
  if (trace.tool && trace.status === "error") {
    return {
      label: "这一步没有完成",
      kind: trace.kind,
      round: trace.round,
      tool: trace.tool,
      state: "error",
    };
  }
  if (trace.kind === "tool_plan" && Array.isArray(trace.tools) && trace.tools.length) {
    return {
      label: "正在规划下一步",
      kind: trace.kind,
      round: trace.round,
      state: "info",
    };
  }
  return null;
};

export const readTraceSlideIndex = (trace: ChatStreamTrace) => {
  if (typeof trace.slideIndex === "number" && trace.slideIndex >= 0) {
    return trace.slideIndex;
  }
  if (typeof trace.slideNumber === "number" && trace.slideNumber > 0) {
    return trace.slideNumber - 1;
  }
  return null;
};
