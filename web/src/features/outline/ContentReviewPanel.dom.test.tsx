import { StrictMode, type ComponentProps } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { PresentationOutline } from "../../entities/types";
import {
  APPLIED_VERSION, BASE, OUTLINE_PATH, PRESENTATION_ID, SOURCE_VERSION, TEMPLATES,
  deferredResponse, jsonResponse, makeOutline, makePresentation, makeResult,
  makeReview, makeSource, mockHttp, pendingResponse,
} from "../../test/contentReviewFixtures";
import { ContentReviewPanel } from "./ContentReviewPanel";
import { OutlineEditor } from "./OutlineEditor";
import type { SavedContentReview } from "./contentReview";

// Real React event handling in a Node DOM. These tests do not inspect pixels,
// exercise a real browser, or call a model/provider.
function button(name: string | RegExp): HTMLButtonElement {
  return screen.getByRole("button", { name }) as HTMLButtonElement;
}

function renderPanel(overrides: Partial<ComponentProps<typeof ContentReviewPanel>> = {}, strict = false) {
  const panel = <ContentReviewPanel presentationId={PRESENTATION_ID}
    draftSignature="saved-draft" savedSignature="saved-draft" dirty={false} disabled={false}
    onBusyChange={vi.fn()} onSelectSlide={vi.fn()} onApplied={vi.fn()} {...overrides} />;
  return render(strict ? <StrictMode>{panel}</StrictMode> : panel);
}

function renderEditor() {
  return render(<OutlineEditor presentation={makePresentation()} initial={makeOutline()} templates={TEMPLATES} />);
}

async function settleTimers(milliseconds = 0) {
  await act(async () => { await vi.advanceTimersByTimeAsync(milliseconds); });
}

