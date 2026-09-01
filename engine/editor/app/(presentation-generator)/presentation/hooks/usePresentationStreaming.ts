import { useEffect, useRef } from "react";
import { useDispatch } from "react-redux";
import {
  clearPresentationData,
  setPresentationData,
  setStreaming,
  type PresentationData,
} from "@/store/slices/presentationGeneration";
import { jsonrepair } from "jsonrepair";
import { notify } from "@/components/ui/sonner";
import { MixpanelEvent, trackEvent } from "@/utils/mixpanel";
import { sanitizeAnalyticsError } from "@/utils/analytics";
import { getApiUrl, normalizeBackendAssetUrls } from "@/utils/api";
import { withBridgeSessionQuery } from "@/utils/teachnovaSession";
import { store } from "@/store/store";
import {
  isChatGptAuthRequiredMessage,
  requestChatGptReauth,
} from "@/utils/chatgptAuth";
import {
  mergeSingleSlidePreservingResolvedAssets,
  mergeSlidesPreservingResolvedAssets,
} from "../utils/streamAssetMerge";
import { isTemplateV2Slide } from "../../_shared/blank-slide";

// This GET starts paid per-slide content generation. Never reopen it automatically:
// a transient SSE error used to start the whole deck again from page 1 and duplicate
// gpt-5-mini charges. The backend checkpoints completed text before image work; a
// deliberate browser refresh can resume that saved state without silently paying twice.
const PAID_STREAM_AUTO_RETRY_COUNT = 0;

function settleStreamUrl(
  presentationId: string,
  status: "completed" | "failed"
) {
  const cleanUrl = new URL(window.location.href);
  cleanUrl.searchParams.delete("stream");
  window.history.replaceState({}, "", cleanUrl.toString());

  if (window.parent === window) return;
  let targetOrigin = "*";
  try {
    if (document.referrer) targetOrigin = new URL(document.referrer).origin;
  } catch {
    // The message contains no deck content or credentials. The outer shell
    // still validates both the sender origin and presentation id.
  }
  window.parent.postMessage(
    {
      type: "presenton:stream-settled",
      presentationId,
      status,
    },
    targetOrigin
  );
}

// 后端错误可能来自不同模型供应商；界面只显示稳定、可理解的中文提示。
function localizeStreamError(message: string): string {
  if (/image generation|openai image/i.test(message)) {
    return "图片生成失败，请重试。";
  }
  if (/network|connection|connect|timeout/i.test(message)) {
    return "生成服务连接失败，请检查网络后重试。";
  }
  return /[\u3400-\u9fff]/.test(message)
    ? message
    : "生成过程中出现错误，请重试。";
}

function mergePresentationPreservingTemplateData(
  incoming: PresentationData
): PresentationData {
  const prev = store.getState().presentationGeneration.presentationData;
  if (!prev) return incoming;

  return {
    ...prev,
    ...incoming,
    layout: incoming.layout ?? prev.layout,
    version: incoming.version ?? prev.version,
    theme: incoming.theme ?? prev.theme,
    structure: (incoming as any).structure ?? (prev as any).structure,
    slides: Array.isArray(incoming.slides)
      ? mergeSlidesPreservingResolvedAssets(prev.slides, incoming.slides)
      : prev.slides,
  } as PresentationData;
}

function parseStreamedSlideChunk(chunk: unknown): any | null {
  if (typeof chunk !== "string" || !chunk.trim()) return null;
  try {
    const parsed = JSON.parse(chunk);
    if (
      parsed &&
      typeof parsed === "object" &&
      !Array.isArray(parsed) &&
      typeof parsed.layout === "string" &&
      typeof parsed.index === "number" &&
      parsed.content &&
      typeof parsed.content === "object"
    ) {
      return parsed;
    }
  } catch {
    return null;
  }
  return null;
}

function contiguousSlidesByIndex(slides: unknown): any[] {
  if (!Array.isArray(slides)) return [];
  const byIndex = new Map<number, any>();
  for (const slide of slides) {
    if (!slide || typeof slide !== "object") continue;
    const index = Number((slide as any).index);
    if (!Number.isInteger(index) || index < 0) continue;
    byIndex.set(index, slide);
  }
  const contiguous: any[] = [];
  for (let index = 0; byIndex.has(index); index += 1) {
    contiguous.push(byIndex.get(index));
  }
  return contiguous;
}

