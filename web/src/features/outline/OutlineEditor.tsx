import { useEffect, useMemo, useState } from "react";
import { api, localizeError } from "../../api/client";
import type { Presentation, PresentationOutline, TemplateItem } from "../../entities/types";
import { ArrowLeftIcon, PlusIcon, SparklesIcon } from "../../components/Icons";
import {
  outlineTitle,
  toEditableOutlineContent,
  toStoredOutlineContent,
} from "./outlineFormat";
import { resolveAutoTemplateId } from "./templateRouting";

const DEFAULT_TEMPLATE_ID = "general";
const EDITOR_BASE =
  import.meta.env.VITE_EDITOR_BASE_URL ?? "http://127.0.0.1:5001";

const DISPLAY_NAMES: Record<string, string> = {
  general: "自动匹配",
  swift: "简洁明快",
  standard: "标准清晰",
  momentum: "活力节奏",
  modern: "现代简约",
  executive: "清晰专业",
  dynamic: "灵动多彩",
};

function readOutlineQueryOptions() {
  if (typeof window === "undefined") {
    return { templateId: null as string | null, createMode: "topic" as const };
  }
  const params = new URLSearchParams(window.location.search);
  const templateId = params.get("template")?.trim() || null;
  const mode = params.get("mode")?.trim();
  return {
    templateId,
    createMode: mode === "template" ? ("template" as const) : ("topic" as const),
  };
}

function templateName(template: TemplateItem) {
  return (
    DISPLAY_NAMES[template.id] ??
    (/\?{2,}|�/.test(template.name) ? "通用模板" : template.name)
  );
}

