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
