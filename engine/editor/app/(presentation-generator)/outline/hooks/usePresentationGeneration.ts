import { useState, useCallback } from "react";
import { useDispatch } from "react-redux";
import { usePathname, useRouter } from "next/navigation";
import { notify } from "@/components/ui/sonner";
import { clearPresentationData } from "@/store/slices/presentationGeneration";
import { PresentationGenerationApi } from "../../services/api/presentation-generation";
import { LoadingState } from "../types/index";

import { MixpanelEvent, trackEvent } from "@/utils/mixpanel";
import { sanitizeAnalyticsError } from "@/utils/analytics";
import {
  limitOutlines,
  MAX_NUMBER_OF_SLIDES,
} from "@/utils/presentationLimits";
import { store } from "@/store/store";

const DEFAULT_LOADING_STATE: LoadingState = {
  message: "",
  isLoading: false,
  showProgress: false,
  duration: 0,
};

export const usePresentationGeneration = (
  presentationId: string | null
) => {
  const dispatch = useDispatch();
  const router = useRouter();
  const pathname = usePathname();
  const [loadingState, setLoadingState] = useState<LoadingState>(
    DEFAULT_LOADING_STATE
  );

  const validateInputs = useCallback(
    (
      currentOutlines: { content: string }[] | null,
      selectedTemplateId?: string | null
    ) => {
      if (!currentOutlines || currentOutlines.length === 0) {
        notify.warning(
          "大纲尚未就绪",
          "请等待大纲生成完成后再继续。"
        );
        return false;
      }

      if (selectedTemplateId === null) {
        notify.warning(
          "尚未选择模板",
          "请选择模板后再生成演示文稿。"
        );
        return false;
      }

      if (currentOutlines.length > MAX_NUMBER_OF_SLIDES) {
        notify.warning(
          "大纲页数超出限制",
          `请将大纲控制在 ${MAX_NUMBER_OF_SLIDES} 页以内。`
        );
        return false;
      }

      return true;
    },
    []
  );

  const clearTheme = () => {
    const element = document.getElementById("presentation-page");
    if (!element) return;
    element.style.removeProperty("--primary-color");
    element.style.removeProperty("--background-color");
    element.style.removeProperty("--card-color");
    element.style.removeProperty("--stroke");
    element.style.removeProperty("--primary-text");
    element.style.removeProperty("--background-text");
    element.style.removeProperty("--graph-0");
    element.style.removeProperty("--graph-1");
    element.style.removeProperty("--graph-2");
    element.style.removeProperty("--graph-3");
    element.style.removeProperty("--graph-4");
    element.style.removeProperty("--graph-5");
    element.style.removeProperty("--graph-6");
    element.style.removeProperty("--graph-7");
    element.style.removeProperty("--graph-8");
    element.style.removeProperty("--graph-9");
  };

  const handleSubmit = useCallback(async (selectedTemplateId: string) => {
    const latestOutlines = store.getState().presentationGeneration.outlines;
    if (!validateInputs(latestOutlines, selectedTemplateId)) return;
    const preparedOutlines = limitOutlines(latestOutlines);

    trackEvent(MixpanelEvent.Outline_Presentation_Generation_Started, {
      pathname,
      presentation_id: presentationId,
      outline_count: preparedOutlines.length,
      template_id: selectedTemplateId,
    });

    setLoadingState({
      message: "正在准备模板排版与配图…",
      isLoading: true,
      showProgress: true,
      duration: 30,
    });

    try {
      const title =
        preparedOutlines[0]?.content
          .split(/\r?\n/)
          .find((line) => line.trim())
          ?.replace(/^\s{0,3}#{1,6}\s*/, "")
          .replace(/\*\*|__/g, "")
          .trim() || undefined;
      const response = await PresentationGenerationApi.presentationPrepare({
        presentation_id: presentationId,
        outlines: preparedOutlines,
        layout: selectedTemplateId,
        title,
      });

      if (response) {
        trackEvent(MixpanelEvent.TemplateV2_Prepare_Completed, {
          presentation_id: presentationId,
          template_id: selectedTemplateId,
          outline_count: preparedOutlines.length,
        });
        dispatch(clearPresentationData());
        clearTheme();
        router.replace(
          `/presentation?id=${presentationId}&stream=true&type=standard`
        );
      }
    } catch (error: any) {
      console.error("Error In Presentation Generation(prepare).", error);
      trackEvent(MixpanelEvent.TemplateV2_Prepare_Failed, {
        presentation_id: presentationId,
        template_id: selectedTemplateId,
        outline_count: preparedOutlines.length,
        error_message: sanitizeAnalyticsError(
          error,
          "Error in presentation generation"
        ),
      });
      notify.error(
        "Generation error",
        error.message || "Error in presentation generation."
      );
    } finally {
      setLoadingState(DEFAULT_LOADING_STATE);
    }
  }, [validateInputs, presentationId, dispatch, router, pathname]);

  const handleSmartSubmit = useCallback(async () => {
    const latestOutlines = store.getState().presentationGeneration.outlines;
    if (!validateInputs(latestOutlines)) return;
    if (!presentationId) return;
    const preparedOutlines = limitOutlines(latestOutlines);

    setLoadingState({
      message: "正在根据大纲准备主题排版…",
      isLoading: true,
      showProgress: true,
      duration: 20,
    });

    try {
      await PresentationGenerationApi.updateOutlines(
        presentationId,
        preparedOutlines
      );
      dispatch(clearPresentationData());
      clearTheme();
      router.replace(
        `/presentation?id=${presentationId}&stream=true&type=smart`
      );
    } catch (error: any) {
      console.error("Error preparing Smart presentation.", error);
      notify.error(
        "生成错误",
        error.message || "根据大纲准备主题排版时发生错误。"
      );
    } finally {
      setLoadingState(DEFAULT_LOADING_STATE);
    }
  }, [dispatch, presentationId, router, validateInputs]);

  return { loadingState, handleSubmit, handleSmartSubmit };
};
