import { useEffect, useMemo, useRef, useState } from "react";
import { api, consumeStream, localizeError, localizeStatus } from "../../api/client";
import type { Presentation, PresentationOutline, TemplateItem, TemplateList } from "../../entities/types";
import { clearReturnTo, peekReturnTo, rememberReturnTo } from "../../navigation/returnTo";
import { OutlineEditor } from "../outline/OutlineEditor";
import {
  parsePartialKindergartenSlides,
  parsePartialOutlineSlides,
} from "../outline/outlineFormat";

const EDITOR_BASE =
  import.meta.env.VITE_EDITOR_BASE_URL ?? "http://127.0.0.1:5001";
const EDITOR_HOME = `${EDITOR_BASE}/dashboard`;
const EDITOR_CREATE = `${EDITOR_BASE}/upload`;

function isOutlinePath(pathname = location.pathname) {
  return /^\/presentations\/[^/]+\/outline$/.test(pathname);
}

function rememberOutlineReturn() {
  if (isOutlinePath()) rememberReturnTo();
}

export function Shell({ children }: { children: React.ReactNode }) {
  const returnTo = peekReturnTo();
  const onTemplateRoute =
    location.pathname === "/templates" || location.pathname === "/templates/new";
  const brandHref = onTemplateRoute && returnTo ? returnTo : EDITOR_HOME;

  return (
    <div className="app-shell">
      <header className="topbar">
        <a
          className="brand"
          href={brandHref}
          aria-label={onTemplateRoute && returnTo ? "返回大纲" : "返回首页"}
          onClick={() => clearReturnTo()}
        >
          <img className="brand-logo" src="/teachnova-mark.png" alt="" />
          <span className="brand-name">Teachnova</span>
          <span className="brand-product">幼教PPT</span>
        </a>
        <nav className="topnav">
          <a href="/templates" onClick={rememberOutlineReturn}>
            模板库
          </a>
          <a href="/templates/new" onClick={rememberOutlineReturn}>
            制作模板
          </a>
        </nav>
      </header>
      {children}
    </div>
  );
}

export function CreatePage() {
  useEffect(() => {
    window.location.replace(EDITOR_CREATE);
  }, []);

  return (
    <Shell>
      <main className="home-main">
        <div className="hero-copy">
          <h1>输入一个主题，生成完整幼教 PPT</h1>
        </div>
        <p style={{ marginBottom: 16, color: "#667085" }}>
          主工作台已统一到编辑器首页，正在跳转…
        </p>
        <a href={EDITOR_CREATE}>若未自动跳转，点击打开新建演示</a>
        <p style={{ marginTop: 12, color: "#98A2B3", fontSize: 13 }}>
          创建后会回到原来的大纲与排版页面
        </p>
      </main>
    </Shell>
  );
}

