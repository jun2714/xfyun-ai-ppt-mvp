"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import Image from "next/image";
import { useRouter, useSearchParams } from "next/navigation";
import { useDispatch, useSelector } from "react-redux";
import { toast } from "sonner";

import { OverlayLoader } from "@/components/ui/overlay-loader";
import { cn } from "@/lib/utils";
import { RootState, store } from "@/store/store";
import {
  clearOutlines,
  setOutlines,
  setPresentationId,
  type OutlineItem,
} from "@/store/slices/presentationGeneration";
import { setPptGenUploadState } from "@/store/slices/presentationGenUpload";
import {
  clampSlideCountValue,
  limitOutlines,
  parseLimitedSlideCount,
  trimTextToWordLimit,
} from "@/utils/presentationLimits";
import { sanitizeAnalyticsError } from "@/utils/analytics";
import { MixpanelEvent, trackEvent } from "@/utils/mixpanel";

import Chat from "../../presentation/components/Chat";
import {
  LanguageType,
  PresentationConfig,
} from "../../upload/type";
import {
  buildTeachnovaPrompt,
  createTeachnovaDefaultConfig,
  parseTeachnovaPrompt,
} from "../../upload/product-defaults";
import { PresentationGenerationApi } from "../../services/api/presentation-generation";
import { DashboardApi } from "../../services/api/dashboard";
import { useOutlineManagement } from "../hooks/useOutlineManagement";
import { useOutlineStreaming } from "../hooks/useOutlineStreaming";
import { usePresentationGeneration } from "../hooks/usePresentationGeneration";
import EmptyStateView from "./EmptyStateView";
import GenerateButton from "./GenerateButton";
import OutlineContent from "./OutlineContent";
import OutlinePromptBar from "./OutlinePromptBar";
import OutlineStandardHeader from "./OutlineStandardHeader";
import TemplateSelection from "./TemplateSelection";
import { readPreferredTemplateId } from "../../utils/preferredTemplate";

const DEFAULT_OUTLINE_CONFIG: PresentationConfig =
  createTeachnovaDefaultConfig();

const normalizeOutlineConfig = (
  config: PresentationConfig
): PresentationConfig => ({
  ...config,
  slides: config.slides ? clampSlideCountValue(config.slides) || null : null,
});

const getDocumentPaths = (files: unknown): string[] => {
  if (!Array.isArray(files)) {
    return [];
  }

  return files
    .flat()
    .map((file) =>
      file && typeof file === "object" && "file_path" in file
        ? (file as { file_path?: unknown }).file_path
        : null
    )
    .filter((filePath): filePath is string => typeof filePath === "string");
};

const getOutlinesFromResponse = (outline: unknown): OutlineItem[] => {
  if (!outline || typeof outline !== "object") {
    return [];
  }

  const slides = (outline as { slides?: unknown }).slides;
  if (!Array.isArray(slides)) {
    return [];
  }

  return limitOutlines(
    slides.map((slide) => {
      const slideRecord =
        slide && typeof slide === "object"
          ? (slide as { content?: unknown; content_contract?: unknown })
          : null;
      const content = slideRecord?.content;

      if (typeof content === "string") {
        return {
          content,
          ...(slideRecord?.content_contract
            ? {
                content_contract:
                  slideRecord.content_contract as OutlineItem["content_contract"],
              }
            : {}),
        };
      }
      if (content == null) {
        return { content: "" };
      }
      return { content: String(content) };
    })
  );
};

const scrollToPageTop = () => {
  window.requestAnimationFrame(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  });
};

