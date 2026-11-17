import assert from "node:assert/strict";
import test from "node:test";
import {
  canApplyReview, formatElapsed, humanQuestions, isReviewRunning, isReviewStale, newReviewRequestId,
  outlineSignature, pageChanges, pollReviewStatus, reviewStatusLabel,
} from "./contentReview.ts";
import { errorMessage } from "../../api/errorMessages.ts";

function result(overrides = {}) {
  return {
    status: "passed", message: "文本检查完成", elapsed_ms: 12000, rounds_completed: 1,
    original_plan: { slides: [{ slide_no: 1, screen_content: { title: "旧标题", points: ["旧正文"] }, teacher_note: "原讲稿" }] },
    plan: { slides: [{ slide_no: 1, screen_content: { title: "新标题", points: ["旧正文"] }, teacher_note: "新讲稿" }] },
    machine_quality: { passed: true, errors: [], warnings: [] },
    semantic_review: { findings: [], needs_human: false, human_questions: [] },
    ...overrides,
  };
}

function fixture() {
  const review = { review_id: "review-1", source_version: "v1", can_apply: true,
    changed_slide_numbers: [1], result: result() };
  const source = { available: true, reason: "ready", message: "", source_version: "v1",
    brief: {}, plan: null, latest_review: review };
  return { review, source, options: { dirty: false, busy: false, stale: false } };
}

test("only a matching, saved, available draft can adopt a reviewed change", () => {
  const { review, source, options } = fixture();
  assert.equal(canApplyReview(review, source, options), true);
  for (const flag of ["dirty", "busy", "stale"]) {
    assert.equal(canApplyReview(review, source, { ...options, [flag]: true }), false);
  }
  assert.equal(canApplyReview(review, { ...source, source_version: "v2" }, options), false);
  assert.equal(canApplyReview(review, { ...source, available: false }, options), false);
  assert.equal(canApplyReview({ ...review, can_apply: false }, source, options), false);
  assert.equal(canApplyReview({ ...review, changed_slide_numbers: [] }, source, options), false);
  assert.equal(canApplyReview(null, source, options), false);
  assert.equal(canApplyReview({ ...review, stale: true }, source, options), false);
  assert.equal(canApplyReview(review, { ...source, reason: "outline_changed" }, options), false);
  assert.equal(canApplyReview(review, { ...source, apply_available: false }, options), false);
  assert.equal(canApplyReview({ ...review, applied: true }, source, options), false);
  for (const reason of ["review_running", "review_in_progress"]) {
    assert.equal(isReviewRunning({ ...source, reason }), true);
    assert.equal(canApplyReview(review, { ...source, reason }, options), false);
  }
  assert.equal(isReviewRunning({ ...source, reason: "review_expired" }), false);
});

test("read-only recovery keeps polling after a transient error and stops on cleanup", async (context) => {
  context.mock.timers.enable({ apis: ["setTimeout"] });
  let reads = 0;
  const stop = pollReviewStatus(async () => {
    reads += 1;
    if (reads === 1) throw new Error("temporary read failure");
  });
  context.mock.timers.tick(5000);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(reads, 1);
  context.mock.timers.tick(5000);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(reads, 2);
  stop();
  context.mock.timers.tick(10000);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(reads, 2);
});

test("saving a manual edit cannot make an old report current when its source version is unchanged", () => {
  const { review, source } = fixture();
  const local = { dirty: false, reportSignature: "saved-edited-outline", draftSignature: "saved-edited-outline" };
  assert.equal(isReviewStale(review, source, local), false);
  assert.equal(isReviewStale(review, { ...source, available: false, reason: "outline_changed" }, local), true);
  assert.equal(isReviewStale({ ...review, stale: true }, source, local), true);
});

test("draft identity ignores object-key order but notices text and note edits", () => {
  const initial = { slides: [{ content: "海洋动物", content_contract: { teacher_note: "原讲稿", relationship: "single" } }] };
  const reordered = { slides: [{ content_contract: { relationship: "single", teacher_note: "原讲稿" }, content: "海洋动物" }] };
  assert.equal(outlineSignature(initial), outlineSignature(reordered));
  assert.notEqual(outlineSignature(initial), outlineSignature({ slides: [{ ...initial.slides[0], content: "海龟" }] }));
  assert.notEqual(outlineSignature(initial), outlineSignature({ slides: [{ ...initial.slides[0], content_contract: { teacher_note: "修改讲稿", relationship: "single" } }] }));
});

test("a conflicting grade cannot appear as a passing UI result", () => {
  assert.equal(reviewStatusLabel(result()), "文本检查通过");
  assert.notEqual(reviewStatusLabel(result({ semantic_review: null })), "文本检查通过");
  assert.notEqual(reviewStatusLabel(result({ machine_quality: { passed: false, errors: [], warnings: [] } })), "文本检查通过");
  assert.notEqual(reviewStatusLabel(result({ semantic_review: { findings: [{ severity: "error" }], needs_human: false, human_questions: [] } })), "文本检查通过");
  assert.notEqual(reviewStatusLabel(result({ status: "model_error" })), "文本检查通过");
});

test("change preview shows real changed text and leaves equal fields out", () => {
  assert.deepEqual(pageChanges(result(), 1), [
    { label: "标题", before: "旧标题", after: "新标题" },
    { label: "教师讲稿", before: "原讲稿", after: "新讲稿" },
  ]);
  assert.deepEqual(pageChanges(result(), 99), []);
});

test("human questions from an unadopted final candidate remain visible", () => {
  const report = result({ status: "needs_human", review_history: [{ adopted: false,
    semantic_review: { findings: [], needs_human: true, human_questions: ["这项数据的来源是什么？"] } }] });
  assert.deepEqual(humanQuestions(report), ["这项数据的来源是什么？"]);
});

test("structured conflict messages explain recovery without dumping raw detail", () => {
  assert.equal(errorMessage({ detail: { code: "version_conflict", message: "大纲已修改，请重新读取检查资料。" } }, 409, "Conflict"),
    "大纲已修改，请重新读取检查资料。");
  assert.equal(errorMessage({ detail: { secret: "DO_NOT_DISPLAY" } }, 409, "Conflict"), "项目状态已变化，请刷新后重试。");
});

test("elapsed time is measured duration, not an invented percentage", () => {
  assert.equal(formatElapsed(59_900), "59 秒");
  assert.equal(formatElapsed(61_000), "1 分 1 秒");
  assert.equal(formatElapsed(-100), "0 秒");
});

test("each explicit request has a new UUID for server deduplication", () => {
  const first = newReviewRequestId();
  assert.match(first, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  assert.notEqual(first, newReviewRequestId());
});