export function OutlinePage({ presentationId }: { presentationId: string }) {
  const [presentation, setPresentation] = useState<Presentation>();
  const [outline, setOutline] = useState<PresentationOutline>({ slides: [] });
  const [templates, setTemplates] = useState<TemplateItem[]>([]);
  const [status, setStatus] = useState("正在读取项目");
  const [error, setError] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [activeSlideIndex, setActiveSlideIndex] = useState<number | null>(null);
  const started = useRef(false);
  const outlineQuery = useMemo(() => {
    const params = new URLSearchParams(location.search);
    const templateId = params.get("template")?.trim() || null;
    const mode = params.get("mode")?.trim();
    return {
      templateId,
      createMode: (mode === "template" ? "template" : "topic") as
        | "topic"
        | "template",
    };
  }, []);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void (async () => {
      try {
        const current = await api<Presentation>(`/presentation/${presentationId}`);
        const [existingOutline, templateList] = await Promise.all([
          api<PresentationOutline>(`/outlines/${presentationId}`).catch(
            () => ({ slides: [] } as PresentationOutline),
          ),
          api<TemplateList>("/template/all?page_size=100").catch(
            () => ({ items: [], total: 0 } as TemplateList),
          ),
        ]);
        setPresentation(current);
        setTemplates(templateList.items);
        if (existingOutline.slides.length) {
          setOutline(existingOutline);
          setStatus("");
          return;
        }

        setStreaming(true);
        setStatus("AI 正在组织大纲");
        setOutline({ slides: [] });
        setActiveSlideIndex(null);
        let accumulated = "";
        const kindergartenOutline =
          current.generation_metadata?.outline_status === "pending";
        const streamPath = kindergartenOutline
          ? `/kindergarten/presentation/outline/stream/${presentationId}`
          : `/outlines/stream/${presentationId}`;
        await consumeStream(streamPath, (event) => {
          if (event.type === "status") {
            setStatus(localizeStatus(event.status));
            return;
          }
          if (event.type === "chunk") {
            accumulated += event.chunk;
            const slides = parsePartialOutlineSlides(accumulated);
            if (slides.length) {
              setOutline({ slides: slides.map((slide) => ({ ...slide })) });
              setActiveSlideIndex(Math.max(0, slides.length - 1));
              setStatus(`正在生成第 ${slides.length} 页…`);
            } else if (accumulated.trim()) {
              setStatus("正在写入大纲内容…");
            }
            return;
          }
          if (event.type === "kindergarten_chunk") {
            accumulated += event.chunk;
            const slides = parsePartialKindergartenSlides(accumulated);
            if (slides.length) {
              setOutline({ slides });
              setActiveSlideIndex(Math.max(0, slides.length - 1));
              setStatus(`正在生成第 ${slides.length} 页…`);
            }
            return;
          }
          if (event.type === "outline") {
            setOutline(event.outline);
            setActiveSlideIndex(Math.max(0, event.outline.slides.length - 1));
            return;
          }
          if (event.type === "complete" && event.presentation) {
            setPresentation(event.presentation);
          }
        });
        const finalOutline = await api<PresentationOutline>(
          `/outlines/${presentationId}`,
        );
        setOutline(finalOutline);
        setPresentation(await api<Presentation>(`/presentation/${presentationId}`));
        setActiveSlideIndex(null);
        setStreaming(false);
        setStatus("");
      } catch (cause) {
        setError(localizeError(cause));
        setStreaming(false);
        setStatus("");
      }
    })();
  }, [presentationId]);

  if (error) {
    return (
      <Shell>
        <main className="center-state">
          <h1>大纲生成失败</h1>
          <p>{error}</p>
          <a href={EDITOR_HOME}>返回首页</a>
        </main>
      </Shell>
    );
  }
  if (!presentation) {
    return (
      <Shell>
        <main className="center-state running">
          <span className="spinner" />
          <h1>{status}</h1>
        </main>
      </Shell>
    );
  }
  if (!streaming && outline.slides.length === 0) {
    return (
      <Shell>
        <main className="center-state running">
          <span className="spinner" />
          <h1>{status || "正在准备大纲"}</h1>
        </main>
      </Shell>
    );
  }
  return (
    <Shell>
      <OutlineEditor
        presentation={presentation}
        initial={outline}
        templates={templates}
        streaming={streaming}
        status={status}
        activeSlideIndex={activeSlideIndex}
        preferredTemplateId={
          presentation.generation_metadata?.selected_template ||
          outlineQuery.templateId
        }
        createMode={outlineQuery.createMode}
      />
    </Shell>
  );
}

export function GenerationPage({ presentationId }: { presentationId: string }) {
  useEffect(() => {
    location.replace(`/presentations/${presentationId}/edit?stream=true`);
  }, [presentationId]);
  return (
    <Shell>
      <main className="center-state running">
        <span className="spinner" />
        <h1>正在打开编辑器</h1>
        <p>页面将在编辑器中逐页生成</p>
      </main>
    </Shell>
  );
}
