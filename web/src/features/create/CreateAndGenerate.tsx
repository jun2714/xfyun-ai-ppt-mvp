import { useEffect, useRef, useState } from "react";
import { api, consumeStream, localizeError, localizeStatus } from "../../api/client";
import type { Presentation, PresentationOutline, TemplateItem, TemplateList } from "../../entities/types";
import { OutlineEditor } from "../outline/OutlineEditor";
import { ArrowRightIcon, CopyIcon, MoreVerticalIcon, SparklesIcon, TrashIcon } from "../../components/Icons";

function projectTitle(item: Presentation) {
  return item.title || item.content.split("\n")[0]?.replace("主题：", "") || "未命名演示";
}

export function Shell({ children }: { children: React.ReactNode }) {
  return <div className="app-shell">
    <header className="topbar">
      <a className="brand" href="/">
        <img className="brand-logo" src="/teachnova-mark.png" alt="" />
        <span className="brand-name">Teachnova</span>
        <span className="brand-product">幼教PPT</span>
      </a>
      <nav className="topnav"><a href="/templates">模板库</a><a href="/templates/new">制作模板</a></nav>
    </header>
    {children}
  </div>;
}

export function CreatePage() {
  const [presentations, setPresentations] = useState<Presentation[]>([]);
  const [topic, setTopic] = useState("");
  const [audience, setAudience] = useState("");
  const [age, setAge] = useState("");
  const [scene, setScene] = useState("");
  const [goal, setGoal] = useState("");
  const [style, setStyle] = useState("");
  const [slideCount, setSlideCount] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [projectError, setProjectError] = useState("");
  const [pendingProjectId, setPendingProjectId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Presentation | null>(null);

  useEffect(() => {
    void api<Presentation[]>("/presentation/all?include_slides=true&version=v2-standard")
      .then(setPresentations).catch((cause: Error) => setError(localizeError(cause)));
  }, []);

  const create = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true); setError("");
    const brief = [
      `主题：${topic.trim()}`,
      `观众：${audience.trim()}${age.trim() ? `，${age.trim()}` : ""}`,
      `使用场景：${scene.trim()}`,
      goal.trim() ? `演示目标：${goal.trim()}` : "",
      style.trim() ? `视觉偏好：${style.trim()}` : "",
      "请生成适合实际教学或沟通使用的中文演示文稿。内容必须面向观众，不要输出制作说明、图片提示词或设计备注。",
    ].filter(Boolean).join("\n");
    try {
      const created = await api<Presentation>("/presentation/create", {
        method: "POST",
        body: JSON.stringify({
          content: brief,
          n_slides: slideCount ? Number(slideCount) : null,
          language: "Chinese",
          tone: "educational",
          verbosity: "standard",
          instructions: "保持中文自然、简洁、适龄；页面结构由内容决定，不套用固定流程。",
          include_table_of_contents: false,
          include_title_slide: true,
          web_search: false,
          generation_mode: "standard",
        }),
      });
      location.href = `/presentations/${created.id}/outline`;
    } catch (cause) {
      setError(localizeError(cause)); setBusy(false);
    }
  };

  const duplicateProject = async (item: Presentation) => {
    setPendingProjectId(item.id); setProjectError("");
    try {
      const duplicated = await api<Presentation>(`/presentation/${item.id}/duplicate`, { method: "POST" });
      setPresentations((current) => [duplicated, ...current]);
    } catch (cause) {
      setProjectError(localizeError(cause));
    } finally {
      setPendingProjectId(null);
    }
  };

  const deleteProject = async () => {
    if (!deleteTarget) return;
    setPendingProjectId(deleteTarget.id); setProjectError("");
    try {
      await api<null>(`/presentation/${deleteTarget.id}`, { method: "DELETE" });
      setPresentations((current) => current.filter((item) => item.id !== deleteTarget.id));
      setDeleteTarget(null);
    } catch (cause) {
      setProjectError(localizeError(cause));
    } finally {
      setPendingProjectId(null);
    }
  };

  return <Shell><main className="home-main">
      <div className="hero-copy"><h1>输入一个主题，生成完整幼教 PPT</h1></div>
      <form className="prompt-workspace" onSubmit={(event) => void create(event)}>
        <div className="prompt-main"><span className="prompt-symbol"><SparklesIcon /></span><textarea required value={topic} onChange={(event) => setTopic(event.target.value)} placeholder="例如：为幼儿园中班制作一套认识海洋动物的互动课件" /></div>
        <div className="brief-row">
          <label><span>观众</span><input required value={audience} onChange={(event) => setAudience(event.target.value)} placeholder="幼儿、家长或教师" /></label>
          <label><span>年龄或班级</span><input value={age} onChange={(event) => setAge(event.target.value)} placeholder="如：中班 4—5 岁" /></label>
          <label><span>使用场景</span><input required value={scene} onChange={(event) => setScene(event.target.value)} placeholder="如：集体教学" /></label>
          <label><span>页数</span><input type="number" min="1" max="50" value={slideCount} onChange={(event) => setSlideCount(event.target.value)} placeholder="自动" /></label>
        </div>
        <details className="more-options"><summary>补充要求</summary><div className="secondary-fields">
          <label><span>演示目标</span><input value={goal} onChange={(event) => setGoal(event.target.value)} placeholder="希望观众理解或完成什么" /></label>
          <label><span>视觉风格</span><input value={style} onChange={(event) => setStyle(event.target.value)} placeholder="如：明亮、童趣、自然" /></label>
        </div></details>
        {error && <div className="error-line">{error}</div>}
        <footer><span>下一步可逐页修改大纲</span><button className="primary" disabled={busy}>{busy ? "正在创建…" : "生成大纲"}<ArrowRightIcon /></button></footer>
      </form>
      {presentations.length > 0 && <section className="recent-projects">
        <header><h2>最近项目</h2><span>{presentations.length} 个</span></header>
        {projectError && <div className="project-error">{projectError}</div>}
        <div className="recent-grid">
          {presentations.map((item) => {
            const title = projectTitle(item);
            const previewBase = import.meta.env.VITE_EDITOR_BASE_URL ?? "http://127.0.0.1:5001";
            const projectUrl = item.slides.length ? `/presentations/${item.id}/edit` : `/presentations/${item.id}/outline`;
            return <article className="project-card" key={item.id}>
              <a className="project-preview" href={projectUrl}>
                <iframe
                  aria-hidden="true"
                  loading="lazy"
                  src={`${previewBase}/presentation-thumbnail?id=${encodeURIComponent(item.id)}`}
                  tabIndex={-1}
                  title={`${title} 第一页预览`}
                />
                <span className="project-kind">PPT</span>
                <span className="project-pages">{item.n_slides || 0}</span>
              </a>
              <div className="project-copy">
                <a className="project-meta" href={projectUrl}><b>{title}</b><span>{new Date(item.updated_at).toLocaleDateString("zh-CN")}</span></a>
                <details className="project-actions">
                  <summary aria-label={`管理${title}`}><MoreVerticalIcon /></summary>
                  <div className="project-menu">
                    <button disabled={pendingProjectId === item.id} onClick={(event) => {
                      event.currentTarget.closest("details")?.removeAttribute("open");
                      void duplicateProject(item);
                    }}><CopyIcon />{pendingProjectId === item.id ? "正在复制…" : "复制"}</button>
                    <button className="danger" disabled={pendingProjectId === item.id} onClick={(event) => {
                      event.currentTarget.closest("details")?.removeAttribute("open");
                      setDeleteTarget(item);
                    }}><TrashIcon />删除</button>
                  </div>
                </details>
              </div>
            </article>;
          })}
        </div>
      </section>}
      {deleteTarget && <div className="confirm-backdrop" role="presentation" onMouseDown={(event) => {
        if (event.target === event.currentTarget && pendingProjectId !== deleteTarget.id) setDeleteTarget(null);
      }}>
        <section aria-labelledby="delete-project-title" aria-modal="true" className="confirm-dialog" role="dialog">
          <h2 id="delete-project-title">删除演示文稿？</h2>
          <p>“{projectTitle(deleteTarget)}”删除后无法恢复。</p>
          <footer><button disabled={pendingProjectId === deleteTarget.id} onClick={() => setDeleteTarget(null)}>取消</button><button className="danger" disabled={pendingProjectId === deleteTarget.id} onClick={() => void deleteProject()}>{pendingProjectId === deleteTarget.id ? "正在删除…" : "确认删除"}</button></footer>
        </section>
      </div>}
  </main></Shell>;
}

