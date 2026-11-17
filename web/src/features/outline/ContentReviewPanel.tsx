import { useCallback, useEffect, useRef, useState } from "react";
import { api, localizeError } from "../../api/client";
import { ApiError } from "../../api/errorMessages";
import type { PresentationOutline } from "../../entities/types";
import {
  canApplyReview, formatElapsed, humanQuestions, isReviewRunning, isReviewStale,
  newReviewRequestId, pageChanges, pollReviewStatus,
  reviewStatusLabel, type ContentReviewSource, type SavedContentReview,
} from "./contentReview";
import { teacherReviewMessages } from "./outlineFeedback";

const CRITERIA: Record<string, string> = {
  topic_focus: "主题聚焦", age_and_audience: "年龄与对象", teaching_feasibility: "课堂可用性",
  cross_slide_coherence: "前后衔接", source_fidelity: "资料依据", visual_brief_alignment: "配图描述",
};

const READ_WAIT_MS = 20_000;
const APPLY_WAIT_MS = 30_000;
type ApplyRecovery = { reviewId: string; confirmedRejected: boolean };

class RequestDeadlineError extends Error {}

async function boundedApi<T>(path: string, init: RequestInit, controller: AbortController, waitMs: number): Promise<T> {
  let deadline: ReturnType<typeof setTimeout> | undefined;
  let onAbort = () => {};
  const stopped = new Promise<never>((_resolve, reject) => {
    onAbort = () => reject(new DOMException("Request aborted", "AbortError"));
    if (controller.signal.aborted) onAbort();
    else controller.signal.addEventListener("abort", onAbort, { once: true });
    deadline = setTimeout(() => {
      reject(new RequestDeadlineError());
      controller.abort();
    }, waitMs);
  });
  try {
    return await Promise.race([api<T>(path, { ...init, signal: controller.signal }), stopped]);
  } finally {
    clearTimeout(deadline);
    controller.signal.removeEventListener("abort", onAbort);
  }
}

function isSavedOutline(value: unknown): value is PresentationOutline {
  if (!value || typeof value !== "object" || !("slides" in value) || !Array.isArray(value.slides)) return false;
  return value.slides.length > 0 && value.slides.every((slide: unknown) =>
    slide !== null && typeof slide === "object" && "content" in slide && typeof slide.content === "string");
}

