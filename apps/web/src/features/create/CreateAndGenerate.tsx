import React, { useEffect, useState } from "react";
import { api, startJob, waitForJob } from "../../api/client";
import type { Brief, Job, PresentationState } from "../../entities/types";
import { OutlineEditor } from "../outline/OutlineEditor";

export function CreatePage() {
  const [items, setItems] = useState<Brief[]>([]);
  const [form, setForm] = useState({ title: "", audience: "", ageRange: "", usageContext: "", objective: "", pageCount: 10, style: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { void api<Brief[]>("/presentations").then(setItems).catch((cause) => setError(cause.message)); }, []);
  const create = async (event: React.FormEvent) => {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const brief = await api<Brief>("/presentations", { method: "POST", body: JSON.stringify({ title: form.title, audience: form.audience, ageRange: form.ageRange || undefined, usageContext: form.usageContext, objective: form.objective, pageCount: form.pageCount, constraints: form.style ? [`视觉偏好：${form.style}`] : [], sourceAssetIds: [], language: "zh-CN" }) });
      await startJob(`/presentations/${brief.id}/outline-jobs`);
      location.href = `/presentations/${brief.id}/generate`;
    } catch (cause) { setError((cause as Error).message); setBusy(false); }
  };
  const field = (key: keyof typeof form, value: string | number) => setForm((current) => ({ ...current, [key]: value }));
  return <main className="create-page"><header className="site-header"><a className="brand" href="/">SparkDeck</a><span>幼儿园全场景 AI 演示</span></header><section className="create-hero"><span className="step-label">第 1 步</span><h1>说清楚要讲什么，先生成大纲</h1><p>大纲确认后，系统才会设计页面并按最终版式生成需要的图片。</p></section><form className="brief-form" onSubmit={(event) => void create(event)}>
    <label className="wide-field">演示主题<input required value={form.title} onChange={(event) => field("title", event.target.value)} placeholder="例如：新学期家长会 / 春天科学活动 / 消防安全教育" /></label>
    <label>给谁看<input required value={form.audience} onChange={(event) => field("audience", event.target.value)} placeholder="幼儿、家长、教师…" /></label>
    <label>年龄或班级<input value={form.ageRange} onChange={(event) => field("ageRange", event.target.value)} placeholder="小班 / 4–5 岁" /></label>
    <label>使用场景<input required value={form.usageContext} onChange={(event) => field("usageContext", event.target.value)} placeholder="课堂教学、家长会、园务汇报…" /></label>
    <label>页数<input required type="number" min={1} max={80} value={form.pageCount} onChange={(event) => field("pageCount", Number(event.target.value))} /></label>
    <label className="wide-field">希望观众听完以后怎样<input required value={form.objective} onChange={(event) => field("objective", event.target.value)} placeholder="理解、参与、形成共识或完成某项行动" /></label>
    <label className="wide-field">视觉偏好（可选）<input value={form.style} onChange={(event) => field("style", event.target.value)} placeholder="例如：温暖自然、童趣但不幼稚、照片为主" /></label>
    {error && <div className="error-banner wide-field">{error}</div>}<div className="form-action wide-field"><span>费用仅在后台统计，不在流程中打断你。</span><button className="primary" disabled={busy}>{busy ? "正在生成大纲…" : "生成大纲"}</button></div>
  </form>{items.length > 0 && <section className="recent"><h2>最近的演示</h2><div>{items.map((item) => <a key={item.id} href={`/presentations/${item.id}/generate`}><b>{item.title}</b><span>{item.audience} · {item.pageCount} 页</span></a>)}</div></section>}</main>;
}

export function GeneratePage({ presentationId }: { presentationId: string }) {
  const [state, setState] = useState<PresentationState>();
  const [progress, setProgress] = useState<Job>();
  const [error, setError] = useState("");
  const load = async () => { try { setState(await api(`/presentations/${presentationId}`)); } catch (cause) { setError((cause as Error).message); } };
  useEffect(() => { void load(); }, [presentationId]);
  const runPipeline = async () => {
    setError("");
    try {
      const stages = ["design-jobs", "composition-jobs", "asset-jobs", "quality-jobs"];
      for (const stage of stages) {
        const job = await api<Job>(`/presentations/${presentationId}/${stage}`, { method: "POST", body: JSON.stringify({ idempotencyKey: crypto.randomUUID(), ...(stage === "composition-jobs" ? { canvas: { width: 960, height: 540 } } : {}) }) });
        const completed = await waitForJob(job.id, setProgress);
        setProgress(completed);
      }
      location.href = `/presentations/${presentationId}/edit`;
    } catch (cause) { setError((cause as Error).message); }
  };
  if (!state) return <main className="empty-state">正在读取演示…</main>;
  if (!state.outline) return <main className="empty-state"><h1>还没有生成大纲</h1><p>{error || "请返回首页重新开始。"}</p><a href="/">返回首页</a></main>;
  if (!state.outline.confirmedAt) return <main className="generate-page"><OutlineEditor presentationId={presentationId} initial={state.outline} onConfirmed={() => void load()} /></main>;
  return <main className="generation-status"><div><span className="step-label">第 3 步</span><h1>生成设计、版式和必要图片</h1><p>先生成全稿设计意图和每页候选，选定版式后才解析图片。不会给未采用的候选生图。</p>{progress && <div className="progress"><span style={{ width: `${progress.progress}%` }} /><b>{progress.stage}</b><small>{progress.progress}%</small></div>}{error && <div className="error-banner">{error}</div>}<button className="primary large" onClick={() => void runPipeline()} disabled={progress?.status === "running"}>开始生成完整 PPT</button></div></main>;
}
