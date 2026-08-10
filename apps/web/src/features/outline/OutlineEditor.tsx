import React, { useState } from "react";
import { api, requestKey } from "../../api/client";
import type { Outline } from "../../entities/types";

export function OutlineEditor({ presentationId, initial, onConfirmed }: { presentationId: string; initial: Outline; onConfirmed: () => void }) {
  const [outline, setOutline] = useState(initial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const updatePage = (index: number, field: "headline" | "message", value: string) => setOutline((current) => ({ ...current, pages: current.pages.map((page, pageIndex) => pageIndex === index ? { ...page, [field]: value } : page) }));
  const updateGroup = (pageIndex: number, groupIndex: number, value: string) => setOutline((current) => ({ ...current, pages: current.pages.map((page, index) => index !== pageIndex ? page : { ...page, contentGroups: page.contentGroups.map((group, innerIndex) => innerIndex !== groupIndex ? group : group.items ? { ...group, items: value.split("\n").map((item) => item.trim()).filter(Boolean) } : { ...group, text: value }) }) }));
  const saveAndConfirm = async () => {
    setSaving(true); setError("");
    try {
      const saved = await api<Outline>(`/presentations/${presentationId}/outline`, { method: "PUT", body: JSON.stringify({ expectedRevision: outline.revision, idempotencyKey: requestKey(), outline }) });
      await api(`/presentations/${presentationId}/outline/confirm`, { method: "POST", body: JSON.stringify({ expectedRevision: saved.revision, idempotencyKey: requestKey() }) });
      onConfirmed();
    } catch (cause) { setError((cause as Error).message); }
    finally { setSaving(false); }
  };
  return <section className="outline-editor">
    <div className="section-heading"><div><span className="step-label">第 2 步</span><h1>检查并确认大纲</h1><p>标题和正文都是最终给观众看的内容；图片描述不会进入页面。</p></div><button className="primary" onClick={() => void saveAndConfirm()} disabled={saving}>{saving ? "保存中…" : "确认大纲并继续"}</button></div>
    {error && <div className="error-banner">{error}</div>}
    <div className="outline-pages">{outline.pages.map((page, pageIndex) => <article key={page.id}>
      <b className="page-number">{String(pageIndex + 1).padStart(2, "0")}</b>
      <label>页面标题<input value={page.headline} onChange={(event) => updatePage(pageIndex, "headline", event.target.value)} /></label>
      <label>核心信息<input value={page.message} onChange={(event) => updatePage(pageIndex, "message", event.target.value)} /></label>
      {page.contentGroups.map((group, groupIndex) => <label key={group.id}>{group.label || `内容 · ${group.kind}`}<textarea value={group.items ? group.items.join("\n") : group.text ?? ""} onChange={(event) => updateGroup(pageIndex, groupIndex, event.target.value)} /></label>)}
    </article>)}</div>
  </section>;
}
