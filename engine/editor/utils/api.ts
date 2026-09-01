import { extractApiErrorMessage } from "@/utils/apiErrorMessages";
import { withBridgeSessionQuery } from "@/utils/teachnovaSession";

function isAbsoluteHttpUrl(path: string): boolean {
  return /^https?:\/\//i.test(path);
}

export async function getApiErrorMessage(
  response: Response,
  fallbackMessage: string
): Promise<string> {
  try {
    const errorData: unknown = await response.clone().json();
    return extractApiErrorMessage(errorData, fallbackMessage, response.status);
  } catch {
    try {
      const text = await response.text();
      return extractApiErrorMessage(text, fallbackMessage, response.status);
    } catch {
      return fallbackMessage;
    }
  }
}

function withLeadingSlash(path: string): string {
  return path.startsWith("/") ? path : `/${path}`;
}

function getConfiguredFastApiUrl(): string | null {
  if (typeof window !== "undefined" && window.env?.NEXT_PUBLIC_FAST_API) {
    return window.env.NEXT_PUBLIC_FAST_API;
  }

  if (process.env.NEXT_PUBLIC_FAST_API) {
    return process.env.NEXT_PUBLIC_FAST_API;
  }

  return null;
}

function getFastApiUrlFromQuery(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const params = new URLSearchParams(window.location.search);
    const value = params.get("fastapiUrl");
    if (!value) return null;

    const parsed = new URL(value);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return null;
    }
    return parsed.origin;
  } catch {
    return null;
  }
}

function isElectronRuntime(): boolean {
  return typeof window !== "undefined" && !!window.electron;
}

function shouldUseConfiguredFastApiInLocalWeb(): boolean {
  if (typeof window === "undefined") return false;
  if (window.location.hostname !== "127.0.0.1" && window.location.hostname !== "localhost") {
    return false;
  }

  const configured = getConfiguredFastApiUrl();
  if (!configured) return false;

  try {
    // Long-running local template imports can outlive the Next.js development
    // proxy connection. Direct FastAPI requests avoid losing a completed job.
    return new URL(configured).origin !== window.location.origin;
  } catch {
    return false;
  }
}

function shouldUseDirectFastApiOriginInBrowser(): boolean {
  return (
    isElectronRuntime() ||
    !!getFastApiUrlFromQuery() ||
    shouldUseConfiguredFastApiInLocalWeb()
  );
}

function normalizeFastApiOrigin(raw: string): string {
  try {
    return new URL(raw).origin;
  } catch {
    return raw.replace(/\/+$/, "");
  }
}

/**
 * Canvas/Konva must load images same-origin. Local web and Docker should keep
 * /app_data and /static on the Next/nginx origin even when API calls go direct
 * to FastAPI; Electron still needs the FastAPI origin.
 */
function shouldUseSameOriginAssetsInBrowser(): boolean {
  return typeof window !== "undefined" && !isElectronRuntime();
}

function resolveBackendPathForRuntime(
  path: string,
  kind: "api" | "asset" = "api"
): string {
  const normalizedPath = withLeadingSlash(path);

  if (typeof window !== "undefined") {
    if (kind === "asset" && shouldUseSameOriginAssetsInBrowser()) {
      return normalizedPath;
    }
    if (kind === "api" && !shouldUseDirectFastApiOriginInBrowser()) {
      return normalizedPath;
    }
  }

  return `${getFastAPIUrl()}${normalizedPath}`;
}

function resolveAuthenticatedBackendAsset(path: string): string {
  const resolved = resolveBackendPathForRuntime(path, "asset");
  // TeachNova's bridge token lives in sessionStorage, so normal <img>/Konva
  // requests do not inherit the Authorization header installed for fetch().
  // FastAPI protects /app_data/images per user and intentionally returns 404
  // for an unauthenticated/private asset. Carry the same bridge token in the
  // query string, exactly as the EventSource stream does.
  return typeof window !== "undefined" ? withBridgeSessionQuery(resolved) : resolved;
}

// Utility to get the backend base URL.
// - Browser web/docker: same origin (nginx proxy).
// - Browser electron, local web with NEXT_PUBLIC_FAST_API, or query override:
//   direct FastAPI origin (avoids Next.js proxy timeouts on large PPTX imports).
// - Server-side: configured FastAPI origin fallback.
export function getFastAPIUrl(): string {
  const queryFastApiUrl = getFastApiUrlFromQuery();
  if (queryFastApiUrl) {
    return queryFastApiUrl;
  }

  if (typeof window !== "undefined") {
    if (isElectronRuntime() || shouldUseConfiguredFastApiInLocalWeb()) {
      const configured = getConfiguredFastApiUrl();
      if (configured) {
        return normalizeFastApiOrigin(configured);
      }
    }
    return window.location.origin;
  }

  const configured = getConfiguredFastApiUrl();
  return configured ? normalizeFastApiOrigin(configured) : "http://127.0.0.1:5001";
}

// Utility to construct API URL for Docker/web runtime.
export function getApiUrl(path: string): string {
  if (isAbsoluteHttpUrl(path)) {
    return path;
  }

  const normalizedPath = withLeadingSlash(path);
  const isFastApiEndpoint =
    normalizedPath.startsWith("/api/v1/") ||
    normalizedPath.startsWith("/api/v2/");
  if (!isFastApiEndpoint) {
    return normalizedPath;
  }

  if (typeof window === "undefined" && !getConfiguredFastApiUrl()) {
    return normalizedPath;
  }

  return resolveBackendPathForRuntime(normalizedPath);
}

/**
 * getApiUrl may return a path without host (e.g. `/api/v1/...`). A single-argument
 * `new URL("/api/...")` call is invalid; use this before `new URL(..., ...)`-style
 * builds or to obtain an absolute string for `URL` + `searchParams`.
 */
