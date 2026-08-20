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

/** Persist embed mode so in-iframe navigation keeps the top-tab layout. */
export function markTeachnovaEmbed(enabled = true): void {
  if (typeof window === "undefined") return;
  try {
    if (enabled) sessionStorage.setItem(EMBED_FLAG_KEY, "1");
    else sessionStorage.removeItem(EMBED_FLAG_KEY);
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
      return true;
    }
    return sessionStorage.getItem(EMBED_FLAG_KEY) === "1";
  } catch {
    return false;
  }
}
