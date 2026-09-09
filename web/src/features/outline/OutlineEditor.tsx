import { useEffect, useMemo, useState } from "react";
import { api, localizeError } from "../../api/client";
import type { Presentation, PresentationOutline, TemplateItem } from "../../entities/types";
import { ArrowLeftIcon, PlusIcon, SparklesIcon } from "../../components/Icons";
import {
  outlineTitle,
  toEditableOutlineContent,
  toStoredOutlineContent,
} from "./outlineFormat";
import "./outlineProgress.css";

const DEFAULT_TEMPLATE_ID = "general";
const AI_VISUAL_TEMPLATE_ID = "ai-visual";
const EDITOR_BASE =
  import.meta.env.VITE_EDITOR_BASE_URL ?? "http://127.0.0.1:5001";

const DISPLAY_NAMES: Record<string, string> = {
  general: "自动匹配",
  "ai-visual": "AI 自由视觉",
  "kindergarten-classroom": "幼教课堂 · 绘本与观察",
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

function isVisibleTemplate(item: TemplateItem) {
  return item.id !== DEFAULT_TEMPLATE_ID && item.id !== AI_VISUAL_TEMPLATE_ID;
}

function splitTemplates(templates: TemplateItem[]) {
  const selectable = templates.filter(isVisibleTemplate);
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
  const preferred = preferredTemplateId || queryOptions.templateId || null;

  const [outline, setOutline] = useState(initial);
  const [selected, setSelected] = useState(0);
  const [template, setTemplate] = useState(preferred || "");
  const [stage, setStage] = useState<"outline" | "template">("outline");
  const [saving, setSaving] = useState(false);
  const [aiEditing, setAiEditing] = useState<"polish" | "regenerate" | null>(null);
  const [templatePreviewOpen, setTemplatePreviewOpen] = useState(false);
  const [error, setError] = useState("");
  const [templateNotice, setTemplateNotice] = useState("");

  useEffect(() => {
    setOutline(initial);
    if (streaming && typeof activeSlideIndex === "number") {
      setSelected(activeSlideIndex);
    }
  }, [initial, streaming, activeSlideIndex]);

  useEffect(() => {
    if (!preferred) return;
    if (preferred === AI_VISUAL_TEMPLATE_ID || templates.some((item) => item.id === preferred)) {
      setTemplate(preferred);
      setTemplateNotice("");
      return;
    }
    if (templates.length === 0) return;

    const fallback =
      templates.find((item) => item.id === "standard") ??
      templates.find((item) => isVisibleTemplate(item) && item.is_default !== false) ??
      templates.find(isVisibleTemplate);
    const preferredName = DISPLAY_NAMES[preferred] || preferred;
    if (fallback) {
      setTemplate(fallback.id);
      setTemplateNotice(
        `自动推荐的“${preferredName}”当前未加载，已切换为“${templateName(fallback)}”。你也可以重新选择模板。`,
      );
    } else {
      setTemplate("");
      setTemplateNotice(
        `自动推荐的“${preferredName}”当前不可用，请先选择一个已加载的模板。`,
      );
    }
  }, [preferred, templates]);

  useEffect(() => {
    if (streaming) setStage("outline");
  }, [streaming]);

  useEffect(() => {
    if (!templatePreviewOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [templatePreviewOpen]);

  const slides = outline.slides;
  const selectedSafe = Math.min(selected, Math.max(0, slides.length - 1));
  const current = slides[selectedSafe] ?? { content: "" };
  const editableContent = toEditableOutlineContent(current.content);
  const teacherNote = typeof current.content_contract?.teacher_note === "string"
    ? current.content_contract.teacher_note : "";
  const interactionInstruction = typeof current.content_contract?.interaction_instruction === "string"
    ? current.content_contract.interaction_instruction : "";
  const updateTeacherField = (key: "teacher_note" | "interaction_instruction", text: string) => {
    if (streaming || showTemplateStage) return;
    setOutline((value) => ({ slides: value.slides.map((slide, index) => index === selectedSafe
      ? { ...slide, content_contract: { ...slide.content_contract, [key]: text } } : slide) }));
  };
  const title = useMemo(
    () => outlineTitle(slides[0]?.content ?? presentation.title ?? "演示文稿"),
    [slides, presentation.title],
  );
  const selectableTemplates = useMemo(
    () => templates.filter(isVisibleTemplate),
    [templates],
  );
  const availableTemplateIds = useMemo(
    () => new Set(templates.map((item) => item.id)),
    [templates],
  );
  const { custom, builtin } = useMemo(
    () => splitTemplates(templates),
    [templates],
  );
  const showTemplateStage =
    resolvedCreateMode === "template" && stage === "template" && !streaming;
  const templateIsActuallyAvailable =
    template === AI_VISUAL_TEMPLATE_ID || availableTemplateIds.has(template);
  const hasResolvedTemplate =
    Boolean(template) &&
    ![DEFAULT_TEMPLATE_ID, "auto"].includes(template) &&
    templateIsActuallyAvailable;
  const expectedSlides = Math.max(presentation.n_slides || 0, slides.length);
  const activeTitle =
    typeof activeSlideIndex === "number"
      ? outlineTitle(slides[activeSlideIndex]?.content ?? "")
      : "";

  const updateCurrent = (content: string) => {
    if (streaming || showTemplateStage) return;
    setOutline((value) => ({
      slides: value.slides.map((slide, index) =>
        index === selectedSafe
          ? { ...slide, content: toStoredOutlineContent(content) }
          : slide,
      ),
    }));
  };

  const rewriteCurrentWithAi = async (mode: "polish" | "regenerate") => {
    if (streaming || saving || aiEditing || !current.content) return;
    setAiEditing(mode);
    setError("");
    const action =
      mode === "polish"
        ? "润色并压缩本页：保持原意和事实，标题更明确，正文分层清楚，删除重复表达；可见中文控制在120字以内，并确保适合当前PPT版式。"
        : "重新生成本页：依据整份演示主题、相邻页面和本页教学目标重写，不偏离用户原始问题；给出具体事实、解决动作或验证指标，可见中文控制在140字以内。";
    try {
      await api("/chat/message", {
        method: "POST",
        body: JSON.stringify({
          presentation_id: presentation.id,
          presentation_type: "standard",
          message:
            `${action}\n必须调用 updateOutline 工具，只替换零基索引 ${selectedSafe} 的大纲内容，` +
            `不要新增、删除或修改其他页面。\n当前内容：\n${current.content}`,
          attachments: [],
        }),
      });
      const generated = await api<PresentationOutline>(`/outlines/${presentation.id}`);
      const generatedContent = generated.slides[selectedSafe]?.content?.trim();
      if (!generatedContent || generatedContent === current.content.trim()) {
        throw new Error("AI 未返回新的本页内容，请重试。");
      }

      const visibleLines = toEditableOutlineContent(generatedContent)
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean);
      const titleLine = (visibleLines[0] || "未命名页面").replace(/^•\s*/, "");
      const pointLines = visibleLines.slice(1).map((line) => line.replace(/^•\s*/, ""));
      const oldContract = current.content_contract || {};
      const oldAssets = Array.isArray(oldContract.asset_contracts)
        ? oldContract.asset_contracts
        : [];
      const backgroundAssets = oldAssets.filter(
        (asset) =>
          asset &&
          typeof asset === "object" &&
          (asset as Record<string, unknown>).role === "background",
      );
      const nextContract = {
        ...oldContract,
        preserve_visible_copy: true,
        screen_title: titleLine,
        screen_points: pointLines,
        screen_instruction: null,
        visible_characters: visibleLines.join("").length,
        required_asset_semantics: backgroundAssets
          .map((asset) => (asset as Record<string, unknown>).semantic_label)
          .filter((value): value is string => typeof value === "string"),
        asset_contracts: backgroundAssets,
      };
      const nextOutline: PresentationOutline = {
        slides: outline.slides.map((slide, index) =>
          index === selectedSafe
            ? {
                ...slide,
                content: toStoredOutlineContent(generatedContent),
                content_contract: nextContract,
              }
            : slide,
        ),
      };
      const saved = await api<PresentationOutline>(`/outlines/${presentation.id}`, {
        method: "PUT",
        body: JSON.stringify(nextOutline),
      });
      setOutline(saved);
    } catch (cause) {
      setError(localizeError(cause));
    } finally {
      setAiEditing(null);
    }
  };

  const addSlide = () => {
    if (streaming || showTemplateStage) return;
    setOutline((value) => ({
      slides: [...value.slides, { content: "## 新页面\n\n在这里填写面向观众的内容。" }],
    }));
  };

  const removeSlide = () => {
    if (streaming || showTemplateStage || outline.slides.length <= 1) return;
    setOutline((value) => ({
      slides: value.slides.filter((_, index) => index !== selectedSafe),
    }));
    setSelected((value) => Math.max(0, value - 1));
  };

  const prepareWithLayout = async (layoutId: string) => {
    if (streaming || saving) return;
    if (!layoutId || [DEFAULT_TEMPLATE_ID, "auto"].includes(layoutId)) {
      setError("自动模板匹配尚未完成，请重新选择一个可用模板。");
      return;
    }
    if (layoutId !== AI_VISUAL_TEMPLATE_ID && !availableTemplateIds.has(layoutId)) {
      setError("所选模板当前不可用，请重新选择一个已加载的模板。");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const stored: PresentationOutline = {
        // content_contract is hidden machine metadata created by the kindergarten
        // planner. Preserve it while the teacher edits visible copy; otherwise
        // question/reveal locks, image semantics and teacher notes disappear just
        // before layout/asset generation.
        slides: outline.slides.map((slide) => ({
          ...slide,
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
    await prepareWithLayout(template);
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
          setTemplateNotice("");
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
              <h1>{streaming ? "正在生成大纲" : title || "演示文稿大纲"}</h1>
              {streaming && (
                <p className="outline-stream-status">
                  {status || "AI 正在逐页生成大纲"}
                </p>
              )}
              {!streaming && resolvedCreateMode === "template" && (
                <p className="outline-stream-status">大纲确认后，下一步选择模板进行排版</p>
              )}
            </div>
            <div className="outline-actions">
              {resolvedCreateMode === "topic" ? (
                <>
                  <label>
                    视觉方案
                    <select
                      value={template}
                      disabled={streaming || saving || template === AI_VISUAL_TEMPLATE_ID}
                      onChange={(event) => {
                        setTemplate(event.target.value);
                        setTemplateNotice("");
                        setError("");
                      }}
                    >
                      {template === AI_VISUAL_TEMPLATE_ID ? (
                        <option value={AI_VISUAL_TEMPLATE_ID}>AI 自由视觉</option>
                      ) : (
                        <>
                          {!hasResolvedTemplate && (
                            <option value="">
                              {streaming ? "正在自动匹配模板…" : "请选择可用模板…"}
                            </option>
                          )}
                          {selectableTemplates.map((item) => (
                            <option value={item.id} key={item.id}>
                              {templateName(item)} · {item.layout_count} 种布局
                            </option>
                          ))}
                        </>
                      )}
                    </select>
                  </label>
                  <button
                    type="button"
                    className="template-preview-link"
                    onClick={() => setTemplatePreviewOpen(true)}
                  >
                    预览模板
                  </button>
                  <button
                    className="primary"
                    disabled={saving || streaming || !hasResolvedTemplate}
                    onClick={() => void confirmTopic()}
                  >
                    <SparklesIcon />
                    {streaming ? "生成中…" : saving ? "正在准备…" : "确认生成"}
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

          {streaming ? (
            <div className="outline-work-panel" role="status" aria-live="polite">
              <span className="outline-work-spinner" aria-hidden="true" />
              <div className="outline-work-copy">
                <strong>AI 正在构思课堂大纲</strong>
                <p>{status || "正在组织教学目标与页面结构…"}</p>
                <div className="outline-work-feed">
                  <span>已读取主题、年龄段和课堂要求</span>
                  <span>
                    {slides.length
                      ? `已展开 ${slides.length}${expectedSlides ? ` / ${expectedSlides}` : ""} 页大纲`
                      : "正在规划页面顺序与教学节奏"}
                  </span>
                  {typeof activeSlideIndex === "number" && (
                    <span>
                      正在写入第 {activeSlideIndex + 1} 页
                      {activeTitle && activeTitle !== "未命名页面" ? `：${activeTitle}` : ""}
                    </span>
                  )}
                  <span>完成后会检查页面衔接，再交由你确认</span>
                </div>
              </div>
              <span className="outline-work-meta">
                {expectedSlides
                  ? `${Math.min(slides.length, expectedSlides)} / ${expectedSlides} 页`
                  : `${slides.length} 页`}
              </span>
            </div>
          ) : slides.length > 0 ? (
            <div className="outline-complete-banner" role="status">
              <span className="outline-complete-icon" aria-hidden="true">✓</span>
              <div className="outline-complete-copy">
                <strong>大纲已生成完成</strong>
                <p>可以继续修改内容，也可以选择视觉方案或模板后开始生成 PPT。</p>
                {templateNotice && (
                  <p className="outline-template-notice">{templateNotice}</p>
                )}
              </div>
              <div className="outline-complete-actions">
                <button
                  type="button"
                  className="outline-secondary-action"
                  onClick={() => setTemplatePreviewOpen(true)}
                >
                  查看模板
                </button>
                {resolvedCreateMode === "topic" ? (
                  <button
                    className="primary"
                    disabled={saving || !hasResolvedTemplate}
                    onClick={() => void confirmTopic()}
                  >
                    <SparklesIcon />
                    {saving ? "正在准备…" : "确认并生成"}
                  </button>
                ) : (
                  <button className="primary" disabled={saving} onClick={goSelectTemplate}>
                    <SparklesIcon />选择模板并生成
                  </button>
                )}
              </div>
            </div>
          ) : null}

          <div className={`outline-editor-flat ${streaming && activeSlideIndex === selectedSafe ? "is-streaming" : ""}`}>
            <div className="page-meta">
              <b>第 {selectedSafe + 1} 页</b>
              <span>{editableContent.length} 字</span>
              {streaming
                ? <span className="stream-badge">{activeSlideIndex === selectedSafe ? "正在写入" : "已生成"}</span>
                : <>
                    <button
                      type="button"
                      className="outline-ai-action"
                      disabled={Boolean(aiEditing) || saving}
                      onClick={() => void rewriteCurrentWithAi("polish")}
                    >
                      {aiEditing === "polish" ? "润色中…" : "AI 润色本页"}
                    </button>
                    <button
                      type="button"
                      className="outline-ai-action"
                      disabled={Boolean(aiEditing) || saving}
                      onClick={() => void rewriteCurrentWithAi("regenerate")}
                    >
                      {aiEditing === "regenerate" ? "生成中…" : "重新生成本页"}
                    </button>
                    <button onClick={removeSlide} disabled={outline.slides.length <= 1 || Boolean(aiEditing)}>删除此页</button>
                  </>}
            </div>
            <textarea
              aria-label="儿童屏幕内容"
              value={editableContent}
              readOnly={streaming}
              onChange={(event) => updateCurrent(event.target.value)}
              placeholder={streaming ? "内容正在流入…" : "在这里编辑本页大纲"}
            />
          </div>
          {!streaming && current.content_contract && (
            <details className="outline-teacher-notes">
              <summary>教师讲稿与课堂操作（不会投到儿童屏幕）</summary>
              <label>教师讲稿
                <textarea aria-label="教师讲稿" value={teacherNote} maxLength={1200}
                  onChange={(event) => updateTeacherField("teacher_note", event.target.value)} />
              </label>
              <label>课堂操作步骤
                <textarea aria-label="课堂操作步骤" value={interactionInstruction} maxLength={180}
                  onChange={(event) => updateTeacherField("interaction_instruction", event.target.value)} />
              </label>
            </details>
          )}
          {error && (
            <div className="error-line">
              {error}
              {/放不进|文字|容量|fit|layout/i.test(error) && !streaming ? (
                <button
                  type="button"
                  onClick={() => void rewriteCurrentWithAi("polish")}
                  disabled={Boolean(aiEditing)}
                >
                  AI 自动精简当前页
                </button>
              ) : null}
            </div>
          )}
        </>
      )}
    </section>
    {templatePreviewOpen && (
      <div className="outline-template-modal" role="dialog" aria-modal="true" aria-label="模板预览">
        <div className="outline-template-modal-bar">
          <strong>模板预览</strong>
          <button type="button" onClick={() => setTemplatePreviewOpen(false)}>
            ← 返回大纲
          </button>
        </div>
        <iframe title="模板库预览" src="/templates?embed=outline-preview" />
      </div>
    )}
  </main>;
}
