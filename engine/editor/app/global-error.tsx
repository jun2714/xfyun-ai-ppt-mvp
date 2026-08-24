"use client";

import NextError from "next/error";
import { useEffect } from "react";

export default function GlobalError({
  error,
}: {
  error: Error & { digest?: string };
}) {
  useEffect(() => {
    const isChunkError =
      error?.name === "ChunkLoadError" ||
      /Failed to load chunk|ChunkLoadError/.test(error?.message || "");
    if (isChunkError) {
      const key = "presenton-chunk-reload-at";
      const last = Number(sessionStorage.getItem(key) || "0");
      if (Date.now() - last >= 15_000) {
        sessionStorage.setItem(key, String(Date.now()));
        window.location.reload();
        return;
      }
    }
    console.error("Global error:", error);
  }, [error]);

  return (
    <html lang="en">
      <body>
        {/* `NextError` is the default Next.js error page component. Its type
        definition requires a `statusCode` prop. However, since the App Router
        does not expose status codes for errors, we simply pass 0 to render a
        generic error message. */}
        <NextError statusCode={0} />
      </body>
    </html>
  );
}
