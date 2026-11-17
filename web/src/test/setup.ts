import { afterEach, beforeEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  // Every test must install its own mock HTTP responder. No provider/network calls.
  vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("Unexpected live HTTP request"); }));
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true, value: vi.fn(),
  });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
