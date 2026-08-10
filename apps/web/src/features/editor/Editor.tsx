import React, { useEffect, useMemo, useState } from "react";
import { api, downloadExport, requestKey, startJob } from "../../api/client";
import type { PresentationState, Scene, SceneNode } from "../../entities/types";
import { SceneCanvas } from "./SceneCanvas";

export function Editor({ presentationId }: { presentationId: string }) {
  const [state, setState] = useState<PresentationState>();
  const [pageIndex, setPageIndex] = useState(0);
  const [selectedId, setSelectedId] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [copiedNodeId, setCopiedNodeId] = useState("");
  const [error, setError] = useState("");
  const load = async () => { try { setState(await api(`/presentations/${presentationId}`)); } catch (cause) { setError((cause as Error).message); } };
  useEffect(() => { void load(); }, [presentationId]);
  const scene = state?.scene;
  const page = scene?.pages[pageIndex];
  const node = page?.nodes.find((item) => item.id === selectedId);
  const selectNode = (id: string, additive: boolean) => { setSelectedId(id); setSelectedIds((current) => additive ? current.includes(id) ? current.filter((item) => item !== id) : [...current, id] : [id]); };
  const applyScene = (next: Scene | undefined) => next && setState((current) => {
    if (!current) return current;
    const { quality: _quality, ...rest } = current;
    return { ...rest, scene: next };
  });
  const command = async (type: string, value: unknown, target: SceneNode | undefined = node) => {
    const pageCommand = ["duplicate-page", "delete-page", "reorder-page"].includes(type);
    const multiCommand = ["align-nodes", "distribute-nodes", "set-theme"].includes(type);
    if (!scene || !page || (!target && !type.startsWith("add-") && !pageCommand && !multiCommand)) return;
    try {
      const next = await api<Scene>(`/presentations/${presentationId}/commands`, { method: "POST", body: JSON.stringify({ type, pageId: page.id, nodeId: target?.id ?? "__page__", value, expectedRevision: scene.revision, idempotencyKey: requestKey() }) });
      applyScene(next);
      if (["add-text", "add-shape", "add-image"].includes(type)) setSelectedId(next.pages.find((item) => item.id === page.id)?.nodes.at(-1)?.id ?? "");
      if (type === "add-page") setPageIndex(next.pages.length - 1);
      if (type === "duplicate-page") setPageIndex(Math.min(next.pages.length - 1, pageIndex + 1));
      if (type === "delete-node") { setSelectedId(""); setSelectedIds([]); }
      if (type === "delete-page") setPageIndex((current) => Math.max(0, Math.min(current, next.pages.length - 1)));
    }
    catch (cause) { setError((cause as Error).message); }
  };
  const changeBounds = (field: keyof SceneNode["bounds"], value: number) => node && void command("set-bounds", { ...node.bounds, [field]: value });
  const qualityIssues = useMemo(() => state?.quality?.issues.filter((issue) => !issue.pageId || issue.pageId === page?.id) ?? [], [state?.quality, page?.id]);
  if (!state || !scene || !page) return <main className="empty-state">正在读取 Scene Graph…</main>;
  const onEditorKeyDown = (event: React.KeyboardEvent<HTMLElement>) => {
    if ((event.target as HTMLElement).matches("input,textarea,select")) return;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "c" && node) { event.preventDefault(); setCopiedNodeId(node.id); }
    else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "v" && copiedNodeId) { event.preventDefault(); const source = page.nodes.find((item) => item.id === copiedNodeId); if (source) void command("duplicate-node", "", source); }
    else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") { event.preventDefault(); void api<Scene>(`/presentations/${presentationId}/${event.shiftKey ? "redo" : "undo"}`, { method: "POST" }).then(applyScene).catch((cause) => setError(cause.message)); }
    else if ((event.key === "Delete" || event.key === "Backspace") && node) { event.preventDefault(); void command("delete-node", ""); }
    else if (node && ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) {
      event.preventDefault(); const step = event.shiftKey ? 10 : 1;
      const dx = event.key === "ArrowLeft" ? -step : event.key === "ArrowRight" ? step : 0;
      const dy = event.key === "ArrowUp" ? -step : event.key === "ArrowDown" ? step : 0;
      void command("set-bounds", { ...node.bounds, x: node.bounds.x + dx, y: node.bounds.y + dy });
    }
  };
  return <main className="editor-shell" tabIndex={-1} onKeyDown={onEditorKeyDown}>
    {error && <div className="editor-error" role="alert"><b>操作没有完成：</b> {error}<button onClick={() => setError("")}>关闭</button><button onClick={() => void load()}>重新加载</button></div>}
    <header className="editor-toolbar"><a href="/" className="brand">SparkDeck</a><div className="document-title"><b>{state.brief.title}</b><small>{scene.pages.length} 页 · Scene Graph 008.0</small></div><div className="insert-actions">
      <button onClick={() => void command("add-text", "", undefined)}>＋ 文字</button>
      <button onClick={() => void command("add-shape", "", undefined)}>＋ 形状</button>
      <button onClick={() => void command("add-image", "", undefined)}>＋ 图片</button>
      <button onClick={() => void command("add-page", "", undefined)}>＋ 页面</button>
    </div><div className="toolbar-actions">
      <button onClick={async () => applyScene(await api(`/presentations/${presentationId}/undo`, { method: "POST" }))}>撤销</button>
      <button onClick={async () => applyScene(await api(`/presentations/${presentationId}/redo`, { method: "POST" }))}>重做</button>
      <button onClick={async () => { await startJob(`/presentations/${presentationId}/quality-jobs`); await load(); }}>重新质检</button>
      <button className="primary" onClick={() => void downloadExport(presentationId, scene.revision).catch((cause) => setError(cause.message))}>导出 PPTX</button>
    </div></header>
    <aside className="slide-list">{scene.pages.map((item, index) => <button key={item.id} className={index === pageIndex ? "active" : ""} onClick={() => { setPageIndex(index); setSelectedId(""); setSelectedIds([]); }}><span>{index + 1}</span><SceneCanvas page={item} scale={0.16} /></button>)}</aside>
    <section className="editor-workspace" onClick={() => { setSelectedId(""); setSelectedIds([]); }}><SceneCanvas page={page} scale={0.78} selectedId={selectedId} selectedIds={selectedIds} onSelect={selectNode} onMove={(id, x, y) => { const moved = page.nodes.find((item) => item.id === id); if (moved) void command("set-bounds", { ...moved.bounds, x, y }, moved); }} onResize={(id, width, height) => { const resized = page.nodes.find((item) => item.id === id); if (resized) void command("set-bounds", { ...resized.bounds, width, height }, resized); }} /></section>
    <aside className="inspector">
      <section><h3>本页</h3><div className="page-actions"><button onClick={() => void command("duplicate-page", "", undefined)}>复制</button><button onClick={() => void command("reorder-page", Math.max(0, pageIndex - 1), undefined)} disabled={pageIndex === 0}>上移</button><button onClick={() => void command("reorder-page", Math.min(scene.pages.length - 1, pageIndex + 1), undefined)} disabled={pageIndex === scene.pages.length - 1}>下移</button><button className="danger" onClick={() => void command("delete-page", "", undefined)}>删除</button></div><button className="wide" onClick={async () => applyScene(await api(`/presentations/${presentationId}/pages/${page.id}/redesign`, { method: "POST", body: JSON.stringify({ expectedRevision: scene.revision, idempotencyKey: requestKey() }) }))}>重新设计本页（不生图）</button><h3>版式候选</h3><p className="muted">切换候选会重新执行整稿选择，关联页面约束不会被绕过。</p>{page.alternativeCandidateIds.map((candidate) => <button className="wide" key={candidate} onClick={async () => applyScene(await api(`/presentations/${presentationId}/pages/${page.id}/select-composition`, { method: "POST", body: JSON.stringify({ candidateId: candidate, expectedRevision: scene.revision, idempotencyKey: requestKey() }) }))}>切换候选 · {candidate.slice(-4)}</button>)}</section>
      {selectedIds.length > 1 && <section><h3>多选排列</h3><div className="page-actions"><button onClick={() => void command("align-nodes", { nodeIds: selectedIds, axis: "horizontal", mode: "start" }, undefined)}>左</button><button onClick={() => void command("align-nodes", { nodeIds: selectedIds, axis: "horizontal", mode: "center" }, undefined)}>水平居中</button><button onClick={() => void command("align-nodes", { nodeIds: selectedIds, axis: "horizontal", mode: "end" }, undefined)}>右</button><button onClick={() => void command("align-nodes", { nodeIds: selectedIds, axis: "vertical", mode: "start" }, undefined)}>顶</button><button onClick={() => void command("align-nodes", { nodeIds: selectedIds, axis: "vertical", mode: "center" }, undefined)}>垂直居中</button><button onClick={() => void command("align-nodes", { nodeIds: selectedIds, axis: "vertical", mode: "end" }, undefined)}>底</button><button onClick={() => void command("distribute-nodes", { nodeIds: selectedIds, axis: "horizontal" }, undefined)}>水平分布</button><button onClick={() => void command("distribute-nodes", { nodeIds: selectedIds, axis: "vertical" }, undefined)}>垂直分布</button></div></section>}
      <section><h3>整稿主题</h3><div className="bounds-grid"><label>背景<input type="color" defaultValue={String(scene.theme.background ?? "#ffffff")} onBlur={(event) => void command("set-theme", { background: event.target.value }, undefined)} /></label><label>文字<input type="color" defaultValue={String(scene.theme.text ?? "#111111")} onBlur={(event) => void command("set-theme", { text: event.target.value }, undefined)} /></label><label>主色<input type="color" defaultValue={String(scene.theme.primary ?? "#2d7a50")} onBlur={(event) => void command("set-theme", { primary: event.target.value }, undefined)} /></label><label>强调色<input type="color" defaultValue={String(scene.theme.accent ?? "#f2c94c")} onBlur={(event) => void command("set-theme", { accent: event.target.value }, undefined)} /></label></div><label>标题字体<input defaultValue={String(scene.theme.headingFontFamily ?? "Microsoft YaHei")} onBlur={(event) => void command("set-theme", { headingFontFamily: event.target.value }, undefined)} /></label><label>正文字体<input defaultValue={String(scene.theme.bodyFontFamily ?? "Microsoft YaHei")} onBlur={(event) => void command("set-theme", { bodyFontFamily: event.target.value }, undefined)} /></label></section>
      {node && <section><h3>元素属性</h3><span className="node-kind">{node.kind}</span>{node.kind === "text" && <><label>文字<textarea key={`${node.id}-${scene.revision}`} defaultValue={String(node.content.text ?? "")} onBlur={(event) => void command("set-text", event.target.value)} /></label><div className="bounds-grid"><label>字号<input type="number" defaultValue={Number(node.style.fontSize ?? 20)} onBlur={(event) => void command("set-style", { fontSize: Number(event.target.value) })} /></label><label>粗细<select defaultValue={Number(node.style.fontWeight ?? 400)} onChange={(event) => void command("set-style", { fontWeight: Number(event.target.value) })}><option value="400">常规</option><option value="600">半粗</option><option value="700">粗体</option></select></label><label>颜色<input type="color" defaultValue={String(node.style.color ?? "#111111")} onBlur={(event) => void command("set-style", { color: event.target.value })} /></label><label>行距<input type="number" min="1" max="2" step="0.1" defaultValue={Number(node.style.lineHeight ?? 1.2)} onBlur={(event) => void command("set-style", { lineHeight: Number(event.target.value) })} /></label></div><label>字体<input defaultValue={String(node.style.fontFamily ?? "Microsoft YaHei")} onBlur={(event) => void command("set-style", { fontFamily: event.target.value })} /></label></>}{node.kind === "image" && <><label>图片地址<input key={`${node.id}-${scene.revision}`} defaultValue={String(node.content.url ?? "")} onBlur={(event) => event.target.value && void command("set-asset", event.target.value)} /></label><label className="wide">上传本地图片<input type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => { const file = event.target.files?.[0]; if (!file) return; if (file.size > 12 * 1024 * 1024) { setError("本地图片不能超过 12MB"); return; } const reader = new FileReader(); reader.onload = () => void command("set-asset", String(reader.result)); reader.onerror = () => setError("本地图片读取失败"); reader.readAsDataURL(file); }} /></label><button className="wide" onClick={() => void command("set-crop", node.content.fit === "contain" ? "cover" : "contain")}>裁剪：{String(node.content.fit ?? "cover")}</button>{node.content.assetId && <button className="wide" onClick={async () => { await startJob(`/presentations/${presentationId}/assets/${String(node.content.assetId)}/regeneration-jobs`, { expectedRevision: scene.revision }); await load(); }}>重新生成这张图</button>}</>}<div className="bounds-grid">{(["x", "y", "width", "height"] as const).map((field) => <label key={field}>{field}<input type="number" defaultValue={Math.round(node.bounds[field])} onBlur={(event) => changeBounds(field, Number(event.target.value))} /></label>)}</div><label>旋转<input type="number" defaultValue={Number(node.style.rotation ?? 0)} onBlur={(event) => void command("set-rotation", Number(event.target.value))} /></label><label>层级<input type="number" defaultValue={node.zIndex} onBlur={(event) => void command("set-z", Number(event.target.value))} /></label><button className="wide" onClick={() => void command("set-locked", !node.locked)}>{node.locked ? "解除锁定" : "锁定元素"}</button><button className="wide" onClick={() => void command("duplicate-node", "")}>复制元素</button><button className="wide danger" disabled={node.locked} onClick={() => void command("delete-node", "")}>删除元素</button></section>}
      <section><h3>质量状态</h3><div className={`quality-chip ${state.quality?.passed ? "pass" : "pending"}`}>{state.quality?.passed ? "规则检查通过" : "需要处理"}</div>{qualityIssues.map((issue) => <div className={`quality-issue ${issue.severity}`} key={`${issue.code}-${issue.nodeIds.join("-")}`}><b>{issue.code}</b><span>{issue.message}</span></div>)}</section>
    </aside>
  </main>;
}
