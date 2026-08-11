import { useEffect, useRef, useState } from "react";
import { api, consumeStream } from "../../api/client";
import type { Presentation, PresentationOutline, StreamEvent, TemplateItem, TemplateList } from "../../entities/types";
import { OutlineEditor } from "../outline/OutlineEditor";

function Shell({ children }: { children: React.ReactNode }) {
  return <div className="app-shell">
    <header className="topbar"><a className="brand" href="/"><span className="brand-mark">S</span>SparkDeck</a><nav><a href="/">工作台</a><span>AI 生成可编辑 PPT</span></nav></header>
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

  useEffect(() => {
    void api<Presentation[]>("/presentation/all?include_slides=true&version=v2-standard")
      .then(setPresentations).catch((cause: Error) => setError(cause.message));
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
      setError((cause as Error).message); setBusy(false);
    }
  };

  return <Shell><main className="home-layout">
    <aside className="side-nav"><b>演示文稿</b><a className="active" href="/">＋ 新建演示</a><span>最近项目</span></aside>
    <section className="home-main">
      <div className="hero-copy"><p>AI PRESENTATION</p><h1>从一个想法，生成完整 PPT</h1><span>先确认大纲，再生成可编辑页面。页数、内容和布局都由你的需求决定。</span></div>
      <form className="prompt-workspace" onSubmit={(event) => void create(event)}>
        <textarea required value={topic} onChange={(event) => setTopic(event.target.value)} placeholder="描述演示主题、需要讲清的内容和希望达到的效果" />
        <div className="brief-row">
          <label>观众<input required value={audience} onChange={(event) => setAudience(event.target.value)} placeholder="填写主要观众" /></label>
          <label>年龄 / 班级<input value={age} onChange={(event) => setAge(event.target.value)} placeholder="按实际情况填写" /></label>
          <label>场景<input required value={scene} onChange={(event) => setScene(event.target.value)} placeholder="填写使用场景" /></label>
          <label>页数<input type="number" min="1" max="50" value={slideCount} onChange={(event) => setSlideCount(event.target.value)} placeholder="AI 决定" /></label>
        </div>
        <div className="brief-row secondary-fields">
          <label>目标<input value={goal} onChange={(event) => setGoal(event.target.value)} placeholder="希望观众理解或完成什么" /></label>
          <label>风格<input value={style} onChange={(event) => setStyle(event.target.value)} placeholder="描述期望的视觉感受" /></label>
        </div>
        {error && <div className="error-line">{error}</div>}
        <footer><span>费用仅在后台记录，不打断生成流程</span><button className="primary" disabled={busy}>{busy ? "正在创建…" : "生成大纲"}<i>→</i></button></footer>
      </form>
      <section className="recent-list"><header><h2>最近演示</h2><span>{presentations.length} 个项目</span></header>
        {presentations.length === 0 ? <p className="empty-line">还没有演示文稿，从上方输入一个主题开始。</p> : presentations.map((item) => <a key={item.id} href={item.slides.length ? `/presentations/${item.id}/edit` : `/presentations/${item.id}/outline`}>
          <span className="file-icon">P</span><b>{item.title || item.content.split("\n")[0]?.replace("主题：", "") || "未命名演示"}</b><small>{item.n_slides || "AI"} 页 · {new Date(item.updated_at).toLocaleDateString("zh-CN")}</small><i>→</i>
        </a>)}
      </section>
    </section>
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
          if (event.type === "status") setStatus(event.status);
        });
        setOutline(await api<PresentationOutline>(`/outlines/${presentationId}`));
        setPresentation(await api<Presentation>(`/presentation/${presentationId}`));
        setStatus("");
      } catch (cause) { setError((cause as Error).message); setStatus(""); }
    })();
  }, [presentationId]);

  if (error) return <Shell><main className="center-state"><h1>大纲生成失败</h1><p>{error}</p><a href="/">返回工作台</a></main></Shell>;
  if (!outline || !presentation) return <Shell><main className="center-state running"><span className="spinner"/><h1>{status}</h1><p>只调用一次文本模型，完成后即可逐页修改。</p></main></Shell>;
  return <Shell><OutlineEditor presentation={presentation} initial={outline} templates={templates} /></Shell>;
}

export function GenerationPage({ presentationId }: { presentationId: string }) {
  const [presentation, setPresentation] = useState<Presentation>();
  const [status, setStatus] = useState("准备生成页面");
  const [completed, setCompleted] = useState(0);
  const [error, setError] = useState("");
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void (async () => {
      try {
        const current = await api<Presentation>(`/presentation/${presentationId}`);
        setPresentation(current);
        await consumeStream(`/presentation/stream/${presentationId}`, (event: StreamEvent) => {
          if (event.type === "status") setStatus(event.status);
          if (event.type === "chunk" && /\"index\"\s*:/.test(event.chunk)) setCompleted((value) => value + 1);
          if (event.type === "slide_assets") setStatus(`正在处理第 ${event.slide_index + 1} 页素材`);
          if (event.type === "complete") setStatus("页面生成完成");
        });
        location.href = `/presentations/${presentationId}/edit`;
      } catch (cause) { setError((cause as Error).message); }
    })();
  }, [presentationId]);

  const total = presentation?.n_slides || 1;
  const progress = Math.min(96, Math.round((completed / total) * 88) + 8);
  return <Shell><main className="center-state running"><span className="spinner"/><h1>{error ? "生成失败" : "正在生成完整 PPT"}</h1><p>{error || status}</p>
    {!error && <div className="flat-progress"><span style={{ width: `${progress}%` }}/><b>{Math.min(completed, total)} / {total} 页</b></div>}
    {error && <><button className="primary" onClick={() => location.reload()}>重试当前生成</button><a href={`/presentations/${presentationId}/outline`}>返回大纲</a></>}
  </main></Shell>;
}
