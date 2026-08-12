import { useEffect, useMemo, useState } from "react";
import { api, localizeError } from "../../api/client";
import type { Presentation, PresentationOutline, TemplateItem } from "../../entities/types";
import { ArrowLeftIcon, PlusIcon, SparklesIcon } from "../../components/Icons";
import {
  outlineTitle,
  toEditableOutlineContent,
  toStoredOutlineContent,
} from "./outlineFormat";

const DEFAULT_TEMPLATE_ID = "general";

export function OutlineEditor({
  presentation,
  initial,
  templates: _templates,
  streaming = false,
  status = "",
  activeSlideIndex = null,
}: {
  presentation: Presentation;
  initial: PresentationOutline;
  templates: TemplateItem[];
  streaming?: boolean;
  status?: string;
  activeSlideIndex?: number | null;
}) {
  const [outline, setOutline] = useState(initial);
  const [selected, setSelected] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setOutline(initial);
    if (streaming && typeof activeSlideIndex === "number") {
      setSelected(activeSlideIndex);
    }
  }, [initial, streaming, activeSlideIndex]);

  const slides = outline.slides;
  const selectedSafe = Math.min(selected, Math.max(0, slides.length - 1));
  const current = slides[selectedSafe] ?? { content: "" };
  const editableContent = toEditableOutlineContent(current.content);
  const title = useMemo(
    () => outlineTitle(slides[0]?.content ?? presentation.title ?? "演示文稿"),
    [slides, presentation.title],
  );

  const updateCurrent = (content: string) => {
    if (streaming) return;
    setOutline((value) => ({
      slides: value.slides.map((slide, index) =>
        index === selectedSafe ? { content: toStoredOutlineContent(content) } : slide,
      ),
    }));
  };

  const addSlide = () => {
    if (streaming) return;
    setOutline((value) => ({
      slides: [...value.slides, { content: "## 新页面\n\n在这里填写面向观众的内容。" }],
    }));
  };

  const removeSlide = () => {
    if (streaming || outline.slides.length <= 1) return;
    setOutline((value) => ({ slides: value.slides.filter((_, index) => index !== selectedSafe) }));
    setSelected((value) => Math.max(0, value - 1));
  };

  const confirm = async () => {
    if (streaming) return;
    setSaving(true); setError("");
    try {
      const stored: PresentationOutline = {
        slides: outline.slides.map((slide) => ({
          content: toStoredOutlineContent(toEditableOutlineContent(slide.content)),
        })),
      };
      const saved = await api<PresentationOutline>(`/outlines/${presentation.id}`, {
        method: "PUT",
        body: JSON.stringify(stored),
      });
      await api("/presentation/prepare", {
        method: "POST",
        body: JSON.stringify({
          presentation_id: presentation.id,
          outlines: saved.slides,
          layout: DEFAULT_TEMPLATE_ID,
          title,
        }),
      });
      location.href = `/presentations/${presentation.id}/edit?stream=true`;
    } catch (cause) {
      setError(localizeError(cause));
      setSaving(false);
    }
  };

  return <main className="outline-layout">
    <aside className="outline-sidebar">
      <header><a href="/"><ArrowLeftIcon />返回首页</a><b>大纲</b></header>
      <div className="outline-list">
        {slides.map((slide, index) => {
          const writing = streaming && activeSlideIndex === index;
          return <button
            className={`${index === selectedSafe ? "active" : ""} ${writing ? "writing" : ""}`}
            key={`${index}-${outlineTitle(slide.content)}`}
            onClick={() => setSelected(index)}
          >
            <span>{String(index + 1).padStart(2, "0")}</span>
            <b>{outlineTitle(slide.content) || (writing ? "正在生成…" : "未命名页面")}</b>
          </button>;
        })}
        {streaming && slides.length === 0 && (
          <div className="outline-stream-hint">正在构思页面结构…</div>
        )}
      </div>
      {!streaming && <button className="add-page" onClick={addSlide}><PlusIcon />添加一页</button>}
    </aside>
    <section className="outline-canvas">
      <header>
        <div>
          <h1>{title || "正在生成大纲"}</h1>
          {streaming && <p className="outline-stream-status">{status || "AI 正在逐页生成大纲"}</p>}
        </div>
        <div className="outline-actions">
          <button className="primary" disabled={saving || streaming} onClick={() => void confirm()}>
            <SparklesIcon />{streaming ? "生成中…" : saving ? "正在准备…" : "确认生成"}
          </button>
        </div>
      </header>
      <div className={`outline-editor-flat ${streaming && activeSlideIndex === selectedSafe ? "is-streaming" : ""}`}>
        <div className="page-meta">
          <b>第 {selectedSafe + 1} 页</b>
          <span>{editableContent.length} 字</span>
          {streaming
            ? <span className="stream-badge">{activeSlideIndex === selectedSafe ? "正在写入" : "已生成"}</span>
            : <button onClick={removeSlide} disabled={outline.slides.length <= 1}>删除此页</button>}
        </div>
        <textarea
          value={editableContent}
          readOnly={streaming}
          onChange={(event) => updateCurrent(event.target.value)}
          placeholder={streaming ? "内容正在流入…" : "在这里编辑本页大纲"}
        />
      </div>
      {error && <div className="error-line">{error}</div>}
    </section>
  </main>;
}
