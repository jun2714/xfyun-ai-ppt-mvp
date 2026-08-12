"use client";

import React, { memo } from "react";
import CreateCustomTemplate from "../../(dashboard)/templates/components/CreateCustomTemplate";
import { useTemplateSummaries } from "../../hooks/useTemplateSummaries";
import {
  TemplateListCard,
  TemplateListLoadingState,
  TemplateListEmptyState,
  TemplateListSection,
} from "../../components/TemplateListUi";
import { MixpanelEvent, trackEvent } from "@/utils/mixpanel";
import { writePreferredTemplateId } from "../../utils/preferredTemplate";

interface TemplateSelectionProps {
  presentationId: string | null;
  selectedTemplateId: string | null;
  onSelectTemplate: (template: {
    id: string;
    name: string;
    source: "default" | "custom";
    position: number;
  }) => void;
  onCreateTemplate?: () => void;
}

const TemplateSelection: React.FC<TemplateSelectionProps> = memo(
  function TemplateSelection({
    presentationId,
    selectedTemplateId,
    onSelectTemplate,
    onCreateTemplate,
  }) {
    const { defaultTemplates, customTemplates, loading } =
      useTemplateSummaries();

    if (loading) {
      return <TemplateListLoadingState />;
    }

    const renderTemplateCard = (
      template: (typeof defaultTemplates)[number],
      index: number,
      source: "default" | "custom"
    ) => (
      <TemplateListCard
        key={template.id}
        template={template}
        isSelected={selectedTemplateId === template.id}
        showArrow
        selectionPage
        onClick={() => {
          trackEvent(MixpanelEvent.TemplateV2_Template_Selected, {
            presentation_id: presentationId,
            template_id: template.id,
            template_source: source,
          });
          writePreferredTemplateId(template.id);
          onSelectTemplate({
            id: template.id,
            name: template.name,
            source,
            position: index,
          });
        }}
      />
    );

    return (
      <div className="mb-8 space-y-[30px]">
        <TemplateListSection label="内置模板" selectionPage>
          <p className="mb-3 text-[12px] leading-4 text-[#667085]">
            由平台提供，所有用户可见可用
          </p>
          {defaultTemplates.length === 0 ? (
            <TemplateListEmptyState message="暂无可用的内置模板。" />
          ) : (
            <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {defaultTemplates.map((template, index) =>
                renderTemplateCard(template, index, "default")
              )}
            </div>
          )}
        </TemplateListSection>

        <TemplateListSection label="我的模板" selectionPage>
          <p className="mb-3 text-[12px] leading-4 text-[#667085]">
            老师自行上传，仅当前账号可见
          </p>
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            <CreateCustomTemplate
              selectionPage
              onClick={onCreateTemplate}
            />
            {customTemplates.map((template, index) =>
              renderTemplateCard(template, index, "custom")
            )}
          </div>
          {customTemplates.length === 0 ? (
            <p className="mt-3 text-[12px] text-[#98A2B3]">
              还没有个人模板。可上传后在此使用，或先选择上方内置模板。
            </p>
          ) : null}
        </TemplateListSection>
      </div>
    );
  }
);

export default TemplateSelection;
