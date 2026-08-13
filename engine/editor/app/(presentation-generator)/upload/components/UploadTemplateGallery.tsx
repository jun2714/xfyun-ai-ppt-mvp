"use client";

import React from "react";
import Link from "next/link";
import { useTemplateSummaries } from "../../hooks/useTemplateSummaries";
import {
  TemplateListCard,
  TemplateListEmptyState,
  TemplateListLoadingState,
  TemplateListSection,
} from "../../components/TemplateListUi";

function templatePreviewHref(templateId: string) {
  return `/template-preview?templateV2Id=${encodeURIComponent(templateId)}`;
}

/**
 * Showcase gallery for the template-create flow.
 * Selection happens later on the Web outline page after the outline is ready.
 */
export default function UploadTemplateGallery() {
  const { defaultTemplates, customTemplates, loading } = useTemplateSummaries();

  if (loading) {
    return <TemplateListLoadingState message="正在加载模板…" />;
  }

  return (
    <div className="mx-auto max-w-[1200px] space-y-10 px-4 pb-4 sm:px-6">
      <TemplateListSection label="我的模板" selectionPage>
        <p className="mb-3 text-[12px] leading-4 text-[#667085]">
          老师自行上传，仅当前账号可见
        </p>
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          <Link
            href="/custom-template"
            className="flex min-h-[220px] flex-col items-center justify-center gap-2 rounded-[12px] border border-dashed border-[#D0D5DD] bg-[#FCFCFD] px-4 text-center transition-colors hover:border-[#7A5AF8] hover:bg-[#F8F6FF]"
          >
            <span className="text-[28px] leading-none text-[#7A5AF8]">+</span>
            <span className="text-sm font-semibold text-[#191919]">上传新模板</span>
            <span className="text-[11px] text-[#808080]">
              上传 PPTX，制作后仅自己可见
            </span>
          </Link>
          {customTemplates.map((template) => (
            <TemplateListCard
              key={template.id}
              template={template}
              selectionPage
              showArrow
              onClick={() => {
                window.open(templatePreviewHref(template.id), "_blank", "noopener,noreferrer");
              }}
            />
          ))}
        </div>
        {customTemplates.length === 0 ? (
          <p className="mt-3 text-[12px] text-[#98A2B3]">
            还没有个人模板。可点「上传新模板」添加，或先浏览下方内置模板。
          </p>
        ) : null}
      </TemplateListSection>

      <TemplateListSection label="内置模板" selectionPage>
        <p className="mb-3 text-[12px] leading-4 text-[#667085]">
          由平台提供，所有用户可见可用 · 仅供浏览，排版时在大纲页选择
        </p>
        {defaultTemplates.length === 0 ? (
          <TemplateListEmptyState message="暂无内置模板。" />
        ) : (
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {defaultTemplates.map((template) => (
              <TemplateListCard
                key={template.id}
                template={template}
                selectionPage
                showArrow
                onClick={() => {
                  window.open(templatePreviewHref(template.id), "_blank", "noopener,noreferrer");
                }}
              />
            ))}
          </div>
        )}
      </TemplateListSection>
    </div>
  );
}
