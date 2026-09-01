import { useEffect, useRef, useState } from "react";
import { useDispatch } from "react-redux";
import { notify } from "@/components/ui/sonner";
import {
  setOutlines,
  type OutlineItem,
} from "@/store/slices/presentationGeneration";
import { jsonrepair } from "jsonrepair";
import { getApiUrl } from "@/utils/api";
import { withBridgeSessionQuery } from "@/utils/teachnovaSession";
import { limitOutlines } from "@/utils/presentationLimits";
import {
  isChatGptAuthRequiredMessage,
  requestChatGptReauth,
} from "@/utils/chatgptAuth";

const MAX_STREAM_RETRIES = 3;
const STREAM_RETRY_DELAY_MS = 1_000;
const DEFAULT_STATUS_MESSAGE = "正在准备演示大纲…";

const readableStreamError = (detail: unknown): string => {
  const message = typeof detail === "string" ? detail.trim() : "";
  if (/timed? out|timeout/i.test(message)) {
    return "模型生成大纲超时，请重试。";
  }
  if (/quality|质检|校验/i.test(message)) {
    return message || "幼教课堂大纲未通过质量校验，请调整主题后重试。";
  }
  return message || "大纲生成失败，请重试。";
};

const outlineItemsFromPayload = (payload: unknown): OutlineItem[] => {
  if (!payload || typeof payload !== "object") return [];
  const slides = (payload as { slides?: unknown }).slides;
  if (!Array.isArray(slides)) return [];
  return limitOutlines(
    slides.map((slide) => {
      if (!slide || typeof slide !== "object") {
        return { content: String(slide ?? "") };
      }
      const item = slide as {
        content?: unknown;
        content_contract?: OutlineItem["content_contract"];
      };
      return {
        content:
          typeof item.content === "string"
            ? item.content
            : String(item.content ?? ""),
        ...(item.content_contract
          ? { content_contract: item.content_contract }
          : {}),
      };
    })
  );
};