const OutlinePage: React.FC = () => {
  const dispatch = useDispatch();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { presentation_id, outlines } = useSelector(
    (state: RootState) => state.presentationGeneration
  );
  const {
    config: savedConfig,
    files,
    generationMode,
    requestContent,
    requestContext,
  } = useSelector((state: RootState) => state.pptGenUpload);

  // Both creation modes start by generating and reviewing the outline.
  // Template selection happens only after the outline is confirmed.
  const [isTemplateStage, setIsTemplateStage] = useState(false);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(
    null
  );

  useEffect(() => {
    const preferred = readPreferredTemplateId();
    if (preferred) {
      setSelectedTemplateId(preferred);
    }
  }, []);
  const [draftConfig, setDraftConfig] = useState<PresentationConfig>(
    savedConfig ? normalizeOutlineConfig(savedConfig) : DEFAULT_OUTLINE_CONFIG
  );
  const [isRegeneratingOutline, setIsRegeneratingOutline] = useState(false);
  const [hasOutlineStreamFinished, setHasOutlineStreamFinished] =
    useState(false);

  useEffect(() => {
    const urlPresentationId = searchParams.get("id");
    const urlMode = searchParams.get("mode");
    if (urlPresentationId && urlPresentationId !== presentation_id) {
      dispatch(setPresentationId(urlPresentationId));
    }
    if (urlMode === "smart" || urlMode === "standard") {
      dispatch(setPptGenUploadState({ generationMode: urlMode }));
    }
  }, [dispatch, presentation_id, searchParams]);

  const streamState = useOutlineStreaming(
    presentation_id,
    !isTemplateStage
  );
  const { handleDragEnd, handleAddSlide } = useOutlineManagement(outlines);
  const { loadingState, handleSubmit, handleSmartSubmit } =
    usePresentationGeneration(presentation_id);

  const documentPaths = useMemo(() => getDocumentPaths(files), [files]);
  const outlineControlsBusy =
    isRegeneratingOutline || streamState.isLoading || streamState.isStreaming;
  const isOutlineReady = hasOutlineStreamFinished && !outlineControlsBusy;
  const isOutlineAssistantVisible = !isTemplateStage;
  const isRegenerateDisabled = !isOutlineReady;
  const outlineStreamFinished =
    !isTemplateStage &&
    !outlineControlsBusy &&
    streamState.statusMessage === "大纲已就绪";

  useEffect(() => {
    if (savedConfig) {
      setDraftConfig(normalizeOutlineConfig(savedConfig));
    }
  }, [savedConfig]);

  useEffect(() => {
    if (!presentation_id || savedConfig) return;
    let cancelled = false;

    void DashboardApi.getPresentation(presentation_id, { cache: "no-store" })
      .then((presentation) => {
        if (cancelled) return;
        const defaults = createTeachnovaDefaultConfig();
        const requestContent =
          typeof presentation.content === "string"
            ? presentation.content
            : presentation.prompt || "";
        const parsed = parseTeachnovaPrompt(requestContent);
        const restoredConfig = normalizeOutlineConfig({
          ...defaults,
          slides:
            typeof presentation.n_slides === "number" &&
            presentation.n_slides > 0
              ? String(presentation.n_slides)
              : null,
          language:
            presentation.language?.trim()
              ? (presentation.language as PresentationConfig["language"])
              : defaults.language,
          prompt: parsed.topic,
          tone:
            presentation.tone
              ? (presentation.tone as PresentationConfig["tone"])
              : defaults.tone,
          verbosity:
            presentation.verbosity
              ? (presentation.verbosity as PresentationConfig["verbosity"])
              : defaults.verbosity,
        });

        setDraftConfig(restoredConfig);
        dispatch(
          setPptGenUploadState({
            config: restoredConfig,
            generationMode:
              presentation.generation_mode === "smart"
                ? "smart"
                : "standard",
            requestContent,
            requestContext: parsed.teachingContext,
          })
        );
      })
      .catch((error) => {
        console.error("Failed to restore outline generation config", error);
      });

    return () => {
      cancelled = true;
    };
  }, [dispatch, presentation_id, savedConfig]);

  useEffect(() => {
    setHasOutlineStreamFinished(false);
  }, [presentation_id]);

  useEffect(() => {
    if (!presentation_id) {
      setHasOutlineStreamFinished(false);
      return;
    }

    if (outlineStreamFinished) {
      setHasOutlineStreamFinished(true);
    }
  }, [outlineStreamFinished, presentation_id]);

  const handleReturnToOutline = () => {
    setIsTemplateStage(false);
    scrollToPageTop();
  };

  const handleConfigChange = (
    key: keyof PresentationConfig,
    value: unknown
  ) => {
    const nextValue =
      key === "slides" && typeof value === "string"
        ? clampSlideCountValue(value)
        : value;

    setDraftConfig((previous) => ({
      ...previous,
      [key]: nextValue,
    }));
  };

  const handleTemplateSelect = useCallback(
    async (template: {
      id: string;
      name: string;
      source: "default" | "custom";
      position: number;
    }) => {
      setSelectedTemplateId(template.id);
      await handleSubmit(template.id);
    },
    [handleSubmit]
  );

  const handleOutlineContinue = useCallback(async () => {
    if (!isOutlineReady) return;
    if (generationMode === "smart") {
      await handleSmartSubmit();
      return;
    }
    setIsTemplateStage(true);
    scrollToPageTop();
  }, [generationMode, handleSmartSubmit, isOutlineReady]);

  const handleRegenerateOutline = useCallback(async () => {
    if (outlineControlsBusy) {
      return;
    }

    if (!isOutlineReady) {
      return;
    }

    if (!draftConfig.language) {
      toast.error("请选择语言");
      return;
    }

    if (documentPaths.length > 0 && draftConfig.language === LanguageType.Auto) {
      toast.error("使用文档重新生成前，请先选择语言");
      return;
    }

    if (!draftConfig.prompt.trim() && documentPaths.length === 0) {
      toast.error("请提供主题或文档");
      return;
    }

    setIsRegeneratingOutline(true);
    setHasOutlineStreamFinished(false);
    trackEvent(MixpanelEvent.TemplateV2_Outline_Regeneration_Started, {
      presentation_id,
      generation_mode: generationMode,
      prompt_present: draftConfig.prompt.trim().length > 0,
      document_count: documentPaths.length,
      slide_count: parseLimitedSlideCount(draftConfig.slides),
      language: draftConfig.language,
      tone: draftConfig.tone,
      verbosity: draftConfig.verbosity,
      web_search: !!draftConfig.webSearch,
      include_title_slide: !!draftConfig.includeTitleSlide,
      include_table_of_contents: !!draftConfig.includeTableOfContents,
    });

    try {
      const regenerationContent =
        savedConfig &&
        draftConfig.prompt === savedConfig.prompt &&
        requestContent
          ? requestContent
          : buildTeachnovaPrompt(
              draftConfig.prompt,
              requestContext || {}
            );
      const createResponse = await PresentationGenerationApi.createPresentation({
        content: regenerationContent,
        version: "v2-standard",
        n_slides: parseLimitedSlideCount(draftConfig.slides),
        file_paths: documentPaths,
        language: draftConfig.language ?? "",
        tone: draftConfig.tone,
        verbosity: draftConfig.verbosity,
        instructions: draftConfig.instructions || null,
        include_table_of_contents: !!draftConfig.includeTableOfContents,
        include_title_slide: !!draftConfig.includeTitleSlide,
        web_search: !!draftConfig.webSearch,
        generation_mode: generationMode,
      });

      dispatch(
        setPptGenUploadState({
          config: draftConfig,
          files,
          generationMode,
          requestContent: regenerationContent,
          requestContext,
        })
      );
      dispatch(clearOutlines());
      dispatch(setPresentationId(createResponse.id));
      router.replace(
        `/outline?id=${createResponse.id}&mode=${generationMode}`
      );
      trackEvent(MixpanelEvent.TemplateV2_Outline_Regeneration_Completed, {
        old_presentation_id: presentation_id,
        new_presentation_id: createResponse.id,
        generation_mode: generationMode,
      });
    } catch (error: unknown) {
      console.error("Error regenerating outline", error);
      trackEvent(MixpanelEvent.TemplateV2_Outline_Regeneration_Failed, {
        presentation_id,
        generation_mode: generationMode,
        error_message: sanitizeAnalyticsError(
          error,
          "重新生成大纲失败"
        ),
      });
      toast.error("大纲错误", {
        description:
          error instanceof Error
            ? error.message
          : "重新生成大纲失败。",
      });
    } finally {
      setIsRegeneratingOutline(false);
    }
  }, [
    dispatch,
    documentPaths,
    draftConfig,
    files,
    generationMode,
    isOutlineReady,
    outlineControlsBusy,
    presentation_id,
    requestContent,
    requestContext,
    router,
    savedConfig,
  ]);

  const handleUpdateOutline = (index: number, newContent: string) => {
    const slideIndex = index - 1;
    if (!outlines[slideIndex]) return;

    const limitedContent = trimTextToWordLimit(newContent);
    if (outlines[slideIndex].content === limitedContent) return;

    const updatedOutlines = [...outlines];
    updatedOutlines[slideIndex] = {
      ...updatedOutlines[slideIndex],
      content: limitedContent,
      // The structural contract came from the previous text. Removing it
      // prevents a manual edit from silently reusing stale capacity metadata.
      content_contract: undefined,
    };
    dispatch(setOutlines(updatedOutlines));
  };

  const handleOutlineChanged = useCallback(async () => {
    if (!presentation_id) {
      return;
    }

    const outline = await PresentationGenerationApi.getOutlines(presentation_id);
    dispatch(setOutlines(getOutlinesFromResponse(outline)));
  }, [dispatch, presentation_id]);

  const handleBeforeOutlineChatSend = useCallback(async () => {
    if (!presentation_id) {
      return;
    }

    const latestOutlines =
      store.getState().presentationGeneration.outlines;
    await PresentationGenerationApi.updateOutlines(
      presentation_id,
      latestOutlines
    );
  }, [presentation_id]);

  if (!presentation_id) {
    return (
      <div className="min-h-screen bg-[#FEFEFF]">
        <OutlineStandardHeader
          title="生成大纲"
          onBack={() => router.push("/dashboard")}
        />
        <EmptyStateView />
      </div>
    );
  }

  return (
    <div
      className={cn(
        "min-h-screen overflow-x-clip font-syne",
        isTemplateStage ? "bg-[#FEFEFF]" : "bg-[#F6F6F9]"
      )}
    >
      <OverlayLoader
        show={loadingState.isLoading}
        text={loadingState.message}
        showProgress={loadingState.showProgress}
        duration={loadingState.duration}
      />

      <OutlineStandardHeader
        title={isTemplateStage ? "选择模板" : "确认大纲"}
        onBack={() => {
          if (isTemplateStage) {
            handleReturnToOutline();
            return;
          }
          router.push("/upload");
        }}
      />

      {isTemplateStage ? (
        <main className="mx-auto w-full max-w-[1440px] px-5 pb-12 pt-10 sm:px-10 lg:px-20">
          <TemplateSelection
            presentationId={presentation_id}
            selectedTemplateId={selectedTemplateId}
            onSelectTemplate={handleTemplateSelect}
          />
        </main>
      ) : (
        <>
          <div className="lg:mr-[369px]">
            <main className="mx-auto w-[calc(100%-2.5rem)] max-w-[967px] pb-28 pt-10 sm:w-[calc(100%-5rem)]">
              <OutlinePromptBar
                config={draftConfig}
                disabled={outlineControlsBusy}
                isBusy={outlineControlsBusy}
                regenerateDisabled={isRegenerateDisabled}
                onConfigChange={handleConfigChange}
                onRegenerate={handleRegenerateOutline}
              />

              <div className="mt-12">
                <OutlineContent
                  outlines={outlines}
                  isLoading={streamState.isLoading}
                  isStreaming={streamState.isStreaming}
                  activeSlideIndex={streamState.activeSlideIndex}
                  highestActiveIndex={streamState.highestActiveIndex}
                  statusMessage={streamState.statusMessage}
                  onDragEnd={handleDragEnd}
                  onAddSlide={handleAddSlide}
                  onUpdateOutline={handleUpdateOutline}
                />
              </div>
            </main>
          </div>

          {isOutlineAssistantVisible && (
            <aside className="mx-auto mb-28 mt-8 flex h-[600px] w-[calc(100%-2.5rem)] overflow-hidden border border-[#EDEEEF] bg-[#FEFEFF] sm:w-[calc(100%-5rem)] lg:fixed lg:bottom-0 lg:right-0 lg:top-[68px] lg:z-40 lg:mx-0 lg:mb-0 lg:mt-0 lg:h-auto lg:w-[369px] lg:border-0">
              <nav
                className="flex w-[70px] shrink-0 flex-col items-center gap-5 px-1.5 py-2"
                aria-label="大纲工具"
              >
                <div className="flex w-full flex-col items-center rounded-[10px] bg-[#F4F3FF]/60 py-7">
                  <div className="flex rounded-[10px] border border-[#EDEEEF] bg-white p-1.5 shadow-[0_6.6px_6.6px_rgba(124,81,248,0.14)]">
                    <Image
                      src="/ai-star.svg"
                      alt=""
                      width={19}
                      height={18}
                      className="h-[18px] w-[19px]"
                    />
                  </div>
                  <span className="mt-1 text-xs font-normal text-[#7A5AF8]">
                    AI
                  </span>
                </div>
                <span
                  className="h-px w-[30px] bg-[#EDEEEF]"
                  aria-hidden="true"
                />
              </nav>

              <div className="min-w-0 flex-1">
                <Chat
                  key={presentation_id}
                  presentationId={presentation_id}
                  presentationType={generationMode}
                  variant="outline"
                  useEditorLayout
                  inputDisabled={!isOutlineReady}
                  onBeforeSend={handleBeforeOutlineChatSend}
                  onPresentationChanged={handleOutlineChanged}
                />
              </div>
            </aside>
          )}

          <div className="pointer-events-none fixed bottom-6 left-5 right-5 z-50 flex justify-center sm:left-10 sm:right-10 lg:left-0 lg:right-[369px]">
            <div className="pointer-events-auto">
              <GenerateButton
                loadingState={loadingState}
                streamState={streamState}
                canContinue={isOutlineReady}
                onSubmit={() => void handleOutlineContinue()}
              />
            </div>
          </div>
        </>
      )}
    </div>
  );
};

export default OutlinePage;