describe("content review interactions", () => {
  it("submits one POST for a double click and disables both review actions while pending", async () => {
    const pending = deferredResponse();
    let latest: SavedContentReview | null = null;
    const http = mockHttp((call) => {
      if (call.path === `${BASE}/review-source`) return jsonResponse(makeSource({
        latest_review: latest, apply_available: Boolean(latest?.can_apply),
      }));
      if (call.path === `${BASE}/review` && call.method === "POST") return pending.promise;
      throw new Error(`Unexpected route ${call.method} ${call.path}`);
    });
    const user = userEvent.setup();
    renderPanel({}, true);
    await waitFor(() => expect(button("检查内容").disabled).toBe(false));

    await user.dblClick(button("检查内容"));
    expect(http.count("POST", `${BASE}/review`)).toBe(1);
    expect(button("检查内容").disabled).toBe(true);
    expect(button("检查并修订").disabled).toBe(true);
    expect(http.calls.find((call) => call.method === "POST")?.body?.max_revision_rounds).toBe(0);

    latest = makeReview();
    await act(async () => { pending.resolve(jsonResponse(latest)); });
    await screen.findByText("文本检查通过");
    expect(http.count("POST")).toBe(1);
  });

  it("cancels the in-flight request and only reads the saved result afterward", async () => {
    let reads = 0;
    const cancelled = makeReview({ can_apply: false, changed_slide_numbers: [],
      result: { ...makeResult(), status: "cancelled", message: "本轮检查已停止。", rounds_completed: 0 } });
    const http = mockHttp((call) => {
      if (call.path === `${BASE}/review-source`) {
        reads += 1;
        return jsonResponse(makeSource({ latest_review: reads > 1 ? cancelled : null }));
      }
      if (call.path === `${BASE}/review` && call.method === "POST") return pendingResponse(call.signal);
      throw new Error(`Unexpected route ${call.method} ${call.path}`);
    });
    const user = userEvent.setup();
    renderPanel();
    await waitFor(() => expect(button("检查内容").disabled).toBe(false));
    await user.click(button("检查内容"));
    const request = http.calls.find((call) => call.method === "POST");
    await user.click(button("取消检查"));

    await screen.findByText("检查已取消");
    expect(request?.signal?.aborted).toBe(true);
    expect(http.count("POST")).toBe(1);
    expect(http.count("GET", `${BASE}/review-source`)).toBe(2);
    expect(http.count("POST", `${BASE}/review/apply`)).toBe(0);
  });

  it("resumes a running job on mount, survives a read failure, and clears only that read error", async () => {
    vi.useFakeTimers();
    let reads = 0;
    const latest = makeReview();
    const http = mockHttp((call) => {
      if (call.method !== "GET" || call.path !== `${BASE}/review-source`) throw new Error("Only reads are allowed");
      reads += 1;
      if (reads === 2) throw new TypeError("Failed to fetch");
      return jsonResponse(reads < 3
        ? makeSource({ available: false, reason: "review_in_progress", message: "审核仍在进行。" })
        : makeSource({ latest_review: latest, apply_available: true }));
    });
    const onBusyChange = vi.fn();
    renderPanel({ onBusyChange });
    await settleTimers();
    expect(screen.getByText(/已有内容检查正在进行/)).not.toBeNull();
    expect(button("检查内容").disabled).toBe(true);
    expect(onBusyChange).toHaveBeenLastCalledWith(true);

    await settleTimers(5000);
    expect(screen.getByRole("alert").textContent).toContain("暂时无法读取检查状态");
    await settleTimers(5000);
    expect(screen.getByText("文本检查通过")).not.toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(onBusyChange).toHaveBeenLastCalledWith(false);
    expect(http.count("GET")).toBe(3);
    expect(http.count("POST")).toBe(0);
  });

  it("keeps a manual edit, disables old adoption, and saves it without making the old report current", async () => {
    let manuallySaved = false;
    let stored = makeOutline();
    const latest = makeReview();
    const http = mockHttp((call) => {
      if (call.path === `${BASE}/review-source`) return jsonResponse(manuallySaved
        ? makeSource({ available: false, reason: "outline_changed", message: "已保存的人工修改不匹配原稿，请继续编辑当前大纲。",
          latest_review: { ...latest, stale: true, can_apply: false }, apply_available: false })
        : makeSource({ latest_review: latest, apply_available: true }));
      if (call.method === "PUT" && call.path === OUTLINE_PATH) {
        manuallySaved = true;
        stored = call.body as unknown as PresentationOutline;
        return jsonResponse(stored);
      }
      throw new Error(`Unexpected route ${call.method} ${call.path}`);
    });
    const user = userEvent.setup();
    renderEditor();
    await waitFor(() => expect(button("采用修订稿（1 页）").disabled).toBe(false));
    const editor = screen.getByRole("textbox", { name: "儿童屏幕内容" }) as HTMLTextAreaElement;
    await user.clear(editor);
    await user.type(editor, "我重新写的海洋观察");

    expect(button("采用修订稿（1 页）").disabled).toBe(true);
    expect(button("保存草稿").disabled).toBe(false);
    expect(screen.getByText("有未保存的修改")).not.toBeNull();
    const leavingDirty = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(leavingDirty);
    expect(leavingDirty.defaultPrevented).toBe(true);

    await user.click(button("保存草稿"));
    await screen.findByText("检查结果已过期");
    expect(editor.value).toContain("我重新写的海洋观察");
    expect(stored.slides[0]?.content).toContain("我重新写的海洋观察");
    expect(stored.slides[0]?.content_contract).toEqual(makeOutline().slides[0]?.content_contract);
    expect(stored.slides.slice(1)).toEqual(makeOutline().slides.slice(1));
    expect(button("采用修订稿（1 页）").disabled).toBe(true);
    expect(screen.queryByText("文本检查通过")).toBeNull();
    expect(button("确认生成").disabled).toBe(false);
    expect(http.count("PUT", OUTLINE_PATH)).toBe(1);
    expect(http.count("POST")).toBe(0);
    const leavingSaved = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(leavingSaved);
    expect(leavingSaved.defaultPrevented).toBe(false);
  });

  it("uses an issue's page link to select and focus the actual outline page", async () => {
    const latest = makeReview({ can_apply: false, changed_slide_numbers: [],
      result: { ...makeResult(), status: "needs_revision", semantic_review: {
        needs_human: false, human_questions: [], findings: [{
          issue_id: "topic-2", criterion: "topic_focus", severity: "error", slide_no: 2,
          field_path: "screen_content.title", evidence: "认识海龟", requirement: "围绕外形比较安排观察。",
          explanation: "这一页需要提出具体的观察问题。", suggestion: "请幼儿比较海龟与鱼的外形。",
        }],
      } } });
    const http = mockHttp(() => jsonResponse(makeSource({ latest_review: latest })));
    const user = userEvent.setup();
    renderEditor();
    await screen.findByText("这一页需要提出具体的观察问题。");
    expect(screen.getByText("请幼儿比较海龟与鱼的外形。")).not.toBeNull();
    await user.click(button("查看第 2 页"));
    const editor = screen.getByRole("textbox", { name: "儿童屏幕内容" }) as HTMLTextAreaElement;
    await waitFor(() => {
      expect(editor.value).toContain("认识海龟");
      expect(document.activeElement).toBe(editor);
    });
    expect(http.count("POST")).toBe(0);
  });

  it("shows a reviewed candidate without editing the outline and applies it only after an explicit click", async () => {
    let latest: SavedContentReview | null = null;
    let applied = false;
    const http = mockHttp((call) => {
      if (call.path === `${BASE}/review-source`) return jsonResponse(makeSource({
        source_version: applied ? APPLIED_VERSION : SOURCE_VERSION,
        latest_review: latest, apply_available: Boolean(latest?.can_apply),
      }));
      if (call.method === "POST" && call.path === `${BASE}/review`) {
        latest = makeReview();
        return jsonResponse(latest);
      }
      if (call.method === "POST" && call.path === `${BASE}/review/apply`) {
        applied = true;
        latest = makeReview({ applied: true, stale: true, can_apply: false,
          applied_source_version: APPLIED_VERSION, message: "这份审核稿已经应用，不会重复覆盖大纲。" });
        return jsonResponse({ outlines: makeOutline(true), source_version: APPLIED_VERSION, message: "修订稿已采用并保存。" });
      }
      throw new Error(`Unexpected route ${call.method} ${call.path}`);
    });
    const user = userEvent.setup();
    renderEditor();
    await waitFor(() => expect(button("检查并修订").disabled).toBe(false));
    const editor = screen.getByRole("textbox", { name: "儿童屏幕内容" }) as HTMLTextAreaElement;
    await user.click(button("检查并修订"));
    await waitFor(() => expect(button("采用修订稿（1 页）").disabled).toBe(false));

    expect(editor.value).toContain("海底观察");
    expect(http.count("POST", `${BASE}/review/apply`)).toBe(0);
    expect(http.count("PUT")).toBe(0);
    const reviewRequest = http.calls.find((call) => call.path === `${BASE}/review`);
    expect(reviewRequest?.body).toMatchObject({ source_version: SOURCE_VERSION,
      max_revision_rounds: 1, timeout_seconds: 360, max_model_calls: 5 });
    expect(reviewRequest?.body?.request_id).toMatch(/^[0-9a-f-]{36}$/);
    await user.click(screen.getByText("第 1 页 · 查看修订前后"));
    expect(screen.getByText("修订前")).not.toBeNull();
    expect(screen.getByText("修订后")).not.toBeNull();

    await user.click(button("采用修订稿（1 页）"));
    await waitFor(() => expect(editor.value).toContain("海洋小侦探"));
    await waitFor(() => expect(button("修订稿已采用").disabled).toBe(true));
    expect(http.count("POST", `${BASE}/review`)).toBe(1);
    expect(http.count("POST", `${BASE}/review/apply`)).toBe(1);
    expect(http.calls.find((call) => call.path === `${BASE}/review/apply`)?.body).toEqual({
      review_id: makeReview().review_id, source_version: SOURCE_VERSION,
    });
    expect(http.count("PUT")).toBe(0);
  });

  it("preserves a useful 409 action message after a successful recovery GET and does not retry", async () => {
    let conflict = false;
    const message = "大纲已被修改，请重新读取资料后再检查。";
    const http = mockHttp((call) => {
      if (call.path === `${BASE}/review-source`) return jsonResponse(conflict
        ? makeSource({ available: false, reason: "outline_changed", message: "当前大纲已有人工修改。" }) : makeSource());
      if (call.method === "POST" && call.path === `${BASE}/review`) {
        conflict = true;
        return jsonResponse({ detail: { code: "version_conflict", message } }, 409);
      }
      throw new Error(`Unexpected route ${call.method} ${call.path}`);
    });
    const user = userEvent.setup();
    renderPanel();
    await waitFor(() => expect(button("检查内容").disabled).toBe(false));
    await user.click(button("检查内容"));
    await screen.findByText("当前大纲已有人工修改。");
    expect(screen.getByRole("alert").textContent).toBe(message);
    expect(button("检查内容").disabled).toBe(true);
    expect(http.count("POST")).toBe(1);
    expect(http.count("GET")).toBe(2);
  });

  it("recovers a committed adoption after its response is lost before allowing any outline writes", async () => {
    let committed = false;
    const persisted = makeOutline(true);
    persisted.slides[0]!.content += "\n\n• 其他老师后续保存的观察问题";
    const pendingOutline = deferredResponse();
    const http = mockHttp((call) => {
      if (call.path === `${BASE}/review-source`) return jsonResponse(makeSource({
        source_version: committed ? APPLIED_VERSION : SOURCE_VERSION,
        latest_review: makeReview({ applied: committed, stale: committed, can_apply: !committed,
          applied_source_version: committed ? APPLIED_VERSION : null }), apply_available: !committed,
      }));
      if (call.method === "POST" && call.path === `${BASE}/review/apply`) {
        committed = true;
        throw new TypeError("Failed to fetch");
      }
      if (call.method === "GET" && call.path === OUTLINE_PATH) return pendingOutline.promise;
      throw new Error(`Unexpected route ${call.method} ${call.path}`);
    });
    const user = userEvent.setup();
    renderEditor();
    await waitFor(() => expect(button("采用修订稿（1 页）").disabled).toBe(false));
    await user.click(button("采用修订稿（1 页）"));
    await waitFor(() => expect(http.count("GET", OUTLINE_PATH)).toBe(1));
    const editor = screen.getByRole("textbox", { name: "儿童屏幕内容" }) as HTMLTextAreaElement;
    expect(editor.value).toContain("海底观察");
    expect(editor.readOnly).toBe(true);
    expect(button("确认生成").disabled).toBe(true);
    expect(button("保存草稿").disabled).toBe(true);
    await user.click(button("确认生成"));
    expect(http.count("PUT")).toBe(0);

    await act(async () => { pendingOutline.resolve(jsonResponse(persisted)); });
    await waitFor(() => {
      expect(editor.value).toContain("海洋小侦探");
      expect(editor.value).toContain("其他老师后续保存的观察问题");
      expect(editor.readOnly).toBe(false);
      expect(button("确认生成").disabled).toBe(false);
    });
    expect(http.count("POST", `${BASE}/review/apply`)).toBe(1);
    expect(http.count("POST", `${BASE}/review`)).toBe(0);
    expect(http.count("PUT")).toBe(0);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps writes blocked if reading an adopted outline times out and recovers with a manual GET only", async () => {
    vi.useFakeTimers();
    let committed = false;
    let outlineReads = 0;
    const http = mockHttp((call) => {
      if (call.path === `${BASE}/review-source`) return jsonResponse(makeSource({
        source_version: committed ? APPLIED_VERSION : SOURCE_VERSION,
        latest_review: makeReview({ applied: committed, stale: committed, can_apply: !committed }),
        apply_available: !committed,
      }));
      if (call.method === "POST" && call.path === `${BASE}/review/apply`) {
        committed = true;
        throw new TypeError("Failed to fetch");
      }
      if (call.method === "GET" && call.path === OUTLINE_PATH) {
        outlineReads += 1;
        return outlineReads === 1 ? pendingResponse(call.signal) : jsonResponse(makeOutline(true));
      }
      throw new Error(`Unexpected route ${call.method} ${call.path}`);
    });
    renderEditor();
    await settleTimers();
    fireEvent.click(button("采用修订稿（1 页）"));
    await settleTimers();
    const read = http.calls.find((call) => call.path === OUTLINE_PATH);
    expect(read).toBeDefined();
    await settleTimers(20_000);
    expect(read?.signal?.aborted).toBe(true);
    expect(screen.getByText(/暂时无法同步服务器已保存的大纲/)).not.toBeNull();
    const editor = screen.getByRole("textbox", { name: "儿童屏幕内容" }) as HTMLTextAreaElement;
    expect(editor.value).toContain("海底观察");
    expect(editor.readOnly).toBe(true);
    expect(button("确认生成").disabled).toBe(true);
    expect(button("重新确认采用结果").disabled).toBe(false);

    fireEvent.click(button("重新确认采用结果"));
    await settleTimers();
    expect(editor.value).toContain("海洋小侦探");
    expect(editor.readOnly).toBe(false);
    expect(http.count("POST", `${BASE}/review/apply`)).toBe(1);
    expect(http.count("GET", OUTLINE_PATH)).toBe(2);
    expect(http.count("PUT")).toBe(0);
  });

  it("bounds initial source loading and leaves normal editing usable after a read timeout", async () => {
    vi.useFakeTimers();
    let reads = 0;
    const http = mockHttp((call) => {
      reads += 1;
      return reads === 1 ? pendingResponse(call.signal) : jsonResponse(makeSource());
    });
    renderEditor();
    const initialRead = http.calls[0];
    await settleTimers(20_000);
    expect(initialRead?.signal?.aborted).toBe(true);
    expect(screen.getByRole("alert").textContent).toContain("读取检查状态超时");
    expect(button("读取最近结果").disabled).toBe(false);
    expect(button("确认生成").disabled).toBe(false);
    fireEvent.click(button("读取最近结果"));
    await settleTimers();
    expect(button("检查内容").disabled).toBe(false);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(http.count("POST")).toBe(0);
  });

  it("bounds apply waiting but keeps protection until the same review is confirmed and synchronized", async () => {
    vi.useFakeTimers();
    let confirmed = false;
    const http = mockHttp((call) => {
      if (call.path === `${BASE}/review-source`) return jsonResponse(makeSource({
        source_version: confirmed ? APPLIED_VERSION : SOURCE_VERSION,
        latest_review: makeReview({ applied: confirmed, stale: confirmed, can_apply: !confirmed }),
        apply_available: !confirmed,
      }));
      if (call.method === "POST" && call.path === `${BASE}/review/apply`) return pendingResponse(call.signal);
      if (call.method === "GET" && call.path === OUTLINE_PATH) return jsonResponse(makeOutline(true));
      throw new Error(`Unexpected route ${call.method} ${call.path}`);
    });
    renderEditor();
    await settleTimers();
    fireEvent.click(button("采用修订稿（1 页）"));
    await settleTimers(30_000);
    const submitted = http.calls.find((call) => call.method === "POST");
    expect(submitted?.signal?.aborted).toBe(true);
    expect(screen.getByRole("alert").textContent).toContain("采用请求等待超时");
    const editor = screen.getByRole("textbox", { name: "儿童屏幕内容" }) as HTMLTextAreaElement;
    expect(editor.readOnly).toBe(true);
    expect(button("确认生成").disabled).toBe(true);
    expect(button("重新确认采用结果").disabled).toBe(false);
    expect(http.count("GET", OUTLINE_PATH)).toBe(0);

    confirmed = true;
    fireEvent.click(button("重新确认采用结果"));
    await settleTimers();
    expect(editor.value).toContain("海洋小侦探");
    expect(editor.readOnly).toBe(false);
    expect(button("确认生成").disabled).toBe(false);
    expect(http.count("POST")).toBe(1);
    expect(http.count("PUT")).toBe(0);
  });

  it("does not mistake a different review's adoption for confirmation of the pending request", async () => {
    let uncertain = false;
    const http = mockHttp((call) => {
      if (call.path === `${BASE}/review-source`) return jsonResponse(makeSource({
        latest_review: uncertain
          ? makeReview({ review_id: "22222222-2222-4222-8222-222222222222", applied: true, can_apply: false })
          : makeReview(), apply_available: !uncertain,
      }));
      if (call.method === "POST" && call.path === `${BASE}/review/apply`) {
        uncertain = true;
        throw new TypeError("Failed to fetch");
      }
      throw new Error(`Unexpected route ${call.method} ${call.path}`);
    });
    const user = userEvent.setup();
    renderEditor();
    await waitFor(() => expect(button("采用修订稿（1 页）").disabled).toBe(false));
    await user.click(button("采用修订稿（1 页）"));
    await waitFor(() => expect(button("重新确认采用结果").disabled).toBe(false));
    expect(button("确认生成").disabled).toBe(true);
    expect(http.count("GET", OUTLINE_PATH)).toBe(0);
    expect(http.count("POST")).toBe(1);
  });

  it("aborts the paid request on unmount without retrying or reading into the closed page", async () => {
    vi.useFakeTimers();
    const http = mockHttp((call) => {
      if (call.path === `${BASE}/review-source`) return jsonResponse(makeSource());
      if (call.path === `${BASE}/review` && call.method === "POST") return pendingResponse(call.signal);
      throw new Error(`Unexpected route ${call.method} ${call.path}`);
    });
    const view = renderPanel();
    await settleTimers();
    fireEvent.click(button("检查内容"));
    await settleTimers();
    const request = http.calls.find((call) => call.method === "POST");
    expect(request?.signal?.aborted).toBe(false);
    view.unmount();
    expect(request?.signal?.aborted).toBe(true);
    await settleTimers(400_000);
    expect(http.count("POST")).toBe(1);
    expect(http.count("GET")).toBe(1);
  });

  it("stops polling a running job when the page unmounts", async () => {
    vi.useFakeTimers();
    const http = mockHttp(() => jsonResponse(makeSource({ available: false, reason: "review_in_progress" })));
    const view = renderPanel();
    await settleTimers();
    expect(http.count("GET")).toBe(1);
    view.unmount();
    await settleTimers(30_000);
    expect(http.count("GET")).toBe(1);
    expect(http.count("POST")).toBe(0);
  });

  it("aborts an unfinished source read when the page unmounts", async () => {
    const http = mockHttp((call) => pendingResponse(call.signal));
    const view = renderPanel();
    expect(http.calls).toHaveLength(1);
    const read = http.calls[0];
    view.unmount();
    await act(async () => { await Promise.resolve(); });
    expect(read?.signal?.aborted).toBe(true);
    expect(http.calls).toHaveLength(1);
  });

  it("offers a read-only recovery button when initial status loading fails", async () => {
    let reads = 0;
    const http = mockHttp((call) => {
      if (call.method !== "GET") throw new Error("A recovery read must not create a review");
      reads += 1;
      if (reads === 1) throw new TypeError("Failed to fetch");
      return jsonResponse(makeSource());
    });
    const user = userEvent.setup();
    renderPanel();
    await screen.findByRole("alert");
    await user.click(button("读取最近结果"));
    await waitFor(() => expect(button("检查内容").disabled).toBe(false));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(http.count("GET")).toBe(2);
    expect(http.count("POST")).toBe(0);
  });
});