export function buildAbsoluteApiRequestUrl(
  path: string,
  baseForRelative: string = typeof window !== "undefined" &&
    window.location?.origin
    ? window.location.origin
    : "http://127.0.0.1:5001"
): string {
  const resolved = getApiUrl(path);
  if (isAbsoluteHttpUrl(resolved)) {
    return resolved;
  }
  return new URL(resolved, baseForRelative).toString();
}

function hasBackendAssetPrefix(path: string): boolean {
  return path.startsWith("/static/") || path.startsWith("/app_data/");
}

function toBackendServedPath(rawPath: string): string {
  const normalized = rawPath.replace(/\\/g, "/");

  // Never rewrite Next.js bundled/static assets.
  if (normalized.startsWith("/_next/static/")) {
    return normalized;
  }

  const appDataIdx = normalized.indexOf("/app_data/");
  if (appDataIdx !== -1) {
    return normalized.slice(appDataIdx);
  }

  const staticIdx = normalized.indexOf("/static/");
  if (staticIdx !== -1) {
    return normalized.slice(staticIdx);
  }

  const imagesIdx = normalized.lastIndexOf("/images/");
  if (imagesIdx !== -1) {
    return `/app_data${normalized.slice(imagesIdx)}`;
  }

  const uploadsIdx = normalized.lastIndexOf("/uploads/");
  if (uploadsIdx !== -1) {
    return `/app_data${normalized.slice(uploadsIdx)}`;
  }

  const fontsIdx = normalized.lastIndexOf("/fonts/");
  if (fontsIdx !== -1) {
    return `/app_data${normalized.slice(fontsIdx)}`;
  }

  return normalized;
}

function splitPathAndSuffix(value: string): { path: string; suffix: string } {
  const hashIdx = value.indexOf("#");
  const queryIdx = value.indexOf("?");
  const firstSuffixIdx =
    hashIdx === -1
      ? queryIdx
      : queryIdx === -1
        ? hashIdx
        : Math.min(queryIdx, hashIdx);

  if (firstSuffixIdx === -1) {
    return { path: value, suffix: "" };
  }

  return {
    path: value.slice(0, firstSuffixIdx),
    suffix: value.slice(firstSuffixIdx),
  };
}

// Resolve backend-served asset paths to the runtime-appropriate backend path.
export function resolveBackendAssetUrl(path?: string): string {
  if (!path) return "";

  const trimmedPath = path.trim();
  if (!trimmedPath) return "";

  if (trimmedPath.startsWith("data:") || trimmedPath.startsWith("blob:")) {
    return trimmedPath;
  }

  if (trimmedPath.startsWith("file:")) {
    try {
      const parsed = new URL(trimmedPath);
      const servedPath = toBackendServedPath(decodeURIComponent(parsed.pathname));
      if (hasBackendAssetPrefix(servedPath)) {
        return resolveAuthenticatedBackendAsset(servedPath);
      }
      return trimmedPath;
    } catch {
      return trimmedPath;
    }
  }

  if (isAbsoluteHttpUrl(trimmedPath)) {
    try {
      const parsed = new URL(trimmedPath);
      const servedPath = toBackendServedPath(parsed.pathname);
      if (hasBackendAssetPrefix(servedPath)) {
        return resolveAuthenticatedBackendAsset(
          `${servedPath}${parsed.search}${parsed.hash}`
        );
      }
      return trimmedPath;
    } catch {
      return trimmedPath;
    }
  }

  const { path: pathPart, suffix } = splitPathAndSuffix(trimmedPath);
  const servedPath = toBackendServedPath(withLeadingSlash(pathPart));
  if (hasBackendAssetPrefix(servedPath)) {
    return resolveAuthenticatedBackendAsset(`${servedPath}${suffix}`);
  }

  return trimmedPath;
}

export type BackendAssetLike = {
  file_url?: string | null;
  path?: string | null;
  url?: string | null;
};

export function getBackendAssetSource(
  asset: BackendAssetLike | string | null | undefined
): string {
  if (typeof asset === "string") {
    return asset;
  }

  if (!asset) {
    return "";
  }

  return (asset.file_url || asset.path || asset.url || "").trim();
}

export function resolveBackendAssetSource(
  asset: BackendAssetLike | string | null | undefined
): string {
  return resolveBackendAssetUrl(getBackendAssetSource(asset));
}

function isAssetLikeString(value: string): boolean {
  const candidate = value.trim();
  if (!candidate) return false;

  if (/^(?:https?:|data:|blob:|file:)/i.test(candidate)) {
    return true;
  }

  const { path } = splitPathAndSuffix(candidate);
  const normalizedPath = path.replace(/\\/g, "/");
  const startsLikePath =
    normalizedPath.startsWith("/") ||
    normalizedPath.startsWith("./") ||
    normalizedPath.startsWith("../") ||
    /^[A-Za-z]:\//.test(normalizedPath) ||
    /^(?:static|app_data|images|uploads|fonts)\//.test(normalizedPath);

  if (!startsLikePath) return false;

  return hasBackendAssetPrefix(
    toBackendServedPath(withLeadingSlash(normalizedPath))
  );
}

export const normalizeBackendAssetUrls = <T,>(input: T): T => {
  if (Array.isArray(input)) {
    return input.map((item) => normalizeBackendAssetUrls(item)) as T;
  }

  if (input && typeof input === "object") {
    const normalized: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(
      input as Record<string, unknown>
    )) {
      normalized[key] =
        typeof value === "string"
          ? isAssetLikeString(value)
            ? resolveBackendAssetUrl(value)
            : value
          : normalizeBackendAssetUrls(value);
    }
    return normalized as T;
  }

  return input;
};