function hasTemplateV2LayoutPayload(layout: unknown): boolean {
  if (!layout || typeof layout !== "object") return false;
  const layouts = (layout as any).layouts;
  if (Array.isArray(layouts)) return true;
  return Boolean(
    layouts &&
      typeof layouts === "object" &&
      Array.isArray((layouts as any).layouts)
  );
}

function isTemplateV2SlidePayload(slide: unknown): boolean {
  return isTemplateV2Slide(slide);
}

function isTemplateV2PresentationPayload(presentation: unknown): boolean {
  if (!presentation || typeof presentation !== "object") return false;
  const record = presentation as Record<string, unknown>;
  return (
    hasTemplateV2LayoutPayload(record.layout) ||
    (Array.isArray(record.slides) && record.slides.some(isTemplateV2SlidePayload))
  );
}

export const usePresentationStreaming = (
  presentationId: string,
  stream: string | null,
  setLoading: (loading: boolean) => void,
  setError: (error: boolean) => void,
  fetchUserSlides: () => void | Promise<unknown>,
  options: { preloadPresentationData?: boolean } = {}
) => {
  const dispatch = useDispatch();
  const previousSlidesLength = useRef(0);
  const preloadPresentationData = Boolean(options.preloadPresentationData);

  useEffect(() => {
    if (!stream) {
      fetchUserSlides();
      return;
    }

    let eventSource: EventSource | null = null;
    let accumulatedChunks = "";
    let isClosed = false;
    const shownAssetWarnings = new Set<string>();
    let preloadAttempted = false;
    let preloadRequest: Promise<void> | null = null;
    const streamStartedAt = Date.now();
    let streamIsTemplateV2 = preloadPresentationData;
    const pendingSlideChunks = new Map<number, any>();
    let nextSlideIndexToPublish = 0;

    const closeEventSource = () => {
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
    };

    const finalizeFailure = (
      description: string,
      options: { showToast?: boolean } = {}
    ) => {
      if (isClosed) return;
      if (streamIsTemplateV2) {
        trackEvent(MixpanelEvent.TemplateV2_Stream_Failed, {
          presentation_id: presentationId,
          retry_count: PAID_STREAM_AUTO_RETRY_COUNT,
          duration_ms: Date.now() - streamStartedAt,
          error_message: sanitizeAnalyticsError(description, "Stream failed"),
        });
      }
      isClosed = true;
      closeEventSource();
      setLoading(false);
      dispatch(setStreaming(false));

      const currentSlides =
        store.getState().presentationGeneration.presentationData?.slides;
      const hasPartialDeck = Array.isArray(currentSlides) && currentSlides.length > 0;
      setError(!hasPartialDeck);

      // Never reload over an in-memory deck on asset failure. The previous code
      // immediately called fetchUserSlides(), and a not-yet-flushed checkpoint could
      // replace eight visible pages with one blank slide. Keep the usable deck exactly
      // as the teacher saw it. Only a no-page failure probes the durable checkpoint.
      settleStreamUrl(presentationId, hasPartialDeck ? "completed" : "failed");
      if (!hasPartialDeck) {
        void Promise.resolve(fetchUserSlides())
          .then(() => {
            const refreshedSlides =
              store.getState().presentationGeneration.presentationData?.slides;
            if (Array.isArray(refreshedSlides) && refreshedSlides.length > 0) {
              setError(false);
            }
          })
          .catch(() => undefined);
      }

      if (options.showToast !== false) {
        if (hasPartialDeck) {
          notify.warning(
            "部分内容未生成完",
            `${localizeStreamError(description)} 已保留当前页面，不会自动重新生成或重复扣费；刷新页面可从后端检查点继续配图。`,
            { duration: 12_000 }
          );
        } else {
          notify.error("生成失败", localizeStreamError(description));
        }
      }
    };

    const preloadPreparedPresentation = async (force = false) => {
      if ((!preloadPresentationData && !force) || preloadAttempted) return;
      if (preloadRequest) return preloadRequest;

      preloadAttempted = true;
      preloadRequest = (async () => {
        try {
          const response = await fetch(
            getApiUrl(`/api/v1/ppt/presentation/${presentationId}`),
            {
              credentials: "include",
            }
          );
          if (!response.ok) {
            throw new Error("Failed to preload prepared presentation.");
          }
          const preparedPresentation = normalizeBackendAssetUrls(
            await response.json()
          );
          if (!isClosed) {
            const prev = store.getState().presentationGeneration.presentationData;
            streamIsTemplateV2 =
              streamIsTemplateV2 ||
              isTemplateV2PresentationPayload(preparedPresentation);
            dispatch(
              setPresentationData({
                ...(prev ?? {}),
                ...(preparedPresentation as PresentationData),
                slides: prev?.slides ?? (preparedPresentation as any).slides,
              } as PresentationData)
            );
          }
        } catch (error) {
          console.warn("Could not preload prepared presentation:", error);
        } finally {
          preloadRequest = null;
        }
      })();

      return preloadRequest;
    };

    const trackTemplateV2StreamCompleted = (presentation: unknown) => {
      if (!streamIsTemplateV2 && !isTemplateV2PresentationPayload(presentation)) {
        return;
      }
      streamIsTemplateV2 = true;
      const slides = isTemplateV2PresentationPayload(presentation)
        ? (presentation as Record<string, unknown>).slides
        : store.getState().presentationGeneration.presentationData?.slides;
      trackEvent(MixpanelEvent.TemplateV2_Stream_Completed, {
        presentation_id: presentationId,
        slide_count: Array.isArray(slides) ? slides.length : 0,
        retry_count: PAID_STREAM_AUTO_RETRY_COUNT,
        duration_ms: Date.now() - streamStartedAt,
      });
    };

    const publishStreamedSlide = (slide: any) => {
      const index = Number(slide?.index);
      if (!Number.isInteger(index) || index < 0) return;
      pendingSlideChunks.set(index, slide);

      while (pendingSlideChunks.has(nextSlideIndexToPublish)) {
        const nextSlide = pendingSlideChunks.get(nextSlideIndexToPublish);
        pendingSlideChunks.delete(nextSlideIndexToPublish);
        nextSlideIndexToPublish += 1;

        const prev = store.getState().presentationGeneration.presentationData;
        const normalizedSlide = normalizeBackendAssetUrls(nextSlide);
        const mergedSlides = mergeSingleSlidePreservingResolvedAssets(
          prev?.slides,
          normalizedSlide
        );
        dispatch(
          setPresentationData({
            ...(prev ?? {}),
            slides: mergedSlides,
          } as PresentationData)
        );
        previousSlidesLength.current = mergedSlides.length;
        setLoading(false);
        if (
          isTemplateV2SlidePayload(normalizedSlide) &&
          !hasTemplateV2LayoutPayload(prev?.layout)
        ) {
          streamIsTemplateV2 = true;
          void preloadPreparedPresentation(true);
        }
      }
    };

    const openStream = () => {
      closeEventSource();
      eventSource = new EventSource(
        withBridgeSessionQuery(
          getApiUrl(`/api/v1/ppt/presentation/stream/${presentationId}`)
        )
      );

      eventSource.addEventListener("response", (event) => {
        let data: any;
        try {
          data = JSON.parse(event.data);
        } catch {
          finalizeFailure("Failed to parse stream response.");
          return;
        }

        switch (data.type) {
          case "fonts": {
            if (data.fonts && typeof data.fonts === "object") {
              const prev = store.getState().presentationGeneration.presentationData;
              dispatch(
                setPresentationData({
                  ...(prev ?? {}),
                  fonts: data.fonts,
                  slides: prev?.slides ?? [],
                } as PresentationData)
              );
            }
            break;
          }

          case "slide_html": {
            const slideIndex = Number(data.index);
            const html = typeof data.html === "string" ? data.html : "";
            if (!Number.isFinite(slideIndex) || !html) break;

            const incomingSlide =
              data.slide && typeof data.slide === "object"
                ? data.slide
                : {
                    id: data.slide_id,
                    index: slideIndex,
                    layout: "smart-html",
                    layout_group: "smart-html",
                    content: { title: `Slide ${slideIndex + 1}` },
                    html_content: html,
                  };
            const normalizedSlide = normalizeBackendAssetUrls(incomingSlide);
            const prev = store.getState().presentationGeneration.presentationData;
            const mergedSlides = mergeSingleSlidePreservingResolvedAssets(
              prev?.slides,
              normalizedSlide
            );
            dispatch(
              setPresentationData({
                ...(prev ?? {}),
                slides: mergedSlides,
              } as PresentationData)
            );
            previousSlidesLength.current = mergedSlides.length;
            setLoading(false);
            break;
          }

          case "chunk": {
            accumulatedChunks += data.chunk;
            const streamedSlide = parseStreamedSlideChunk(data.chunk);
            if (streamedSlide) {
              publishStreamedSlide(streamedSlide);
            }

            try {
              const repairedJson = jsonrepair(accumulatedChunks);
              const partialData = JSON.parse(repairedJson);
              const normalizedPartialData = normalizeBackendAssetUrls(partialData);
              const contiguousSlides = contiguousSlidesByIndex(
                normalizedPartialData.slides
              );

              if (contiguousSlides.length > 0) {
                const prev =
                  store.getState().presentationGeneration.presentationData;
                const mergedSlides = mergeSlidesPreservingResolvedAssets(
                  prev?.slides,
                  contiguousSlides
                );
                dispatch(
                  setPresentationData({
                    ...(prev ?? {}),
                    ...normalizedPartialData,
                    slides: mergedSlides,
                  } as PresentationData)
                );
                previousSlidesLength.current = contiguousSlides.length;
                nextSlideIndexToPublish = Math.max(
                  nextSlideIndexToPublish,
                  contiguousSlides.length
                );
                setLoading(false);
              }
            } catch {
              // JSON isn't complete yet, continue accumulating
            }
            break;
          }

          case "slide_assets": {
            if (
              data.slide &&
              typeof data.slide === "object"
            ) {
              const prev = store.getState().presentationGeneration.presentationData;
              const normalizedSlide = normalizeBackendAssetUrls(data.slide);
              const mergedSlides = mergeSingleSlidePreservingResolvedAssets(
                prev?.slides,
                normalizedSlide
              );
              dispatch(
                setPresentationData({
                  ...(prev ?? {}),
                  slides: mergedSlides,
                } as PresentationData)
              );
              if (
                isTemplateV2SlidePayload(normalizedSlide) &&
                !hasTemplateV2LayoutPayload(prev?.layout)
              ) {
                streamIsTemplateV2 = true;
                void preloadPreparedPresentation(true);
              }
            }
            if (Array.isArray(data.warnings)) {
              for (const warning of data.warnings) {
                const detail =
                  warning &&
                  typeof warning === "object" &&
                  typeof warning.detail === "string"
                    ? warning.detail
                    : null;
                if (!detail || shownAssetWarnings.has(detail)) {
                  continue;
                }
                shownAssetWarnings.add(detail);
                notify.warning("部分图片生成失败", localizeStreamError(detail), {
                  duration: 12_000,
                });
              }
            }
            break;
          }

          case "complete":
            try {
              dispatch(
                setPresentationData(
                  mergePresentationPreservingTemplateData(
                    normalizeBackendAssetUrls(data.presentation) as PresentationData
                  )
                )
              );
              trackTemplateV2StreamCompleted(data.presentation);
              dispatch(setStreaming(false));
              setLoading(false);
              setError(false);
              isClosed = true;
              closeEventSource();

              settleStreamUrl(presentationId, "completed");
            } catch {
              finalizeFailure("Failed to parse final presentation payload.");
            }
            accumulatedChunks = "";
            break;

          case "closing":
            dispatch(
              setPresentationData(
                mergePresentationPreservingTemplateData(
                  normalizeBackendAssetUrls(data.presentation) as PresentationData
                )
              )
            );
            trackTemplateV2StreamCompleted(data.presentation);
            setLoading(false);
            setError(false);
            dispatch(setStreaming(false));
            isClosed = true;
            closeEventSource();

            settleStreamUrl(presentationId, "completed");
            break;
          case "error":
            if (isChatGptAuthRequiredMessage(data.detail)) {
              requestChatGptReauth({
                message: data.detail,
                source: "presentation-stream",
              });
              finalizeFailure(
                data.detail ||
                  "Your ChatGPT session expired. Please sign in again from Settings.",
                { showToast: false }
              );
              break;
            }
            finalizeFailure(
              data.detail ||
                "Failed to connect to the server. Please try again."
            );
            break;
        }
      });

      eventSource.onerror = (error) => {
        console.error("EventSource failed:", error);
        finalizeFailure("Failed to connect to the server. Please try again.");
      };
    };

    const startStream = async () => {
      dispatch(setStreaming(true));
      dispatch(clearPresentationData());
      trackEvent(MixpanelEvent.Presentation_Stream_API_Call);
      await preloadPreparedPresentation();
      if (!isClosed) {
        openStream();
      }
    };

    void startStream();

    return () => {
      isClosed = true;
      closeEventSource();
    };
  }, [
    presentationId,
    stream,
    dispatch,
    setLoading,
    setError,
    fetchUserSlides,
    preloadPresentationData,
  ]);
};