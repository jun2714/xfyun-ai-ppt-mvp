import type { SlideOutline } from "../../entities/types";

/** Strip markdown heading markers so users edit plain Chinese titles. */
export function toEditableOutlineContent(content: string) {
  return (content || "")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/__(.*?)__/g, "$1")
    .replace(/^\s*[-*]\s+/gm, "• ");
}

/** Re-apply a markdown title line for backend compatibility. */
export function toStoredOutlineContent(content: string) {
  const lines = (content || "").split("\n");
  const firstIdx = lines.findIndex((line) => line.trim());
  if (firstIdx < 0) return "";
  const firstLine = lines[firstIdx] ?? "";
  const title = firstLine.replace(/^#{1,6}\s+/, "").replace(/^•\s+/, "").trim();
  lines[firstIdx] = `## ${title}`;
  return lines.join("\n");
}

export function outlineTitle(content: string) {
  const editable = toEditableOutlineContent(content);
  return editable.split("\n").find((line) => line.trim())?.trim() || "未命名页面";
}

function unescapePartialJsonString(value: string) {
  try {
    return JSON.parse(`"${value}"`) as string;
  } catch {
    return value
      .replace(/\\n/g, "\n")
      .replace(/\\t/g, "\t")
      .replace(/\\"/g, '"')
      .replace(/\\\\/g, "\\");
  }
}

/**
 * Extract slide "content" fields from a partial JSON stream.
 * Completed strings become stable pages; a trailing unfinished string is shown
 * as the page currently being written.
 */
export function parsePartialOutlineSlides(accumulated: string): SlideOutline[] {
  const slides: SlideOutline[] = [];
  const pattern = /"content"\s*:\s*"((?:\\.|[^"\\])*)"/g;
  let match: RegExpExecArray | null;
  let lastIndex = 0;
  while ((match = pattern.exec(accumulated)) !== null) {
    slides.push({ content: unescapePartialJsonString(match[1] ?? "") });
    lastIndex = pattern.lastIndex;
  }

  const trailing = accumulated.slice(lastIndex);
  const incomplete = trailing.match(/"content"\s*:\s*"((?:\\.|[^"\\])*)$/);
  if (incomplete?.[1] != null && incomplete[1].length > 0) {
    slides.push({ content: unescapePartialJsonString(incomplete[1]) });
  }

  return slides;
}

/** Build a readable preview from the partial kindergarten lesson-plan JSON. */
export function parsePartialKindergartenSlides(accumulated: string): SlideOutline[] {
  const markers = [...accumulated.matchAll(/"screen_content"\s*:\s*\{/g)];
  return markers.flatMap((marker, index) => {
    const start = marker.index ?? 0;
    const end = markers[index + 1]?.index ?? accumulated.length;
    const block = accumulated.slice(start, end);
    const title = block.match(/"title"\s*:\s*"((?:\\.|[^"\\])*)"/)?.[1];
    if (!title) return [];
    const lines = [unescapePartialJsonString(title)];
    const pointsBlock = block.match(/"points"\s*:\s*\[([\s\S]*?)(?:\]|$)/)?.[1] ?? "";
    for (const point of pointsBlock.matchAll(/"((?:\\.|[^"\\])*)"/g)) {
      lines.push(`- ${unescapePartialJsonString(point[1] ?? "")}`);
    }
    const instruction = block.match(
      /"instruction"\s*:\s*"((?:\\.|[^"\\])*)"/,
    )?.[1];
    if (instruction) lines.push(unescapePartialJsonString(instruction));
    return [{ content: lines.join("\n") }];
  });
}
