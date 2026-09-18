/**
 * Ask the outer Teachnova shell to navigate home when this editor is embedded.
 * Returning false means the editor is standalone and should use its dashboard.
 */
export function requestTeachnovaHome(): boolean {
  if (typeof window === "undefined" || window.parent === window) return false;

  let targetOrigin = "*";
  try {
    if (document.referrer) targetOrigin = new URL(document.referrer).origin;
  } catch {
    // The outer shell validates the sender origin before acting on the message.
  }

  window.parent.postMessage(
    { type: "teachnova:navigate", target: "home" },
    targetOrigin,
  );
  return true;
}

const EMBED_FLAG_KEY = "teachnova_embed";
const RETURN_TO_KEY = "teachnova_return_to";
const FROM_KEY = "teachnova_from";
const PARENT_ORIGIN_KEY = "teachnova_parent_origin";

function rememberParentOrigin(): void {
  if (typeof window === "undefined") return;
  try {
    if (sessionStorage.getItem(PARENT_ORIGIN_KEY)) return;
    const ancestor = window.location.ancestorOrigins?.[0];
    if (ancestor) {
      sessionStorage.setItem(PARENT_ORIGIN_KEY, ancestor);
      return;
    }
    if (document.referrer) {
      sessionStorage.setItem(PARENT_ORIGIN_KEY, new URL(document.referrer).origin);
    }
  } catch {
    // ignore
  }
}

/** Persist embed mode so in-iframe navigation keeps the top-tab layout. */
export function markTeachnovaEmbed(enabled = true): void {
  if (typeof window === "undefined") return;
  try {
    if (enabled) {
      sessionStorage.setItem(EMBED_FLAG_KEY, "1");
      rememberParentOrigin();
    } else sessionStorage.removeItem(EMBED_FLAG_KEY);
  } catch {
    // ignore
  }
}

export function isTeachnovaEmbed(): boolean {
  if (typeof window === "undefined") return false;
  try {
    const params = new URLSearchParams(window.location.search);
    if (params.get("embed") === "teachnova") {
      markTeachnovaEmbed(true);
      persistWorkbenchReturn(params);
      return true;
    }
    return sessionStorage.getItem(EMBED_FLAG_KEY) === "1";
  } catch {
    return false;
  }
}

function persistWorkbenchReturn(params: URLSearchParams): void {
  try {
    const from = params.get("from") || "";
    const returnTo = params.get("return_to") || "";
    if (from) sessionStorage.setItem(FROM_KEY, from);
    if (returnTo) sessionStorage.setItem(RETURN_TO_KEY, returnTo);
  } catch {
    // ignore
  }
}

export function requestTeachnovaCloseEditor(): boolean {
  if (typeof window === "undefined" || window.parent === window) return false;
  const params = new URLSearchParams(window.location.search);
  persistWorkbenchReturn(params);
  let from = "";
  try {
    from = params.get("from") || sessionStorage.getItem(FROM_KEY) || "";
  } catch {
    from = params.get("from") || "";
  }
  const returnTo = consumeReturnTo();
  const fromWorkbench = from === "workbench" || Boolean(returnTo);
  if (!fromWorkbench) return false;

  let targetOrigin = "*";
  try {
    if (document.referrer) targetOrigin = new URL(document.referrer).origin;
  } catch {
    // The outer shell validates the sender origin before acting on the message.
  }

  window.parent.postMessage({ type: "teachnova:close-editor" }, targetOrigin);
  return true;
}

export function consumeReturnTo(): string {
  if (typeof window === "undefined") return "";
  try {
    const params = new URLSearchParams(window.location.search);
    persistWorkbenchReturn(params);
    const raw = params.get("return_to") || sessionStorage.getItem(RETURN_TO_KEY) || "";
    if (!raw) return "";
    const url = new URL(raw, window.location.origin);
    if (url.protocol !== "http:" && url.protocol !== "https:") return "";
    return url.toString();
  } catch {
    return "";
  }
}

/** In-app path for 「我的项目」; keep the editor inside PPT instead of jumping to the official site. */
export function teachnovaProjectsPath(): string {
  return "/dashboard";
}

/** Tell the official shell a classroom deck is generating in the background. */
export function notifyTeachnovaDeckGenerating(payload: {
  presentationId: string;
  taskId?: string;
  topic?: string;
}): void {
  if (typeof window === "undefined" || window.parent === window) return;
  rememberParentOrigin();
  // Target must not be the editor origin: after in-iframe navigation, referrer
  // is 5001 and the official parent (3030) would drop a mismatched postMessage.
  window.parent.postMessage(
    {
      type: "presenton:deck-generating",
      kind: "classroom-ppt",
      presentationId: payload.presentationId,
      taskId: payload.taskId || "",
      topic: payload.topic || "",
    },
    "*",
  );
}
