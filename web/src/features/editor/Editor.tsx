import { useEffect, useState } from "react";
import { api, editorUrl, localizeError } from "../../api/client";
import type { Presentation } from "../../entities/types";

export function Editor({ presentationId }: { presentationId: string }) {
  const [presentation, setPresentation] = useState<Presentation>();
  const [error, setError] = useState("");
  // Capture this one-time command for the iframe, then remove it from the
  // browser URL. A refresh must reopen saved state, never replay generation.
  const [streaming] = useState(
    () => new URLSearchParams(location.search).get("stream") === "true"
  );

  useEffect(() => {
    if (!streaming) return;

    const cleanUrl = new URL(window.location.href);
    cleanUrl.searchParams.delete("stream");
    window.history.replaceState({}, "", cleanUrl.toString());

    const expectedOrigin = new URL(editorUrl(presentationId, true)).origin;
    const handleEngineMessage = (event: MessageEvent) => {
      if (event.origin !== expectedOrigin) return;
      if (
        !event.data ||
        event.data.type !== "presenton:stream-settled" ||
        event.data.presentationId !== presentationId
      ) {
        return;
      }

      // `stream` is a one-time generation command. Keeping it on the outer
      // Teachnova URL would make a later browser refresh start the stream again.
      const settledUrl = new URL(window.location.href);
      settledUrl.searchParams.delete("stream");
      window.history.replaceState({}, "", settledUrl.toString());
    };

    window.addEventListener("message", handleEngineMessage);
    return () => window.removeEventListener("message", handleEngineMessage);
  }, [presentationId, streaming]);

  useEffect(() => {
    void api<Presentation>(`/presentation/${presentationId}`).then(setPresentation).catch((cause: Error) => setError(localizeError(cause)));
  }, [presentationId]);

  if (error) return <main className="center-state"><h1>编辑器暂时无法打开</h1><p>{error}</p><a href="/">返回首页</a></main>;
  if (!presentation) return <main className="center-state running"><span className="spinner"/><h1>正在打开编辑器</h1></main>;
  return <main className="editor-page editor-page-single-shell">
    <iframe title="PPT 编辑器" src={editorUrl(presentationId, streaming)} />
  </main>;
}