function assetUrl(value?: string | null) {
  if (!value) return "";
  if (/^https?:\/\//i.test(value)) return value;
  const normalized = value.replace(/\\/g, "/");
  for (const prefix of ["/app_data/", "/static/"]) {
    const index = normalized.indexOf(prefix);
    if (index >= 0) return normalized.slice(index);
  }
  return normalized.startsWith("/") ? normalized : `/${normalized}`;
}

function splitTemplates(templates: TemplateItem[]) {
  const selectable = templates.filter((item) => item.id !== "general");
  return {
    custom: selectable.filter((item) => item.is_default === false),
    builtin: selectable.filter((item) => item.is_default !== false),
  };
}

export function OutlineEditor({
  presentation,
  initial,
  templates,
  streaming = false,
  status = "",
  activeSlideIndex = null,
  preferredTemplateId = null,
  createMode = "topic",
}: {
  presentation: Presentation;
  initial: PresentationOutline;
  templates: TemplateItem[];
  streaming?: boolean;
  status?: string;
  activeSlideIndex?: number | null;
  preferredTemplateId?: string | null;
  createMode?: "topic" | "template";
}) {
  const queryOptions = useMemo(() => readOutlineQueryOptions(), []);
  const resolvedCreateMode =
    createMode === "template" || queryOptions.createMode === "template"
      ? "template"
      : "topic";
  const preferred =
    preferredTemplateId || queryOptions.templateId || null;

  const [outline, setOutline] = useState(initial);
  const [selected, setSelected] = useState(0);
  const [template, setTemplate] = useState(
    preferred || (resolvedCreateMode === "template" ? "" : DEFAULT_TEMPLATE_ID),
  );
  const [stage, setStage] = useState<"outline" | "template">("outline");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setOutline(initial);
    if (streaming && typeof activeSlideIndex === "number") {
      setSelected(activeSlideIndex);
    }
  }, [initial, streaming, activeSlideIndex]);

  useEffect(() => {
    if (preferred) {
      setTemplate(preferred);
    }
  }, [preferred]);

  useEffect(() => {
    if (streaming) setStage("outline");
  }, [streaming]);

  const slides = outline.slides;
  const selectedSafe = Math.min(selected, Math.max(0, slides.length - 1));
  const current = slides[selectedSafe] ?? { content: "" };
  const editableContent = toEditableOutlineContent(current.content);
  const title = useMemo(
    () => outlineTitle(slides[0]?.content ?? presentation.title ?? "演示文稿"),
    [slides, presentation.title],
  );
  const selectableTemplates = useMemo(
    () => templates.filter((item) => item.id !== "general"),
    [templates],
  );
  const { custom, builtin } = useMemo(
    () => splitTemplates(templates),
    [templates],
  );
  const showTemplateStage =
    resolvedCreateMode === "template" && stage === "template" && !streaming;

  const updateCurrent = (content: string) => {
    if (streaming || showTemplateStage) return;
    setOutline((value) => ({
      slides: value.slides.map((slide, index) =>
        index === selectedSafe ? { content: toStoredOutlineContent(content) } : slide,
      ),
    }));
  };

  const addSlide = () => {
    if (streaming || showTemplateStage) return;
    setOutline((value) => ({
      slides: [...value.slides, { content: "## 新页面\n\n在这里填写面向观众的内容。" }],
    }));
  };

  const removeSlide = () => {
    if (streaming || showTemplateStage || outline.slides.length <= 1) return;
    setOutline((value) => ({ slides: value.slides.filter((_, index) => index !== selectedSafe) }));
    setSelected((value) => Math.max(0, value - 1));
  };

  const prepareWithLayout = async (layoutId: string) => {
    if (streaming || saving) return;
    if (!layoutId) {
      setError("请选择一个模板后再生成。");
      return;
    }
    setSaving(true);
    setError("");
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
          layout: layoutId,
          title,
        }),
      });
      location.href = `/presentations/${presentation.id}/edit?stream=true`;
    } catch (cause) {
      setError(localizeError(cause));
      setSaving(false);
    }
  };

  const goSelectTemplate = () => {
    if (streaming || saving) return;
    setError("");
    setStage("template");
  };

  const confirmTopic = async () => {
    const layoutId =
      template === DEFAULT_TEMPLATE_ID
        ? resolveAutoTemplateId(presentation, outline, templates)
        : template;
    await prepareWithLayout(layoutId || DEFAULT_TEMPLATE_ID);
  };

  const renderTemplatePickCard = (item: TemplateItem) => {
    const thumbnail = assetUrl(item.thumbnail);
    const name = templateName(item);
    const selectedCard = template === item.id;
    return (
      <button
        type="button"
        key={item.id}
        className={`outline-template-card ${selectedCard ? "active" : ""}`}
        disabled={saving}
        onClick={() => {
          setTemplate(item.id);
          void prepareWithLayout(item.id);
        }}
      >
        <div className="outline-template-thumb">
          {thumbnail ? <img src={thumbnail} alt="" /> : <span>暂无预览</span>}
          <b>{item.layout_count} 种布局</b>
        </div>
        <div className="outline-template-copy">
          <strong>{name}</strong>
          <p>{item.description || "选择此模板进行排版生成"}</p>
        </div>
      </button>
    );
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
      {!streaming && !showTemplateStage && (
        <button className="add-page" onClick={addSlide}><PlusIcon />添加一页</button>
      )}
    </aside>
    <section className="outline-canvas">
      {showTemplateStage ? (
        <>
          <header>
            <div>
              <h1>选择模板</h1>
              <p className="outline-stream-status">点选模板后将开始排版生成</p>
            </div>
            <div className="outline-actions">
              <button
                type="button"
                className="template-preview-link"
                disabled={saving}
                onClick={() => setStage("outline")}
              >
                返回大纲
              </button>
              <a
                className="template-preview-link"
                href={`${EDITOR_BASE}/custom-template`}
                target="_blank"
                rel="noreferrer"
              >
                上传新模板
              </a>
            </div>
          </header>
          <div className="outline-template-stage">
            <section>
              <h2>我的模板</h2>
              <p>老师自行上传，仅当前账号可见</p>
              <div className="outline-template-grid">
                <a
                  className="outline-template-upload"
                  href={`${EDITOR_BASE}/custom-template`}
                  target="_blank"
                  rel="noreferrer"
                >
                  <span>+</span>
                  <b>上传新模板</b>
                  <small>上传 PPTX 制作个人模板</small>
                </a>
                {custom.map(renderTemplatePickCard)}
              </div>
            </section>
            <section>
              <h2>内置模板</h2>
              <p>由平台提供，所有用户可见可用</p>
              <div className="outline-template-grid">
                {builtin.map(renderTemplatePickCard)}
              </div>
            </section>
          </div>
          {error && <div className="error-line">{error}</div>}
        </>
      ) : (
        <>
          <header>
            <div>
              <h1>{title || "正在生成大纲"}</h1>
              {streaming && <p className="outline-stream-status">{status || "AI 正在逐页生成大纲"}</p>}
              {!streaming && resolvedCreateMode === "template" && (
                <p className="outline-stream-status">大纲确认后，下一步选择模板进行排版</p>
              )}
            </div>
            <div className="outline-actions">
              {resolvedCreateMode === "topic" ? (
                <>
                  <label>
                    模板
                    <select
                      value={template}
                      disabled={streaming || saving}
                      onChange={(event) => setTemplate(event.target.value)}
                    >
                      <option value="general">自动匹配</option>
                      {selectableTemplates.map((item) => (
                        <option value={item.id} key={item.id}>
                          {templateName(item)} · {item.layout_count} 种布局
                        </option>
                      ))}
                    </select>
                  </label>
                  <a className="template-preview-link" href="/templates" target="_blank" rel="noreferrer">
                    预览模板
                  </a>
                  <button className="primary" disabled={saving || streaming} onClick={() => void confirmTopic()}>
                    <SparklesIcon />{streaming ? "生成中…" : saving ? "正在准备…" : "确认生成"}
                  </button>
                </>
              ) : (
                <button
                  className="primary"
                  disabled={saving || streaming || slides.length === 0}
                  onClick={goSelectTemplate}
                >
                  <SparklesIcon />
                  {streaming ? "生成中…" : "下一步：选择模板"}
                </button>
              )}
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
        </>
      )}
    </section>
  </main>;
}