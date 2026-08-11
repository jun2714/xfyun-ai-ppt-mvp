import { useEffect, useMemo, useState } from "react";
import { api, localizeError } from "../../api/client";
import type { TemplateItem, TemplateList } from "../../entities/types";
import { Shell } from "../create/CreateAndGenerate";

const DISPLAY_NAMES: Record<string, string> = {
  dynamic: "动感橙黑",
  executive: "柔光紫",
  general: "清爽白紫",
  modern: "现代蓝",
  momentum: "商务蓝",
  standard: "经典图文",
  swift: "简洁青蓝",
};

const DISPLAY_DESCRIPTIONS: Record<string, string> = {
  dynamic: "深色高对比、暖橙强调，适合故事化和强视觉表达。",
  executive: "明亮留白与柔和紫色强调，适合清晰、正式的内容。",
  general: "通用白底图文布局，结构简单，适合多数演示主题。",
  modern: "现代留白和蓝色强调，适合简洁的图文展示。",
  momentum: "大字号和流动蓝色装饰，适合节奏明确的汇报。",
  standard: "经典大图与正文组合，适合稳定、清楚地讲述内容。",
  swift: "轻量图文布局和青蓝点缀，适合短篇演示。",
};

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

function TemplateCard({ template }: { template: TemplateItem }) {
  const thumbnail = assetUrl(template.thumbnail);
  const displayName = DISPLAY_NAMES[template.id] ?? template.name;
  const previewBase = import.meta.env.VITE_EDITOR_BASE_URL ?? "http://127.0.0.1:5001";
  const previewUrl = `${previewBase}/template-preview?templateV2Id=${encodeURIComponent(template.id)}`;

  return <a className="template-card" href={previewUrl} target="_blank" rel="noreferrer">
    <div className="template-thumbnail">
      {thumbnail ? <img src={thumbnail} alt={`${displayName}模板预览`} /> : <span>暂无预览</span>}
      <b>{template.layout_count} 种布局</b>
    </div>
    <div className="template-card-copy">
      <h2>{displayName}</h2>
      <p>{DISPLAY_DESCRIPTIONS[template.id] || template.description || "查看模板包含的页面布局与视觉样式"}</p>
      <span>查看模板 →</span>
    </div>
  </a>;
}

export function TemplateLibrary() {
  const [templates, setTemplates] = useState<TemplateItem[]>([]);
  const [tab, setTab] = useState<"built-in" | "custom">("built-in");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    void api<TemplateList>("/template/all?page_size=100")
      .then((result) => setTemplates(result.items))
      .catch((cause: Error) => setError(localizeError(cause)))
      .finally(() => setLoading(false));
  }, []);

  const visibleTemplates = useMemo(
    () => templates.filter((template) => tab === "built-in" ? template.is_default !== false : template.is_default === false),
    [tab, templates],
  );

  return <Shell><main className="templates-page">
    <header className="templates-heading">
      <div><span>模板中心</span><h1>选择一套合适的设计</h1><p>模板只决定视觉和布局，不限制你的主题、页数和内容结构。</p></div>
      <a className="primary" href="/templates/new">制作模板 <i>→</i></a>
    </header>
    <nav className="template-tabs" aria-label="模板分类">
      <button className={tab === "built-in" ? "active" : ""} onClick={() => setTab("built-in")}>内置模板</button>
      <button className={tab === "custom" ? "active" : ""} onClick={() => setTab("custom")}>我的模板</button>
    </nav>
    {loading && <div className="template-state">正在加载模板…</div>}
    {error && <div className="template-state error-line">{error}</div>}
    {!loading && !error && visibleTemplates.length === 0 && <div className="template-state">{tab === "custom" ? "还没有自定义模板，可从右上角开始制作。" : "暂无可用模板。"}</div>}
    <section className="template-grid">{visibleTemplates.map((template) => <TemplateCard key={template.id} template={template} />)}</section>
  </main></Shell>;
}

export function TemplateBuilder() {
  const base = import.meta.env.VITE_EDITOR_BASE_URL ?? "http://127.0.0.1:5001";
  return <Shell><main className="template-builder-page">
    <iframe title="制作模板" src={`${base}/custom-template?embed=teachnova`} />
  </main></Shell>;
}
