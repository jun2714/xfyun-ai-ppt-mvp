import { markTeachnovaEmbed } from "@/utils/teachnovaEmbed";

const BRIDGE_SESSION_KEY = "presenton_bridge_session";
let lastAuthRequiredAt = 0;

function notifyTeachnovaAuthRequired(): void {
  if (
    typeof window === "undefined" ||
    window.parent === window ||
    Date.now() - lastAuthRequiredAt < 1500
  ) {
    return;
  }
  lastAuthRequiredAt = Date.now();

  let targetOrigin = "*";
  try {
    if (document.referrer) targetOrigin = new URL(document.referrer).origin;
  } catch {
    // Outer shell validates the sender origin.
  }
  window.parent.postMessage(
    { type: "teachnova:auth-required", source: "ppt" },
    targetOrigin,
  );
}

export function getBridgeSessionToken(): string {
  if (typeof window === "undefined") return "";
  try {
    return sessionStorage.getItem(BRIDGE_SESSION_KEY) || "";
  } catch {
    return "";
  }
}

export function setBridgeSessionToken(token: string): void {
  if (typeof window === "undefined") return;
  try {
    if (token) sessionStorage.setItem(BRIDGE_SESSION_KEY, token);
    else sessionStorage.removeItem(BRIDGE_SESSION_KEY);
  } catch {
    // ignore
  }
}

/** Read tn_session from URL once, persist, then strip it from the address bar. */
export function captureTeachnovaSessionFromUrl(): string {
  if (typeof window === "undefined") return getBridgeSessionToken();

  try {
    const url = new URL(window.location.href);
    if (url.searchParams.get("embed") === "teachnova") {
      markTeachnovaEmbed(true);
    }
    try {
      const from = url.searchParams.get("from") || "";
      const returnTo = url.searchParams.get("return_to") || "";
      if (from) sessionStorage.setItem("teachnova_from", from);
      if (returnTo) sessionStorage.setItem("teachnova_return_to", returnTo);
    } catch {
      // ignore
    }
    const fromQuery = url.searchParams.get("tn_session") || "";
    if (fromQuery) {
      setBridgeSessionToken(fromQuery);
      url.searchParams.delete("tn_session");
      if (url.searchParams.get("embed") === "teachnova") {
        url.searchParams.delete("embed");
      }
      window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
      return fromQuery;
    }
  } catch {
    // ignore
  }
  return getBridgeSessionToken();
}


/**
 * Ensure API calls to Presenton FastAPI carry the bridged session JWT.
 * Covers fetch sites that forgot getHeader().
 */
export function installTeachnovaAuthFetch(): void {
  if (typeof window === "undefined") return;
  const w = window as Window & { __tnAuthFetchInstalled?: boolean };
  if (w.__tnAuthFetchInstalled) return;
  w.__tnAuthFetchInstalled = true;

  const originalFetch = window.fetch.bind(window);
  window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    const token = getBridgeSessionToken();
    if (!token) return originalFetch(input, init);

    let url = "";
    if (typeof input === "string") url = input;
    else if (input instanceof URL) url = input.href;
    else url = input.url;

    const isApi =
      url.includes("/api/v1/") ||
      url.includes("/api/v2/") ||
      /:8000(?:\/|$)/.test(url);
    if (!isApi) return originalFetch(input, init);

    const headers = new Headers(
      init?.headers || (input instanceof Request ? input.headers : undefined)
    );
    if (!headers.has("Authorization")) {
      headers.set("Authorization", `Bearer ${token}`);
    }
    return originalFetch(input, { ...init, headers }).then((response) => {
      if (response.status === 401) {
        setBridgeSessionToken("");
        notifyTeachnovaAuthRequired();
      }
      return response;
    });
  };
}

export function bootstrapTeachnovaSession(): string {
  // Detect embed before stripping query params elsewhere.
  try {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      if (params.get("embed") === "teachnova") {
        markTeachnovaEmbed(true);
      }
    }
  } catch {
    // ignore
  }
  const token = captureTeachnovaSessionFromUrl();
  installTeachnovaAuthFetch();
  return token;
}

/** EventSource cannot set Authorization headers; pass session via query. */
export function withBridgeSessionQuery(url: string): string {
  const token =
    getBridgeSessionToken() ||
    (typeof window !== "undefined"
      ? new URLSearchParams(window.location.search).get("tn_session") || ""
      : "");
  if (!token) return url;
  try {
    const absolute = /^https?:\/\//i.test(url)
      ? new URL(url)
      : new URL(url, typeof window !== "undefined" ? window.location.origin : "http://127.0.0.1:5001");
    if (!absolute.searchParams.get("tn_session")) {
      absolute.searchParams.set("tn_session", token);
    }
    if (/^https?:\/\//i.test(url)) return absolute.toString();
    return `${absolute.pathname}${absolute.search}${absolute.hash}`;
  } catch {
    const join = url.includes("?") ? "&" : "?";
    return `${url}${join}tn_session=${encodeURIComponent(token)}`;
  }
}
