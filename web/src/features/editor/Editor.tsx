import { useEffect, useState } from "react";
import { api, editorUrl } from "../../api/client";
import type { Presentation } from "../../entities/types";

export function Editor({ presentationId }: { presentationId: string }) {
  const [presentation, setPresentation] = useState<Presentation>();
  const [error, setError] = useState("");
  useEffect(() => {
    void api<Presentation>(`/presentation/${presentationId}`).then(setPresentation).catch((cause: Error) => setError(cause.message));
  }, [presentationId]);

  if (error) return <main className="center-state"><h1>编辑器暂时无法打开</h1><p>{error}</p><a href="/">返回工作台</a></main>;
  if (!presentation) return <main className="center-state running"><span className="spinner"/><h1>正在打开编辑器</h1></main>;
  return <main className="editor-page"><header><a className="brand" href="/"><span className="brand-mark">S</span>SparkDeck</a><div><b>{presentation.title || "未命名演示"}</b><span>{presentation.slides.length} 页 · 自动保存</span></div><a href={`/presentations/${presentationId}/outline`}>查看大纲</a></header>
    <iframe title="PPT 编辑器" src={editorUrl(presentationId)} />
  </main>;
}
