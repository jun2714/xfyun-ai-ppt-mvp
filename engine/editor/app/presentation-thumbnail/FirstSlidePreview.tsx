"use client";

import { useEffect, useState } from "react";

import SlideScale from "@/app/(presentation-generator)/components/PresentationRender";
import {
  shouldRenderTemplateV2HtmlPreview,
  TemplateV2HtmlSlidePreview,
} from "@/app/(presentation-generator)/components/TemplateV2HtmlSlidePreview";
import { DashboardApi } from "@/app/(presentation-generator)/services/api/dashboard";
import { normalizeBackendAssetUrls } from "@/utils/api";

type PresentationPreview = {
  version?: string;
  fonts?: unknown;
  layout?: unknown;
  slides?: unknown[];
};

export function FirstSlidePreview({ presentationId }: { presentationId: string }) {
  const [presentation, setPresentation] = useState<PresentationPreview | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!presentationId) {
      setFailed(true);
      return;
    }

    let disposed = false;
    void DashboardApi.getPresentation(presentationId, { cache: "no-store" })
      .then((value) => {
        if (!disposed) setPresentation(normalizeBackendAssetUrls(value));
      })
      .catch(() => {
        if (!disposed) setFailed(true);
      });

    return () => {
      disposed = true;
    };
  }, [presentationId]);

  const firstSlide = presentation?.slides?.[0];
  if (failed || (presentation && !firstSlide)) {
    return <main className="grid h-screen w-screen place-items-center bg-[#f4f1ff] text-xs text-[#777282]">暂无预览</main>;
  }
  if (!presentation || !firstSlide) {
    return <main className="h-screen w-screen animate-pulse bg-[#f1eff8]" aria-label="正在加载第一页" />;
  }

  return <main className="h-screen w-screen overflow-hidden bg-white">
    {shouldRenderTemplateV2HtmlPreview(firstSlide, presentation.version) ? (
      <TemplateV2HtmlSlidePreview
        slide={firstSlide}
        fonts={presentation.fonts}
        className="h-full"
      />
    ) : (
      <SlideScale
        slide={firstSlide}
        fonts={presentation.fonts}
        isClickable={false}
        isEditMode={false}
        presentationLayout={presentation.layout}
      />
    )}
  </main>;
}
