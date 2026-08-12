import type { DragEvent } from "react";
import type { ChatAttachment } from "../../../services/api/chat";
import type {
  ChatDocumentAttachment,
  ChatEditPreview,
  ChatLayoutPreview,
  ChatLink,
} from "./chat-types";

export const createMessageId = () => {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }

  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
};

export const createChatLayoutPreviewSlide = (preview: ChatLayoutPreview) => ({
  id: `chat-layout-preview-${preview.slideIndex ?? "slide"}`,
  content: {},
  ui: preview.layout,
  layout: preview.layoutId || "chat-layout-preview",
  layout_group: "template-v2",
});

export const getPresentationSlide = (
  presentationData: unknown,
  slideIndex: number,
) => {
  if (!presentationData || typeof presentationData !== "object") return null;
  const slides = (presentationData as Record<string, unknown>).slides;
  return Array.isArray(slides) ? slides[slideIndex] ?? null : null;
};

export const getPresentationFonts = (presentationData: unknown) => {
  if (!presentationData || typeof presentationData !== "object") {
    return undefined;
  }
  return (presentationData as Record<string, unknown>).fonts;
};

export const clonePreviewSlide = (slide: unknown) => {
  if (!slide) return null;
  try {
    return structuredClone(slide);
  } catch {
    try {
      return JSON.parse(JSON.stringify(slide)) as unknown;
    } catch {
      return null;
    }
  }
};

const URL_PATTERN =
  /(https?:\/\/[^\s<>"']+\.[^\s<>"']+|www\.[^\s<>"']+\.[^\s<>"']+)/gi;
const IMAGE_READ_INTENT_PATTERN =
  /\b(read|extract|parse|analy[sz]e|summari[sz]e|ocr|text|table|chart|data|numbers?|metrics?)\b/i;
const IMAGE_EXTENSION_PATTERN = /\.(jpe?g|png|gif|bmp|tiff?|webp)$/i;
const ATTACHMENT_CONTENT_LIMIT = 2000;

export function pullLinksFromText(text: string) {
  const links: ChatLink[] = [];
  const cleanText = text.replace(URL_PATTERN, (match) => {
    const url = match.replace(/[.,;:!?)}\]]+$/g, "");
    links.push({
      id: createMessageId(),
      url: url.startsWith("www.") ? `https://${url}` : url,
    });
    return match.slice(url.length);
  });
  return { cleanText, links };
}

export function appendInputText(previous: string, next: string) {
  if (!next) return previous;
  if (!previous) return next.trimStart();
  if (/\s$/.test(previous) || /^\s/.test(next)) return `${previous}${next}`;
  return `${previous} ${next}`;
}

export function isImageFile(file: File) {
  return (
    file.type.startsWith("image/") || IMAGE_EXTENSION_PATTERN.test(file.name)
  );
}

export function shouldReadAttachedImages(message: string) {
  return IMAGE_READ_INTENT_PATTERN.test(message);
}

export function trimAttachmentContent(content: string) {
  if (content.length <= ATTACHMENT_CONTENT_LIMIT) return content;
  return `${content.slice(0, ATTACHMENT_CONTENT_LIMIT)}\n[Attachment truncated]`;
}

export function buildChatDocumentAttachments(
  documents: ChatDocumentAttachment[],
): ChatAttachment[] {
  return documents.map((document) => ({
    type: "document",
    name: document.name,
    file_path: document.filePath,
    mime_type: document.mimeType || null,
  }));
}

export function hasDraggedFiles(event: DragEvent<HTMLElement>) {
  return (
    Array.from(event.dataTransfer.types ?? []).includes("Files") ||
    event.dataTransfer.files.length > 0 ||
    Array.from(event.dataTransfer.items ?? []).some(
      (item) => item.kind === "file",
    )
  );
}

export function getDroppedFileUri(event: DragEvent<HTMLElement>) {
  if (!Array.from(event.dataTransfer.types ?? []).includes("text/uri-list")) {
    return "";
  }
  return event.dataTransfer.getData("text/uri-list");
}

export async function readDecomposedFile(filePath: string) {
  if (typeof window !== "undefined" && window.electron?.readFile) {
    const result = await window.electron.readFile(filePath);
    return typeof result === "string" ? result : result?.content || "";
  }

  const response = await fetch("/api/read-file", {
    method: "POST",
    body: JSON.stringify({ filePath }),
  });
  const result = await response.json();
  if (!response.ok) {
    throw new Error(result?.error || "Failed to read document.");
  }
  return result?.content || "";
}

export const conversationStorageKey = (
  scope: string,
  resourceId: string,
  presentationType: "standard" | "smart",
) => `presenton:chat:${scope}:${presentationType}:conversationId:${resourceId}`;

