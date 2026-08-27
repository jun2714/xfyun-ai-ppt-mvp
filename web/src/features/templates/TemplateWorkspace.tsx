import { useEffect, useMemo, useState } from "react";
import { api, localizeError } from "../../api/client";
import type { TemplateItem, TemplateList } from "../../entities/types";
import { clearReturnTo, peekReturnTo } from "../../navigation/returnTo";
import { Shell } from "../create/CreateAndGenerate";
import { ArrowLeftIcon, ArrowRightIcon } from "../../components/Icons";

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
  const displayName = template.name;
  const previewBase = import.meta.env.VITE_EDITOR_BASE_URL ?? "http://127.0.0.1:5001";
  const previewUrl = `${previewBase}/template-preview?templateV2Id=${encodeURIComponent(template.id)}`;

  return <a className="template-card" href={previewUrl} target="_blank" rel="noreferrer">
    <div className="template-thumbnail">
      {thumbnail ? <img src={thumbnail} alt={`${displayName}模板预览`} /> : <span>暂无预览</span>}
      <b>{template.layout_count} 种布局</b>
    </div>
    <div className="template-card-copy">
      <h2>{displayName}</h2>
      <p>{template.description || "查看模板包含的页面布局与视觉样式"}</p>
      <span>查看模板 <ArrowRightIcon /></span>
    </div>
  </a>;
}

function TemplateReturnLink() {
  const returnTo = peekReturnTo();
  if (!returnTo) return null;
  return <a className="template-return-link" href={returnTo} onClick={() => clearReturnTo()}>
    <ArrowLeftIcon />返回大纲
  </a>;
}

export function TemplateLibrary() {
  const [templates, setTemplates] = useState<TemplateItem[]>([]);
  const [tab, setTab] = useState<"built-in" | "custom">(() => {
    if (typeof window === "undefined") return "built-in";
    return new URLSearchParams(window.location.search).get("tab") === "custom"
      ? "custom"
      : "built-in";
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    void api<TemplateList>("/template/all?page_size=100")
      .then((result) => setTemplates(result.items))
      .catch((cause: Error) => setError(localizeError(cause)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const url = new URL(window.location.href);
    if (tab === "custom") url.searchParams.set("tab", "custom");
    else url.searchParams.delete("tab");
    window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
  }, [tab]);

  const visibleTemplates = useMemo(
    () => templates.filter((template) => tab === "built-in" ? template.is_default !== false : template.is_default === false),
    [tab, templates],
  );

  return <Shell><main className="templates-page">
    <header className="templates-heading">
      <div>
        <TemplateReturnLink />
        <span>模板中心</span>
        <h1>选择一套合适的设计</h1>
        <p>模板只决定视觉和布局，不限制你的主题、页数和内容结构。</p>
      </div>
      <a className="primary" href="/templates/new">制作模板 <ArrowRightIcon /></a>
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
  const fastApiUrl = import.meta.env.VITE_ENGINE_API_URL ?? "http://127.0.0.1:8000";
  const studioUrl = `${base}/custom-template?embed=teachnova&fastapiUrl=${encodeURIComponent(fastApiUrl)}`;
  return <Shell><main className="template-builder-page">
    <div className="template-builder-toolbar"><TemplateReturnLink /></div>
    <section className="template-upload-guide" aria-label="模板上传说明">
      <div>
        <strong>上传可编辑的 PPTX</strong>
        <span>建议先删除版权说明页、示例文案和不需要的版式；扫描版 PDF 或整页图片不能直接成为可编辑模板。</span>
      </div>
      <ol>
        <li><b>1</b>检查并补齐字体</li>
        <li><b>2</b>确认逐页预览</li>
        <li><b>3</b>生成可复用布局</li>
        <li><b>4</b>命名后保存到“我的模板”</li>
      </ol>
    </section>
    <iframe title="制作模板" src={studioUrl} />
  </main></Shell>;
}