export const useOutlineStreaming = (
  presentationId: string | null,
  enabled = true,
  planner: "standard" | "kindergarten" = "standard"
) => {
  const dispatch = useDispatch();
  const [isStreaming, setIsStreaming] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [activeSlideIndex, setActiveSlideIndex] = useState<number | null>(null);
  const [highestActiveIndex, setHighestActiveIndex] = useState<number>(-1);
  const [statusMessage, setStatusMessage] = useState(DEFAULT_STATUS_MESSAGE);
  const [errorMessage, setErrorMessage] = useState("");
  const prevSlidesRef = useRef<OutlineItem[]>([]);
  const activeIndexRef = useRef<number>(-1);
  const highestIndexRef = useRef<number>(-1);

  useEffect(() => {
    const resetStreamingState = (message = DEFAULT_STATUS_MESSAGE) => {
      setIsStreaming(false);
      setIsLoading(false);
      setActiveSlideIndex(null);
      setHighestActiveIndex(-1);
      setStatusMessage(message);
      prevSlidesRef.current = [];
      activeIndexRef.current = -1;
      highestIndexRef.current = -1;
    };

    if (!enabled || !presentationId) {
      setErrorMessage("");
      resetStreamingState();
      return;
    }

    let eventSource: EventSource | null = null;
    let accumulatedChunks = "";
    let retryCount = 0;
    let isClosed = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    const closeEventSource = () => {
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
    };

    const clearRetryTimer = () => {
      if (retryTimer) {
        clearTimeout(retryTimer);
        retryTimer = null;
      }
    };

    const failStream = (detail: unknown) => {
      const message = readableStreamError(detail);
      isClosed = true;
      closeEventSource();
      clearRetryTimer();
      setIsStreaming(false);
      setIsLoading(false);
      setActiveSlideIndex(null);
      setHighestActiveIndex(-1);
      setErrorMessage(message);
      setStatusMessage(`大纲生成失败：${message}`);
      notify.error("大纲生成失败", message);
    };

    const scheduleRetry = (reason: string): boolean => {
      if (retryCount >= MAX_STREAM_RETRIES || isClosed) {
        return false;
      }

      retryCount += 1;
      const retryDelay = STREAM_RETRY_DELAY_MS * retryCount;
      console.warn(
        `Outline stream retry ${retryCount}/${MAX_STREAM_RETRIES}: ${reason}`
      );

      closeEventSource();
      clearRetryTimer();
      accumulatedChunks = "";
      prevSlidesRef.current = [];
      activeIndexRef.current = -1;
      highestIndexRef.current = -1;
      setStatusMessage("正在重新连接大纲流…");

      retryTimer = setTimeout(() => {
        if (!isClosed) {
          openStream();
        }
      }, retryDelay);

      return true;
    };

    const openStream = () => {
      closeEventSource();
      const streamPath =
        planner === "kindergarten"
          ? `/api/v1/ppt/kindergarten/presentation/outline/stream/${presentationId}`
          : `/api/v1/ppt/outlines/stream/${presentationId}`;
      eventSource = new EventSource(
        withBridgeSessionQuery(getApiUrl(streamPath))
      );

      eventSource.addEventListener("response", (event) => {
        let data: any;
        try {
          data = JSON.parse(event.data);
        } catch {
          if (!scheduleRetry("invalid SSE payload")) {
            failStream("大纲流返回了无法解析的数据，请重试。");
          }
          return;
        }

        switch (data.type) {
          case "status":
            if (data.status) {
              setStatusMessage(data.status);
            }
            break;

          case "chunk":
            accumulatedChunks += data.chunk;
            try {
              const repairedJson = jsonrepair(accumulatedChunks);
              const partialData = JSON.parse(repairedJson);

              if (partialData.slides) {
                const nextSlides = outlineItemsFromPayload(partialData);
                try {
                  const prev = prevSlidesRef.current || [];
                  let changedIndex: number | null = null;
                  const maxLen = Math.max(prev.length, nextSlides.length);
                  for (let i = 0; i < maxLen; i++) {
                    const prevContent = prev[i]?.content;
                    const nextContent = nextSlides[i]?.content;
                    if (nextContent !== prevContent) {
                      changedIndex = i;
                    }
                  }
                  const prevActive = activeIndexRef.current;
                  let nextActive = changedIndex ?? prevActive;
                  if (nextActive < prevActive) {
                    nextActive = prevActive;
                  }
                  activeIndexRef.current = nextActive;
                  setActiveSlideIndex(nextActive);

                  if (nextActive > highestIndexRef.current) {
                    highestIndexRef.current = nextActive;
                    setHighestActiveIndex(nextActive);
                  }
                } catch {}

                prevSlidesRef.current = nextSlides;
                dispatch(setOutlines(nextSlides));
                setIsLoading(false);
              }
            } catch {
              // JSON is not complete yet, so keep accumulating chunks.
            }
            break;

          case "kindergarten_chunk":
            // Kindergarten planning streams its richer lesson-plan JSON before it
            // is converted into the reviewable presentation outline. Keep the
            // connection visibly alive; the validated `outline` event below is
            // the first payload safe to render/edit as slides.
            accumulatedChunks += data.chunk || "";
            setIsLoading(false);
            if (!data.status) {
              setStatusMessage("AI 正在规划幼教课堂大纲…");
            }
            break;

          case "outline": {
            const nextSlides = outlineItemsFromPayload(data.outline);
            if (nextSlides.length) {
              prevSlidesRef.current = nextSlides;
              dispatch(setOutlines(nextSlides));
              setIsLoading(false);
              setActiveSlideIndex(null);
              setHighestActiveIndex(-1);
              setStatusMessage("正在完成大纲…");
            }
            break;
          }

          case "complete":
            try {
              const completedSlides = outlineItemsFromPayload(
                data.presentation?.outlines
              );
              const outlinesData = completedSlides.length
                ? completedSlides
                : prevSlidesRef.current;
              if (!outlinesData.length) {
                throw new Error("complete payload did not include outlines");
              }
              dispatch(setOutlines(outlinesData));
              setIsStreaming(false);
              setIsLoading(false);
              setActiveSlideIndex(null);
              setHighestActiveIndex(-1);
              setStatusMessage("大纲已就绪");
              setErrorMessage("");
              prevSlidesRef.current = outlinesData;
              activeIndexRef.current = -1;
              highestIndexRef.current = -1;
              isClosed = true;
              closeEventSource();
              clearRetryTimer();
              retryCount = 0;
            } catch {
              if (!scheduleRetry("failed to parse complete payload")) {
                failStream("大纲已经生成，但最终数据解析失败，请重试。");
              }
            }
            accumulatedChunks = "";
            break;

          case "closing":
            setErrorMessage("");
            resetStreamingState("大纲已就绪");
            isClosed = true;
            closeEventSource();
            clearRetryTimer();
            retryCount = 0;
            break;

          case "error":
            if (isChatGptAuthRequiredMessage(data.detail)) {
              resetStreamingState();
              closeEventSource();
              requestChatGptReauth({
                message: data.detail,
                source: "outline-stream",
              });
              break;
            }
            // An explicit server-side SSE error is terminal for this model run.
            // Retrying it silently used to repeat the same paid timeout several
            // times while the UI appeared stuck on "正在生成大纲".
            failStream(data.detail || "大纲生成服务返回错误，请重试。");
            break;
        }
      });

      eventSource.onerror = () => {
        if (isClosed) return;
        if (!scheduleRetry("connection lost")) {
          failStream("无法连接大纲生成服务，请检查服务后重试。");
        }
      };
    };

    setErrorMessage("");
    setStatusMessage(DEFAULT_STATUS_MESSAGE);
    setIsStreaming(true);
    setIsLoading(true);
    openStream();

    return () => {
      isClosed = true;
      closeEventSource();
      clearRetryTimer();
    };
  }, [presentationId, dispatch, enabled, planner]);

  return {
    isStreaming,
    isLoading,
    activeSlideIndex,
    highestActiveIndex,
    statusMessage,
    errorMessage,
  };
};