export const readStoredConversationId = (key: string) => {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage.getItem(key);
  } catch {
    return null;
  }
};

export const storeConversationId = (key: string, conversationId: string) => {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(key, conversationId);
  } catch {
    // Chat history still works from the server when browser storage is blocked.
  }
};

export const removeStoredConversationId = (key: string) => {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(key);
  } catch {
    // Nothing else needs to be cleared when browser storage is unavailable.
  }
};

export const editPreviewStorageKey = (
  scope: string,
  resourceId: string,
  conversationId: string,
) =>
  `presenton:chat:${scope}:editPreviews:${resourceId}:${conversationId}`;

type StoredEditPreviewEntry = {
  content: string;
  editPreview: ChatEditPreview;
};

export const storeEditPreviewsForConversation = (
  key: string,
  messages: Array<{ role: string; content: string; editPreview?: ChatEditPreview }>,
) => {
  if (typeof window === "undefined") return;
  const entries: StoredEditPreviewEntry[] = messages
    .filter(
      (message) =>
        message.role === "assistant" &&
        message.editPreview?.modifiedSlides?.length,
    )
    .map((message) => ({
      content: message.content,
      editPreview: message.editPreview!,
    }));
  try {
    if (entries.length === 0) {
      window.sessionStorage.removeItem(key);
      return;
    }
    window.sessionStorage.setItem(key, JSON.stringify(entries));
  } catch {
    // Preview restore is best-effort; canvas content still comes from the server.
  }
};

export const readStoredEditPreviews = (key: string): StoredEditPreviewEntry[] => {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.sessionStorage.getItem(key);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as StoredEditPreviewEntry[]) : [];
  } catch {
    return [];
  }
};

export const attachStoredEditPreviews = <
  T extends { role: string; content: string; editPreview?: ChatEditPreview },
>(
  messages: T[],
  stored: StoredEditPreviewEntry[],
): T[] => {
  if (!stored.length) return messages;
  const remaining = [...stored];
  return messages.map((message) => {
    if (message.role !== "assistant" || message.editPreview) return message;
    const matchIndex = remaining.findIndex(
      (entry) => entry.content === message.content,
    );
    if (matchIndex < 0) return message;
    const [match] = remaining.splice(matchIndex, 1);
    return {
      ...message,
      editPreview: match.editPreview,
    };
  });
};

const ELEMENT_TYPE_LABELS: Record<string, string> = {
  text: "文本",
  image: "图片",
  chart: "图表",
  table: "表格",
  vector: "形状",
  svg: "矢量图",
  math: "公式",
  container: "容器",
  flex: "弹性布局",
  grid: "网格",
  group: "编组",
  infographic: "信息图",
  "text-list": "列表",
};

export function localizeSelectionLabel(label: string | null | undefined): string {
  const value = (label || "").trim();
  if (!value) return "";

  if (/^\d+\s+components?\s+selected$/i.test(value)) {
    const count = value.match(/^(\d+)/)?.[1] ?? "";
    return count ? `已选 ${count} 个组件` : "已选多个组件";
  }

  const elementTypeMatch = value.match(/^([a-z-]+)\s+in\s+(.+)$/i);
  if (elementTypeMatch) {
    const typeLabel =
      ELEMENT_TYPE_LABELS[elementTypeMatch[1].toLowerCase()] ?? elementTypeMatch[1];
    return `${localizeSelectionLabel(elementTypeMatch[2])}中的${typeLabel}`;
  }

  if (ELEMENT_TYPE_LABELS[value.toLowerCase()]) {
    return ELEMENT_TYPE_LABELS[value.toLowerCase()];
  }

  if (/^component\s+\d+$/i.test(value)) {
    return value.replace(/^component\s+/i, "组件 ");
  }

  if (/full[- ]?(slide|canvas)\s+white\s+background/i.test(value)) {
    return "整页白色背景";
  }
  if (/full[- ]?canvas\s+white\s+background/i.test(value)) {
    return "整页白色背景";
  }
  if (/white\s+background/i.test(value) && /decorative/i.test(value)) {
    return "白色装饰背景";
  }
  if (/background/i.test(value) && !/[\u4e00-\u9fff]/.test(value)) {
    return "背景";
  }

  // Long English template descriptions are truncated poorly in the chip.
  if (
    value.length > 28 &&
    !/[\u4e00-\u9fff]/.test(value) &&
    /[A-Za-z]{3,}/.test(value)
  ) {
    if (/title|heading|header/i.test(value)) return "标题";
    if (/image|illustration|photo/i.test(value)) return "图片";
    if (/chart|graph/i.test(value)) return "图表";
    if (/card|callout/i.test(value)) return "卡片";
    if (/text|paragraph|body|content/i.test(value)) return "文本";
    return "已选组件";
  }

  return value;
}
