import type { StreamEvent } from "../entities/types";
import { ApiError, errorMessage, localizeError } from "./errorMessages";
export { localizeError } from "./errorMessages";

const API = import.meta.env.VITE_API_BASE_URL ?? "/api/v1/ppt";
const BRIDGE_SESSION_KEY = "presenton_bridge_session";

if (typeof window !== "undefined") {
  try {
    const url = new URL(window.location.href);
    const token = url.searchParams.get("tn_session") || "";
    if (token) sessionStorage.setItem(BRIDGE_SESSION_KEY, token);
  } catch {
    // ignore
  }
}

function captureBridgeSessionFromUrl() {
  try {
    const url = new URL(window.location.href);
    const token = url.searchParams.get("tn_session") || "";
    if (token) {
      sessionStorage.setItem(BRIDGE_SESSION_KEY, token);
      url.searchParams.delete("tn_session");
      window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
    }
  } catch {
    // ignore
  }
}

function getBridgeSessionToken() {
  try {
    captureBridgeSessionFromUrl();
    return sessionStorage.getItem(BRIDGE_SESSION_KEY) || "";
  } catch {
    return "";
  }
}

function authHeaders(extra?: HeadersInit): HeadersInit {
  const token = getBridgeSessionToken();
  const headers = new Headers(extra);
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  return headers;
}

const hasChinese = (value: string) => /[\u3400-\u9fff]/.test(value);

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...init,
    credentials: "omit",
    headers: authHeaders({
      ...(init?.body ? { "content-type": "application/json" } : {}),
      ...(init?.headers ?? {}),
    }),
  });
  const body = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(errorMessage(body, response.status, response.statusText), response.status);
  return body as T;
}

/** The generation API exposes long-running outline and slide generation as SSE. */
export async function consumeStream(path: string, onEvent: (event: StreamEvent) => void) {
  const token = getBridgeSessionToken();
  const streamUrl = token
    ? `${API}${path}${path.includes("?") ? "&" : "?"}tn_session=${encodeURIComponent(token)}`
    : `${API}${path}`;
  const response = await fetch(streamUrl, {
    credentials: "omit",
    headers: authHeaders({ accept: "text/event-stream" }),
  });
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => null);
    throw new Error(errorMessage(body, response.status, response.statusText || "生成请求失败"));
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
      if (event.type === "error") throw new Error(localizeError(event.detail));
    }
    if (done) break;
  }
}

export const editorUrl = (presentationId: string, stream = false) => {
  const base = import.meta.env.VITE_EDITOR_BASE_URL ?? "http://127.0.0.1:5001";
  const params = new URLSearchParams({ id: presentationId, type: "standard" });
  if (stream) params.set("stream", "true");
  const token = getBridgeSessionToken();
  if (token) params.set("tn_session", token);
  if (new URLSearchParams(location.search).get("embed") === "teachnova") {
    params.set("embed", "teachnova");
  }
  return `${base}/presentation?${params.toString()}`;
};

export function localizeStatus(status: string) {
  if (hasChinese(status)) return status;
  if (/outline/i.test(status)) return "正在生成大纲";
  if (/layout|template/i.test(status)) return "正在选择页面布局";
  if (/asset|image/i.test(status)) return "正在生成图片";
  if (/export/i.test(status)) return "正在准备演示文稿";
  if (/complete/i.test(status)) return "生成完成";
  return "正在生成内容";
}
