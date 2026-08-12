const RETURN_TO_KEY = "teachnova:returnTo";

export function isSafeAppPath(path: string) {
  return path.startsWith("/") && !path.startsWith("//") && !path.includes("://");
}

export function rememberReturnTo(path = `${location.pathname}${location.search}`) {
  if (!isSafeAppPath(path)) return;
  sessionStorage.setItem(RETURN_TO_KEY, path);
}

export function peekReturnTo() {
  const path = sessionStorage.getItem(RETURN_TO_KEY);
  return path && isSafeAppPath(path) ? path : null;
}

export function clearReturnTo() {
  sessionStorage.removeItem(RETURN_TO_KEY);
}

export function consumeReturnTo() {
  const path = peekReturnTo();
  clearReturnTo();
  return path;
}
