import { vi } from "vitest";
import type { Presentation, PresentationOutline, TemplateItem } from "../entities/types";
import type {
  ContentReviewResult, ContentReviewSource, SavedContentReview,
} from "../features/outline/contentReview";

export const PRESENTATION_ID = "ppt-review-dom";
export const SOURCE_VERSION = "a".repeat(64);
export const APPLIED_VERSION = "b".repeat(64);
export const BASE = `/api/v1/ppt/kindergarten/presentation/${PRESENTATION_ID}`;
export const OUTLINE_PATH = `/api/v1/ppt/outlines/${PRESENTATION_ID}`;

export function makeOutline(revised = false): PresentationOutline {
  return { slides: [
    { content: `## ${revised ? "海洋小侦探" : "海底观察"}\n\n• 观察海龟的外形`,
      content_contract: { teacher_note: "请幼儿描述观察到的特征。", interaction_instruction: "指一指图片中的海龟。" } },
    { content: "## 认识海龟\n\n• 找出海龟的四肢" },
    { content: "## 归纳讨论\n\n• 说说海龟和鱼有什么不同" },
  ] };
}

export function makePresentation(): Presentation {
  return {
    id: PRESENTATION_ID, title: "海洋观察", content: "海洋观察", n_slides: 3,
    language: "zh", created_at: "2026-11-17T00:00:00Z", updated_at: "2026-11-17T00:00:00Z",
    slides: [], generation_metadata: { content_mode: "classroom", outline_status: "ready" },
  };
}

export const TEMPLATES: TemplateItem[] = [{
  id: "kindergarten-classroom", name: "幼教课堂", layout_count: 3,
}];

export function makeResult(): ContentReviewResult {
  const remainingSlides = [
    { slide_no: 2, screen_content: { title: "认识海龟", points: ["找出海龟的四肢"] } },
    { slide_no: 3, screen_content: { title: "归纳讨论", points: ["说说海龟和鱼有什么不同"] } },
  ];
  return {
    status: "passed", message: "文稿已完成复核。", elapsed_ms: 12000, rounds_completed: 1,
    original_plan: { slides: [{ slide_no: 1, screen_content: { title: "海底观察", points: ["观察海龟的外形"] } }, ...remainingSlides] },
    plan: { slides: [{ slide_no: 1, screen_content: { title: "海洋小侦探", points: ["观察海龟的外形"] } }, ...remainingSlides] },
    machine_quality: { passed: true, errors: [], warnings: [] },
    semantic_review: { findings: [], needs_human: false, human_questions: [] },
  };
}

export function makeReview(overrides: Partial<SavedContentReview> = {}): SavedContentReview {
  return { review_id: "11111111-1111-4111-8111-111111111111", source_version: SOURCE_VERSION,
    result: makeResult(), can_apply: true, changed_slide_numbers: [1], stale: false,
    applied: false, ...overrides };
}

export function makeSource(overrides: Partial<ContentReviewSource> = {}): ContentReviewSource {
  return {
    available: true, reason: null, message: "可以检查当前大纲。", source_version: SOURCE_VERSION,
    brief: { topic: "海洋观察", content_mode: "classroom", age_group: "4-5岁", n_slides: 3 },
    plan: makeResult().original_plan, latest_review: null, apply_available: false, ...overrides,
  };
}

export type MockHttpCall = {
  path: string;
  method: string;
  body: Record<string, unknown> | null;
  signal: AbortSignal | null;
};

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

export function mockHttp(respond: (call: MockHttpCall) => Response | Promise<Response>) {
  const calls: MockHttpCall[] = [];
  const fetch = vi.fn<typeof globalThis.fetch>(async (input, init) => {
    const call: MockHttpCall = {
      path: new URL(String(input), "http://localhost:5173").pathname,
      method: init?.method ?? "GET",
      body: typeof init?.body === "string" ? JSON.parse(init.body) as Record<string, unknown> : null,
      signal: init?.signal ?? null,
    };
    calls.push(call);
    return respond(call);
  });
  vi.stubGlobal("fetch", fetch);
  return { calls, fetch, count: (method: string, path?: string) => calls.filter((call) =>
    call.method === method && (!path || call.path === path)).length };
}

export function pendingResponse(signal: AbortSignal | null): Promise<Response> {
  return new Promise((_resolve, reject) => {
    const abort = () => reject(new DOMException("Request aborted", "AbortError"));
    if (signal?.aborted) abort();
    else signal?.addEventListener("abort", abort, { once: true });
  });
}

export function deferredResponse() {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>((done) => { resolve = done; });
  return { promise, resolve };
}
