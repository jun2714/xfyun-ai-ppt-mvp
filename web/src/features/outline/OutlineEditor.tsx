import { useMemo, useState } from "react";
import { api, localizeError } from "../../api/client";
import type { Presentation, PresentationOutline, TemplateItem } from "../../entities/types";

function outlineTitle(content: string) {
  return content.split("\n").find((line) => line.trim())?.replace(/^#+\s*/, "").trim() || "未命名页面";
}

function templateName(template: TemplateItem) {
  const names: Record<string, string> = {
    general: "自动匹配",
    swift: "简洁明快",
    standard: "标准清晰",
    momentum: "活力节奏",
    modern: "现代简约",
    executive: "清晰专业",
    dynamic: "灵动多彩",
  };
  return names[template.id] ?? (/\?{2,}|�/.test(template.name) ? "通用模板" : template.name);
}

export function OutlineEditor({ presentation, initial, templates }: { presentation: Presentation; initial: PresentationOutline; templates: TemplateItem[] }) {
  const [outline, setOutline] = useState(initial);
  const [selected, setSelected] = useState(0);
  const [template, setTemplate] = useState("general");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const current = outline.slides[selected] ?? { content: "" };
  const title = useMemo(() => outlineTitle(outline.slides[0]?.content ?? presentation.title ?? "演示文稿"), [outline, presentation.title]);

  const updateCurrent = (content: string) => setOutline((value) => ({
    slides: value.slides.map((slide, index) => index === selected ? { content } : slide),
  }));
  const addSlide = () => setOutline((value) => ({ slides: [...value.slides, { content: "## 新页面\n\n在这里填写面向观众的内容。" }] }));
  const removeSlide = () => {
    if (outline.slides.length <= 1) return;
    setOutline((value) => ({ slides: value.slides.filter((_, index) => index !== selected) }));
    setSelected((value) => Math.max(0, value - 1));
  };
  const confirm = async () => {
    setSaving(true); setError("");
    try {
      const saved = await api<PresentationOutline>(`/outlines/${presentation.id}`, { method: "PUT", body: JSON.stringify(outline) });
      await api("/presentation/prepare", { method: "POST", body: JSON.stringify({
        presentation_id: presentation.id,
        outlines: saved.slides,
        layout: template,
        title,
      }) });
      location.href = `/presentations/${presentation.id}/generate`;
    } catch (cause) { setError(localizeError(cause)); setSaving(false); }
  };

  return <main className="outline-layout">
    <aside className="outline-sidebar"><header><a href="/">← 返回首页</a><b>大纲</b></header>
      <div className="outline-list">{outline.slides.map((slide, index) => <button className={index === selected ? "active" : ""} key={`${index}-${outlineTitle(slide.content)}`} onClick={() => setSelected(index)}>
        <span>{String(index + 1).padStart(2, "0")}</span><b>{outlineTitle(slide.content)}</b>
      </button>)}</div>
      <button className="add-page" onClick={addSlide}>＋ 添加一页</button>
    </aside>
    <section className="outline-canvas"><header><div><h1>{title}</h1></div>
      <div className="outline-actions"><label>模板<select value={template} onChange={(event) => setTemplate(event.target.value)}><option value="general">自动匹配</option>{templates.filter((item) => item.id !== "general").map((item) => <option value={item.id} key={item.id}>{templateName(item)} · {item.layout_count} 种布局</option>)}</select></label><button className="primary" disabled={saving} onClick={() => void confirm()}>{saving ? "正在准备…" : "确认生成"} →</button></div>
    </header>
    <div className="outline-editor-flat"><div className="page-meta"><b>第 {selected + 1} 页</b><span>{current.content.length} 字</span><button onClick={removeSlide} disabled={outline.slides.length <= 1}>删除此页</button></div>
      <textarea value={current.content} onChange={(event) => updateCurrent(event.target.value)} />
    </div>
    {error && <div className="error-line">{error}</div>}
    </section>
  </main>;
}
