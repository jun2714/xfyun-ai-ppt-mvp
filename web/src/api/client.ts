import type { StreamEvent } from "../entities/types";

const API = import.meta.env.VITE_API_BASE_URL ?? "/api/v1/ppt";

function errorMessage(body: unknown, fallback: string) {
  if (body && typeof body === "object") {
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: { ...(init?.body ? { "content-type": "application/json" } : {}), ...(init?.headers ?? {}) },
  });
  const body = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) throw new Error(errorMessage(body, response.statusText));
  return body as T;
}

/** The generation API exposes long-running outline and slide generation as SSE. */
export async function consumeStream(path: string, onEvent: (event: StreamEvent) => void) {
  const response = await fetch(`${API}${path}`, { headers: { accept: "text/event-stream" } });
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => null);
    throw new Error(errorMessage(body, response.statusText || "生成请求失败"));
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const frames = buffer.split(/\r?\n\r?\n/);
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const data = frame.split(/\r?\n/).filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart()).join("\n");
      if (!data) continue;
      const event = JSON.parse(data) as StreamEvent;
      onEvent(event);
      if (event.type === "error") throw new Error(event.detail);
    }
    if (done) break;
  }
}

export const editorUrl = (presentationId: string) => {
  const base = import.meta.env.VITE_EDITOR_BASE_URL ?? "http://127.0.0.1:5001";
  return `${base}/presentation?id=${encodeURIComponent(presentationId)}&type=standard`;
};