export function ContentReviewPanel({ presentationId, draftSignature, savedSignature, dirty,
  disabled, onBusyChange, onSelectSlide, onApplied }: {
  presentationId: string;
  draftSignature: string;
  savedSignature: string;
  dirty: boolean;
  disabled: boolean;
  onBusyChange: (busy: boolean) => void;
  onSelectSlide: (number: number) => void;
  onApplied: (outlines: PresentationOutline) => void;
}) {
  const base = `/kindergarten/presentation/${presentationId}`;
  const [source, setSource] = useState<ContentReviewSource | null>(null);
  const [review, setReview] = useState<SavedContentReview | null>(null);
  const [reportSignature, setReportSignature] = useState<string | null>(null);
  const [loadingSource, setLoadingSource] = useState(true);
  const [activity, setActivity] = useState<"review" | "revise" | "apply" | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState("");
  const [sourceError, setSourceError] = useState("");
  const [notice, setNotice] = useState("");
  const [applyRecovery, setApplyRecovery] = useState<ApplyRecovery | null>(null);
  const pendingApply = useRef<ApplyRecovery | null>(null);
  const appliedCallback = useRef(onApplied);
  appliedCallback.current = onApplied;
  const request = useRef<AbortController | null>(null);
  const sourceRequest = useRef<AbortController | null>(null);
  const sourceSequence = useRef(0);
  const mounted = useRef(true);
  const currentBase = useRef(base);
  currentBase.current = base;
  const serverBusy = isReviewRunning(source);

  const rememberApply = useCallback((value: ApplyRecovery | null) => {
    pendingApply.current = value;
    setApplyRecovery(value);
  }, []);

  const readSource = useCallback(async () => {
    sourceRequest.current?.abort();
    const controller = new AbortController();
    sourceRequest.current = controller;
    const sequence = ++sourceSequence.current;
    setLoadingSource(true);
    let syncingOutline = false;
    try {
      const next = await boundedApi<ContentReviewSource>(`${base}/review-source`, {
        cache: "no-store",
      }, controller, READ_WAIT_MS);
      if (!mounted.current || currentBase.current !== base || sequence !== sourceSequence.current) return;
      setSource(next);
      setReview(next.latest_review);
      setReportSignature(next.latest_review ? savedSignature : null);
      setSourceError("");
      const recovery = pendingApply.current;
      if (recovery) {
        const confirmedApplied = next.latest_review?.review_id === recovery.reviewId && next.latest_review.applied;
        if (confirmedApplied || recovery.confirmedRejected) {
          // A report may be stale after adoption, and the server outline can have
          // additional visual contracts or later edits. Always read the actual
          // persisted outline; never rebuild it from the reviewed plan.
          syncingOutline = true;
          setNotice("正在同步服务器已保存的大纲，完成前暂停编辑和生成。");
          const saved = await boundedApi<PresentationOutline>(`/outlines/${presentationId}`, {
            cache: "no-store",
          }, controller, READ_WAIT_MS);
          if (!mounted.current || currentBase.current !== base || sequence !== sourceSequence.current
              || pendingApply.current !== recovery) return;
          if (!isSavedOutline(saved)) throw new Error("服务器尚未返回完整的已保存大纲。");
          appliedCallback.current(saved);
          rememberApply(null);
          if (confirmedApplied) setError("");
          setNotice(confirmedApplied
            ? "已同步服务器保存的修订稿，可以继续编辑和生成。"
            : "采用请求未完成；已同步服务器当前大纲，可以继续编辑。");
        } else {
          setNotice("采用结果尚未确认，编辑和生成暂时暂停。请重新读取结果，不会重复提交采用请求。");
        }
      }
    } catch (cause) {
      if (!mounted.current || currentBase.current !== base || sequence !== sourceSequence.current
          || (controller.signal.aborted && !(cause instanceof RequestDeadlineError))) return;
      if (pendingApply.current) {
        setSourceError(syncingOutline
          ? "暂时无法同步服务器已保存的大纲，编辑和生成仍已暂停。请重新确认采用结果。"
          : "暂时无法确认采用结果，编辑和生成仍已暂停。请重新读取服务器状态。");
      } else {
        setSourceError(cause instanceof RequestDeadlineError
          ? "读取检查状态超时，请再次读取；仍可继续编辑和生成 PPT。"
          : cause instanceof ApiError && cause.status === 404
            ? "此稿暂时无法读取完整检查资料，你可以继续编辑和生成 PPT。"
            : `暂时无法读取检查状态：${localizeError(cause)}`);
      }
    } finally {
      if (sourceRequest.current === controller) sourceRequest.current = null;
      if (mounted.current && currentBase.current === base && sequence === sourceSequence.current) setLoadingSource(false);
    }
  }, [base, presentationId, savedSignature, rememberApply]);

  useEffect(() => {
    setActivity(null);
    setNotice("");
    setError("");
    rememberApply(null);
    return () => {
      request.current?.abort();
      request.current = null;
    };
  }, [base, rememberApply]);

  useEffect(() => {
    mounted.current = true;
    setSource(null);
    setReview(null);
    setReportSignature(null);
    setSourceError("");
    void readSource();
    return () => {
      sourceRequest.current?.abort();
    };
  }, [readSource]);

  useEffect(() => () => {
    mounted.current = false;
    request.current?.abort();
    sourceRequest.current?.abort();
    onBusyChange(false);
  }, [onBusyChange]);

  useEffect(() => { onBusyChange(activity !== null || serverBusy || applyRecovery !== null); },
    [activity, serverBusy, applyRecovery, onBusyChange]);

  useEffect(() => {
    if (!activity) return;
    const started = Date.now();
    setElapsed(0);
    const timer = window.setInterval(() => setElapsed(Date.now() - started), 1000);
    return () => window.clearInterval(timer);
  }, [activity]);

  useEffect(() => {
    if (!serverBusy || activity) return;
    // A refresh only reads a running job; it never submits another model call.
    return pollReviewStatus(readSource);
  }, [serverBusy, activity, readSource]);

  const stale = isReviewStale(review, source, { dirty, reportSignature, draftSignature });
  const canStart = Boolean(source?.available && source.source_version && !dirty
    && !disabled && !activity && !serverBusy && !loadingSource && !applyRecovery);
  const canApply = canApplyReview(review, source, {
    dirty, stale, busy: disabled || Boolean(activity) || serverBusy || loadingSource || Boolean(applyRecovery),
  });

  const runReview = async (rounds: 0 | 1) => {
    if (!canStart || !source?.source_version || request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setActivity(rounds ? "revise" : "review");
    setError("");
    setNotice("");
    let waitExpired = false;
    const deadline = window.setTimeout(() => {
      waitExpired = true;
      controller.abort();
    }, 370_000);
    try {
      const result = await api<SavedContentReview>(`${base}/review`, {
        method: "POST", signal: controller.signal,
        body: JSON.stringify({
          source_version: source.source_version, max_revision_rounds: rounds,
          timeout_seconds: 360, max_model_calls: 5, request_id: newReviewRequestId(),
        }),
      });
      if (!mounted.current || currentBase.current !== base) return;
      setReview(result);
      setReportSignature(savedSignature);
      setSource((previous) => previous ? { ...previous, latest_review: result,
        apply_available: result.can_apply } : previous);
      setNotice("检查结果已保存，可展开具体问题查看。");
    } catch (cause) {
      if (!mounted.current || currentBase.current !== base) return;
      if (controller.signal.aborted) {
        setNotice(waitExpired
          ? "已达到等待时限，当前大纲保留。正在读取最近结果确认状态。"
          : "已取消本次请求，当前大纲保留。正在读取最近结果确认状态。");
      } else {
        setError(localizeError(cause));
      }
    } finally {
      window.clearTimeout(deadline);
      if (request.current === controller) request.current = null;
      if (mounted.current && currentBase.current === base) {
        setActivity(null);
        // This recovery path is read-only, even after timeout or a lost response.
        void readSource();
      }
    }
  };

  const applyReview = async () => {
    if (!canApply || !review || request.current) return;
    const controller = new AbortController();
    request.current = controller;
    const recovery: ApplyRecovery = { reviewId: review.review_id, confirmedRejected: false };
    rememberApply(recovery);
    setActivity("apply");
    setError("");
    setNotice("");
    try {
      const applied = await boundedApi<{ outlines: PresentationOutline; source_version: string; message: string }>(
        `${base}/review/apply`, {
          method: "POST",
          body: JSON.stringify({ review_id: review.review_id, source_version: review.source_version }),
        }, controller, APPLY_WAIT_MS,
      );
      if (!mounted.current || currentBase.current !== base) return;
      if (!isSavedOutline(applied?.outlines)) throw new Error("采用请求的保存结果尚未确认。");
      appliedCallback.current(applied.outlines);
      rememberApply(null);
      setReview(null);
      setReportSignature(null);
      setNotice(applied.message || "修订稿已采用并保存。");
    } catch (cause) {
      if (mounted.current && currentBase.current === base) {
        // A lost response or timeout cannot establish whether the write committed.
        // Known rejection statuses still require synchronizing the saved outline
        // before allowing this page to write, because another tab may have edited it.
        recovery.confirmedRejected = cause instanceof ApiError && [400, 401, 403, 404, 409, 422].includes(cause.status);
        setError(cause instanceof RequestDeadlineError
          ? "采用请求等待超时，正在确认服务器的保存结果。"
          : `采用请求未确认：${localizeError(cause)}`);
      }
    } finally {
      if (request.current === controller) request.current = null;
      if (mounted.current && currentBase.current === base) {
        setActivity(null);
        void readSource();
      }
    }
  };

  const result = review?.result;
  const questions = result ? humanQuestions(result) : [];
  const findings = result?.semantic_review?.findings ?? [];
  const machineIssues = [
    ...(result?.machine_quality.errors ?? []).map((issue) => ({ ...issue, severity: "error" })),
    ...(result?.machine_quality.warnings ?? []).map((issue) => ({ ...issue, severity: "warning" })),
  ];
  const resultLabel = result ? reviewStatusLabel(result) : "";

  return <section className="content-review-panel" aria-label="内容检查">
    <div className="content-review-heading">
      <div>
        <h2>内容检查</h2>
        <p>检查主题、前后衔接和课堂可用性，最多修订一轮；修订稿由你确认采用。</p>
      </div>
      <div className="content-review-actions">
        <button type="button" className="outline-secondary-action" disabled={!canStart}
          onClick={() => void runReview(0)}>检查内容</button>
        <button type="button" className="outline-secondary-action" disabled={!canStart}
          onClick={() => void runReview(1)}>检查并修订</button>
      </div>
    </div>

    {activity ? <div className="content-review-running" role="status" aria-live="polite">
      <span className="content-review-spinner" aria-hidden="true" />
      <span>{activity === "apply" ? "正在保存修订稿" : activity === "revise" ? "正在检查并修订内容" : "正在检查内容"}
        <small>已用时 {formatElapsed(elapsed)}</small></span>
      {activity !== "apply" && <button type="button" onClick={() => request.current?.abort()}>取消检查</button>}
    </div> : serverBusy ? <p className="content-review-info" role="status">
      已有内容检查正在进行，正在读取它的进度和结果。
    </p> : loadingSource ? <p className="content-review-muted" role="status">正在读取检查状态…</p> : null}

    {dirty && <p className="content-review-info">当前有未保存的修改，请先保存草稿。检查不会覆盖你的手动修改。</p>}
    {applyRecovery && activity !== "apply" && <p className="content-review-info" role="status">
      正在确认采用结果，编辑和生成暂时暂停；同步已保存大纲后自动恢复。
    </p>}
    {!loadingSource && source && !source.available && !serverBusy &&
      <p className="content-review-muted">{source.message || "此稿暂无完整检查资料，可以继续编辑和生成 PPT。"}</p>}
    {error && <p className="content-review-error" role="alert">{error}</p>}
    {sourceError && <p className="content-review-error" role="alert">{sourceError}</p>}
    {notice && <p className="content-review-info" role="status">{notice}</p>}
    <button type="button" className="content-review-refresh" disabled={loadingSource || Boolean(activity)}
      onClick={() => { setSourceError(""); void readSource(); }}>{applyRecovery ? "重新确认采用结果" : "读取最近结果"}</button>

    {result && <div className="content-review-result">
      <div className="content-review-result-title">
        <strong className={resultLabel === "文本检查通过" && !stale && !review?.applied ? "content-review-passed" : ""}>
          {review?.applied ? "修订稿已采用" : stale ? "检查结果已过期" : resultLabel}
        </strong>
        <span>耗时 {formatElapsed(result.elapsed_ms)} · {findings.length + machineIssues.length} 项发现</span>
      </div>
      {review?.applied ? <p className="content-review-info">{review.message || "这份修订稿已经采用，以下保留本次检查与修改记录。"}</p>
        : stale ? <p className="content-review-info">大纲已改变，以下结果仅供参考；旧修订稿不能覆盖当前内容。</p>
        : <p>{result.message}</p>}
      {questions.length > 0 && <div className="content-review-questions">
        <strong>需要你确认</strong><ul>{questions.map((text) => <li key={text}>{text}</li>)}</ul>
      </div>}
      {machineIssues.map((issue, index) => <article className="content-review-finding" key={`machine-${index}`}>
        <header><b>{issue.severity === "error" ? "需修改" : "可优化"} · 格式与活动检查</b>{issue.slide_no && <button type="button" onClick={() => onSelectSlide(issue.slide_no!)}>
          查看第 {issue.slide_no} 页</button>}</header>
        <p>{teacherReviewMessages(issue.message).join("；")}</p>
      </article>)}
      {findings.map((finding) => <article className="content-review-finding" key={finding.issue_id}>
        <header><b>{finding.severity === "error" ? "需修改" : "可优化"} · {CRITERIA[finding.criterion] || "内容质量"}</b>
          <button type="button" onClick={() => onSelectSlide(finding.slide_no)}>查看第 {finding.slide_no} 页</button></header>
        <p>{finding.explanation}</p>
        <blockquote><span>原文</span>{finding.evidence}</blockquote>
        <p><strong>建议：</strong>{finding.suggestion}</p>
        <details><summary>查看检查依据</summary><p>{finding.requirement}</p></details>
      </article>)}
      {review && review.changed_slide_numbers.length > 0 && <div className="content-review-revisions">
        <strong>已有 {review.changed_slide_numbers.length} 页修订稿</strong>
        {review.changed_slide_numbers.map((number) => <details key={number}>
          <summary>第 {number} 页 · 查看修订前后</summary>
          {pageChanges(result, number).map((change) => <div className="content-review-comparison" key={change.label}>
            <b>{change.label}</b><div><span>修订前</span><p>{change.before}</p></div><div><span>修订后</span><p>{change.after}</p></div>
          </div>)}
        </details>)}
        <button type="button" className="content-review-apply" disabled={!canApply} onClick={() => void applyReview()}>
          {review.applied ? "修订稿已采用" : `采用修订稿（${review.changed_slide_numbers.length} 页）`}
        </button>
      </div>}
      <p className="content-review-muted">本次检查覆盖文稿与配图描述，实际图片、排版和导出效果需另行查看。</p>
    </div>}
  </section>;
}
