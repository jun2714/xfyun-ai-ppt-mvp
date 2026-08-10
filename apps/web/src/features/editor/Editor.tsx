import React, { useEffect, useMemo, useState } from "react";
import { api, downloadExport, requestKey, startJob } from "../../api/client";
import type { PresentationState, Scene, SceneNode } from "../../entities/types";
import { SceneCanvas } from "./SceneCanvas";

export function Editor({ presentationId }: { presentationId: string }) {
  const [state, setState] = useState<PresentationState>();
  const [pageIndex, setPageIndex] = useState(0);
  const [selectedId, setSelectedId] = useState("");
  const [error, setError] = useState("");
  const load = async () => { try { setState(await api(`/presentations/${presentationId}`)); } catch (cause) { setError((cause as Error).message); } };
  useEffect(() => { void load(); }, [presentationId]);
  const scene = state?.scene;
  const page = scene?.pages[pageIndex];
  const node = page?.nodes.find((item) => item.id === selectedId);
  const applyScene = (next: Scene | undefined) => next && setState((current) => {
    if (!current) return current;
    const { quality: _quality, ...rest } = current;
    return { ...rest, scene: next };
  });
  const command = async (type: string, value: unknown, target: SceneNode | undefined = node) => {
    if (!scene || !page || (!target && !type.startsWith("add-"))) return;
    try {
      const next = await api<Scene>(`/presentations/${presentationId}/commands`, { method: "POST", body: JSON.stringify({ type, pageId: page.id, nodeId: target?.id ?? "__page__", value, expectedRevision: scene.revision, idempotencyKey: requestKey() }) });
      applyScene(next);
      if (type.startsWith("add-")) setSelectedId(next.pages.find((item) => item.id === page.id)?.nodes.at(-1)?.id ?? "");
      if (type === "delete-node") setSelectedId("");
    }
    catch (cause) { setError((cause as Error).message); }
  };
  const changeBounds = (field: keyof SceneNode["bounds"], value: number) => node && void command("set-bounds", { ...node.bounds, [field]: value });
  const qualityIssues = useMemo(() => state?.quality?.issues.filter((issue) => !issue.pageId || issue.pageId === page?.id) ?? [], [state?.quality, page?.id]);
  if (error) return <main className="empty-state"><h1>操作没有完成</h1><p>{error}</p><button onClick={() => { setError(""); void load(); }}>重新加载</button></main>;
  if (!state || !scene || !page) return <main className="empty-state">正在读取 Scene Graph…</main>;
  return <main className="editor-shell">
    <header className="editor-toolbar"><a href="/" className="brand">SparkDeck</a><div className="document-title"><b>{state.brief.title}</b><small>{scene.pages.length} 页 · Scene Graph 007.2</small></div><div className="insert-actions">
      <button onClick={() => void command("add-text", "双击编辑文字", undefined)}>＋ 文字</button>
      <button onClick={() => void command("add-shape", "", undefined)}>＋ 形状</button>
    </div><div className="toolbar-actions">
      <button onClick={async () => applyScene(await api(`/presentations/${presentationId}/undo`, { method: "POST" }))}>撤销</button>
      <button onClick={async () => applyScene(await api(`/presentations/${presentationId}/redo`, { method: "POST" }))}>重做</button>
      <button onClick={async () => { await startJob(`/presentations/${presentationId}/quality-jobs`); await load(); }}>重新质检</button>
      <button className="primary" onClick={() => void downloadExport(presentationId, scene.revision).catch((cause) => setError(cause.message))}>导出 PPTX</button>
    </div></header>
    <aside className="slide-list">{scene.pages.map((item, index) => <button key={item.id} className={index === pageIndex ? "active" : ""} onClick={() => { setPageIndex(index); setSelectedId(""); }}><span>{index + 1}</span><SceneCanvas page={item} scale={0.16} /></button>)}</aside>
    <section className="editor-workspace" onClick={() => setSelectedId("")}><SceneCanvas page={page} scale={0.78} selectedId={selectedId} onSelect={setSelectedId} onMove={(id, x, y) => { const moved = page.nodes.find((item) => item.id === id); if (moved) void command("set-bounds", { ...moved.bounds, x, y }, moved); }} /></section>
    <aside className="inspector">
      <section><h3>本页版式</h3><p className="muted">候选都来自通用排版原语，切换不会重新生成图片。</p>{page.alternativeCandidateIds.map((candidate) => <button className="wide" key={candidate} onClick={async () => applyScene(await api(`/presentations/${presentationId}/pages/${page.id}/select-composition`, { method: "POST", body: JSON.stringify({ candidateId: candidate, expectedRevision: scene.revision, idempotencyKey: requestKey() }) }))}>切换候选 · {candidate.slice(-4)}</button>)}</section>
      {node && <section><h3>元素属性</h3><span className="node-kind">{node.kind}</span>{node.kind === "text" && <label>文字<textarea key={`${node.id}-${scene.revision}`} defaultValue={String(node.content.text ?? "")} onBlur={(event) => void command("set-text", event.target.value)} /></label>}{node.kind === "image" && <><label>图片地址<input key={`${node.id}-${scene.revision}`} defaultValue={String(node.content.url ?? "")} onBlur={(event) => void command("set-asset", event.target.value)} /></label><button className="wide" onClick={() => void command("set-crop", node.content.fit === "contain" ? "cover" : "contain")}>裁剪：{String(node.content.fit ?? "cover")}</button></>}<div className="bounds-grid">{(["x", "y", "width", "height"] as const).map((field) => <label key={field}>{field}<input type="number" defaultValue={Math.round(node.bounds[field])} onBlur={(event) => changeBounds(field, Number(event.target.value))} /></label>)}</div><label>层级<input type="number" defaultValue={node.zIndex} onBlur={(event) => void command("set-z", Number(event.target.value))} /></label><button className="wide danger" onClick={() => void command("delete-node", "")}>删除元素</button></section>}
      <section><h3>质量状态</h3><div className={`quality-chip ${state.quality?.passed ? "pass" : "pending"}`}>{state.quality?.passed ? "规则检查通过" : "需要处理"}</div>{qualityIssues.map((issue) => <div className={`quality-issue ${issue.severity}`} key={`${issue.code}-${issue.nodeIds.join("-")}`}><b>{issue.code}</b><span>{issue.message}</span></div>)}</section>
    </aside>
  </main>;
}
