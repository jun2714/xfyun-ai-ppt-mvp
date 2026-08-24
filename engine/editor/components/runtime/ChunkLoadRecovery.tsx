"use client";

import { useEffect } from "react";

const RELOAD_GUARD_KEY = "presenton-chunk-reload-at";
const RELOAD_GUARD_MS = 15_000;

function isChunkLoadError(error: unknown) {
  if (!error) {
    return false;
  }
  const name = error instanceof Error ? error.name : "";
  const message = error instanceof Error ? error.message : String(error);
  return (
    name === "ChunkLoadError" ||
    /Failed to load chunk|Loading chunk .+ failed|ChunkLoadError/.test(message)
  );
}

function reloadOnce() {
  const last = Number(sessionStorage.getItem(RELOAD_GUARD_KEY) || "0");
  if (Date.now() - last < RELOAD_GUARD_MS) {
    return;
  }
  sessionStorage.setItem(RELOAD_GUARD_KEY, String(Date.now()));
  window.location.reload();
}

export function ChunkLoadRecovery() {
  useEffect(() => {
    const onError = (event: ErrorEvent) => {
      if (
        isChunkLoadError(event.error) ||
        /Failed to load chunk|ChunkLoadError/.test(event.message || "")
      ) {
        event.preventDefault();
        reloadOnce();
      }
    };

    const onRejection = (event: PromiseRejectionEvent) => {
      if (isChunkLoadError(event.reason)) {
        event.preventDefault();
        reloadOnce();
      }
    };

    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);
    return () => {
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, []);

  return null;
}