export function OutlinePage({ presentationId }: { presentationId: string }) {
  const [presentation, setPresentation] = useState<Presentation>();
  const [outline, setOutline] = useState<PresentationOutline>();
  const [templates, setTemplates] = useState<TemplateItem[]>([]);
  const [status, setStatus] = useState("正在读取项目");
  const [error, setError] = useState("");
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void (async () => {
      try {
        const [current, existingOutline, templateList] = await Promise.all([
          api<Presentation>(`/presentation/${presentationId}`),
          api<PresentationOutline>(`/outlines/${presentationId}`),
          api<TemplateList>("/template/all?page_size=100"),
        ]);
        setPresentation(current); setTemplates(templateList.items);
        if (existingOutline.slides.length) { setOutline(existingOutline); setStatus(""); return; }
        setStatus("AI 正在组织大纲");
        await consumeStream(`/outlines/stream/${presentationId}`, (event) => {
          if (event.type === "status") setStatus(localizeStatus(event.status));
        });
        setOutline(await api<PresentationOutline>(`/outlines/${presentationId}`));
        setPresentation(await api<Presentation>(`/presentation/${presentationId}`));
        setStatus("");
      } catch (cause) { setError(localizeError(cause)); setStatus(""); }
    })();
  }, [presentationId]);

  if (error) return <Shell><main className="center-state"><h1>大纲生成失败</h1><p>{error}</p><a href="/">返回首页</a></main></Shell>;
  if (!outline || !presentation) return <Shell><main className="center-state running"><span className="spinner"/><h1>{status}</h1></main></Shell>;
  return <Shell><OutlineEditor presentation={presentation} initial={outline} templates={templates} /></Shell>;
}

export function GenerationPage({ presentationId }: { presentationId: string }) {
  useEffect(() => {
    location.replace(`/presentations/${presentationId}/edit?stream=true`);
  }, [presentationId]);
  return <Shell><main className="center-state running"><span className="spinner"/><h1>正在打开编辑器</h1><p>页面将在编辑器中逐页生成</p></main></Shell>;
}
