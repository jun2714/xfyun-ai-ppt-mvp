import type { PresentationOutline } from "../../entities/types";

export type ContentReviewFinding = {
  issue_id: string;
  criterion: string;
  severity: "error" | "warning";
  slide_no: number;
  field_path: string;
  evidence: string;
  requirement: string;
  explanation: string;
  suggestion: string;
};

export type SemanticReview = {
  findings: ContentReviewFinding[];
  needs_human: boolean;
  human_questions: string[];
};

export type ReviewPlan = {
  slides: Array<Record<string, unknown> & { slide_no: number }>;
};

export type ContentReviewResult = {
  status: string;
  message: string;
  original_plan: ReviewPlan;
  plan: ReviewPlan;
  machine_quality: {
    passed: boolean;
    errors: Array<{ code: string; message: string; slide_no?: number | null }>;
    warnings: Array<{ code: string; message: string; slide_no?: number | null }>;
  };
  semantic_review: SemanticReview | null;
  review_history?: Array<{ adopted: boolean; semantic_review: SemanticReview }>;
  elapsed_ms: number;
  rounds_completed: number;
};

export type SavedContentReview = {
  review_id: string;
  source_version: string;
  result: ContentReviewResult;
  can_apply: boolean;
  stale?: boolean;
  applied?: boolean;
  applied_source_version?: string | null;
  message?: string;
  changed_slide_numbers: number[];
};

export type ContentReviewSource = {
  available: boolean;
  reason: string | null;
  message: string;
  source_version: string | null;
  brief: Record<string, unknown> | null;
  plan: ReviewPlan | null;
  latest_review: SavedContentReview | null;
  apply_available?: boolean;
};

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b))
      .filter(([, item]) => item !== undefined).map(([key, item]) => [key, canonical(item)]));
  }
  return value;
}

/** Local edit identity only; the server remains authoritative for source_version. */
export function outlineSignature(outline: PresentationOutline): string {
  return JSON.stringify(canonical(outline));
}

export function canApplyReview(
  review: SavedContentReview | null,
  source: ContentReviewSource | null,
  options: { dirty: boolean; busy: boolean; stale: boolean },
): boolean {
  return Boolean(review?.can_apply && review.changed_slide_numbers.length && source?.available
    && !review.stale && !review.applied && source.apply_available !== false
    && source.reason !== "outline_changed" && !isReviewRunning(source)
    && review.source_version === source.source_version
    && !options.dirty && !options.busy && !options.stale);
}

export function isReviewRunning(source: ContentReviewSource | null): boolean {
  return source?.reason === "review_in_progress" || source?.reason === "review_running";
}

/** Only polls a supplied read operation, including after a transient read failure. */
export function pollReviewStatus(read: () => Promise<unknown>, intervalMs = 5000): () => void {
  let stopped = false;
  let timer: ReturnType<typeof setTimeout>;
  const schedule = () => {
    timer = setTimeout(async () => {
      try { await read(); } catch { /* The read operation owns its user-facing error. */ }
      finally { if (!stopped) schedule(); }
    }, intervalMs);
  };
  schedule();
  return () => { stopped = true; clearTimeout(timer); };
}

export function isReviewStale(
  review: SavedContentReview | null,
  source: ContentReviewSource | null,
  options: { dirty: boolean; reportSignature: string | null; draftSignature: string },
): boolean {
  return Boolean(review && (review.stale || source?.reason === "outline_changed" || options.dirty
    || options.reportSignature !== options.draftSignature || review.source_version !== source?.source_version));
}

const STATUS_LABELS: Record<string, string> = {
  passed: "文本检查通过",
  needs_revision: "发现需要修改的内容",
  needs_human: "有内容需要你确认",
  max_rounds_reached: "本轮修订完成，仍有待改进项",
  no_progress: "本轮未取得进一步改善",
  budget_exhausted: "本轮检查已停止",
  timeout: "检查超时，当前大纲保留",
  cancelled: "检查已取消",
  model_error: "检查未完成，当前大纲保留",
  invalid_output: "检查结果需要重新核对",
  revision_rejected: "修订稿未被采用",
};

export function reviewStatusLabel(result: ContentReviewResult): string {
  if (result.status === "passed" && (!result.machine_quality?.passed || !result.semantic_review
      || result.semantic_review.needs_human || result.machine_quality.errors.length
      || result.semantic_review.findings.some((item) => item.severity === "error"))) {
    return "检查结果需要重新核对";
  }
  return STATUS_LABELS[result.status] || "检查结果待确认";
}

export function formatElapsed(milliseconds: number): string {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  return seconds < 60 ? `${seconds} 秒` : `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
}

export function humanQuestions(result: ContentReviewResult): string[] {
  const direct = result.semantic_review?.human_questions ?? [];
  const last = result.review_history?.at(-1);
  return [...new Set([...direct, ...(result.status === "needs_human"
    ? last?.semantic_review.human_questions ?? [] : [])])];
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : {};
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function pageCopy(plan: ReviewPlan, number: number): Record<string, string> {
  const slide = plan.slides.find((item) => item.slide_no === number);
  if (!slide) return {};
  const screen = record(slide.screen_content);
  const interaction = record(slide.interaction);
  const game = record(slide.game);
  const options = record(game.options);
  const answer = typeof game.answer_key === "string" ? options[game.answer_key] ?? game.answer_key : "";
  const visual = Array.isArray(slide.assets) ? slide.assets.map((asset) => {
    const item = record(asset);
    return [item.semantic_label, item.description, item.audience_text].filter((value) => typeof value === "string").join("：");
  }).join("\n") : "";
  return {
    "标题": String(screen.title ?? ""),
    "正文": strings(screen.points).join("\n"),
    "屏幕操作提示": String(screen.instruction ?? ""),
    "教学目标": String(slide.teaching_goal ?? ""),
    "教师讲稿": String(slide.teacher_note ?? ""),
    "课堂操作": String(interaction.instruction ?? ""),
    "题目": String(game.question ?? ""),
    "选项": Object.values(options).map(String).join("、"),
    "答案": String(answer ?? ""),
    "排序答案": strings(game.sequence_order).map((key) => String(options[key] ?? key)).join(" → "),
    "配对与分类答案": Object.entries(record(game.answer_map)).map(([key, value]) =>
      `${String(options[key] ?? key)} → ${String(options[String(value)] ?? value)}`).join("\n"),
    "配图描述": visual,
  };
}

export function pageChanges(result: ContentReviewResult, number: number) {
  const before = pageCopy(result.original_plan, number);
  const after = pageCopy(result.plan, number);
  return [...new Set([...Object.keys(before), ...Object.keys(after)])]
    .filter((label) => before[label] !== after[label])
    .map((label) => ({ label, before: before[label] || "（空）", after: after[label] || "（空）" }));
}

export function newReviewRequestId(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = ((bytes[6] ?? 0) & 15) | 64;
  bytes[8] = ((bytes[8] ?? 0) & 63) | 128;
  const hex = [...bytes].map((value) => value.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
