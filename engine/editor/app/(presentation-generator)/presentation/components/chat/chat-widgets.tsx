import { useState } from "react";
import { Check, ChevronRight, Loader2 } from "lucide-react";
import Image from "next/image";
import { cn } from "@/lib/utils";
import {
  Command,
  CommandGroup,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { TemplateV2HtmlSlidePreview } from "../../../components/TemplateV2HtmlSlidePreview";
import {
  quickPromptGroups,
  teachingContextGroups,
  type TeachingContextKey,
  type TeachingContextState,
} from "./chat-prompts";
import type { AssistantActivity, ChatEditPreview } from "./chat-types";

const AssistantSparkleIcon = ({ size = 14 }: { size?: number }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 14 14"
    fill="none"
    aria-hidden="true"
  >
    <path
      d="M6.9 1.1c.22 3.03 1.37 4.17 4.4 4.4-3.03.22-4.18 1.37-4.4 4.4-.22-3.03-1.37-4.18-4.4-4.4 3.03-.23 4.18-1.37 4.4-4.4Z"
      fill="#7A5AF8"
    />
    <path
      d="M11.2 9.4c.1 1.42.64 1.96 2.06 2.06-1.42.1-1.96.64-2.06 2.06-.1-1.42-.64-1.96-2.06-2.06 1.42-.1 1.96-.64 2.06-2.06Z"
      fill="#6172F3"
    />
  </svg>
);

export const AssistantMarker = () => (
  <div className="mb-2 flex items-center gap-1.5 text-[#8A8F98]">
    <AssistantSparkleIcon size={14} />
    <span className="text-[11px] font-medium leading-4">助手</span>
  </div>
);

export const ActivityStatusIcon = ({
  activity,
}: {
  activity: AssistantActivity;
}) => {
  if (activity.state === "running") {
    return (
      <span
        className="activity-flow-dots relative mt-1 h-[9px] w-[22px] shrink-0"
        aria-label="处理中"
      >
        <span className="absolute left-0 top-[1.5px] h-[6px] w-[6px] rounded-full bg-[#C3C3CB]" />
        <span className="absolute left-[8px] top-[1.5px] h-[6px] w-[6px] rounded-full bg-[#C3C3CB]" />
        <span className="absolute left-[16px] top-[1.5px] h-[6px] w-[6px] rounded-full bg-[#C3C3CB]" />
      </span>
    );
  }

  if (activity.state === "error") {
    return <span className="h-2 w-2 shrink-0 rounded-full bg-[#F04438]" />;
  }

  return <span className="h-2 w-2 shrink-0 rounded-full bg-[#E6E6E6]" />;
};

export const QuickPromptsPanel = ({
  onPromptSelect,
  groups = quickPromptGroups,
}: {
  onPromptSelect: (prompt: string) => void;
  groups?: typeof quickPromptGroups;
}) => (
  <div className="flex flex-col gap-6 font-syne">
    <AssistantSparkleIcon size={24} />
    <div className="flex flex-col gap-5">
      {groups.map((group) => (
        <div key={group.label} className="flex flex-col gap-2">
          <p className="text-sm font-normal tracking-[0.28px] text-[#333333]">
            {group.label}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {group.prompts.map((prompt) => (
              <button
                key={prompt}
                type="button"
                onClick={() => onPromptSelect(prompt)}
                className="rounded-full border border-black/[0.04] bg-black/[0.02] px-4 py-1.5 font-manrope text-xs font-normal tracking-[0.24px] text-[#333333] outline-none transition-colors hover:border-[#D9D6FE] hover:bg-[#FAFAFF] hover:text-[#7A5AF8] focus:border-[#7A5AF8] focus:outline-none focus:ring-0 focus-visible:border-[#7A5AF8] focus-visible:text-[#7A5AF8] focus-visible:outline-none focus-visible:ring-0 active:border-[#7A5AF8] active:text-[#7A5AF8]"
              >
                {prompt}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  </div>
);

export const TeachingContextBar = ({
  value,
  onChange,
  disabled = false,
  className,
}: {
  value: TeachingContextState;
  onChange: (next: TeachingContextState) => void;
  disabled?: boolean;
  className?: string;
}) => {
  const [openKey, setOpenKey] = useState<TeachingContextKey | null>(null);

  const selectOption = (key: TeachingContextKey, option: string | undefined) => {
    onChange({
      ...value,
      [key]: option,
    });
    setOpenKey(null);
  };

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-2",
        className,
      )}
      aria-label="教学信息"
    >
      {teachingContextGroups.map((group) => {
        const selected = value[group.key];
        const open = openKey === group.key;
        return (
          <Popover
            key={group.key}
            open={open}
            onOpenChange={(nextOpen) => {
              if (disabled) return;
              setOpenKey(nextOpen ? group.key : null);
            }}
          >
            <PopoverTrigger asChild>
              <button
                type="button"
                role="combobox"
                disabled={disabled}
                aria-expanded={open}
                aria-controls={`teaching-context-${group.key}`}
                className={cn(
                  "flex h-[28px] max-w-[140px] items-center gap-1 overflow-hidden rounded-full border bg-white px-2.5 font-syne font-semibold text-[#191919] shadow-none transition-colors focus-visible:ring-2 focus-visible:ring-[#5146E5]/25 disabled:cursor-not-allowed disabled:opacity-40",
                  selected
                    ? "border-[#D9D6FE] text-[#6941C6]"
                    : "border-[#EDEEEF]",
                )}
              >
                <span className="min-w-0 truncate text-[11px] font-semibold tracking-[-0.12px]">
                  {selected || group.shortLabel || group.label}
                </span>
                <ChevronRight
                  aria-hidden="true"
                  strokeWidth={1.75}
                  className="h-3 w-3 shrink-0 rotate-90"
                />
              </button>
            </PopoverTrigger>
            <PopoverContent
              id={`teaching-context-${group.key}`}
              className="w-[180px] p-0 font-syne"
              align="end"
            >
              <Command>
                <CommandList>
                  <CommandGroup>
                    <CommandItem
                      value="__clear__"
                      onSelect={() => selectOption(group.key, undefined)}
                      className="font-syne text-sm text-[#667085]"
                    >
                      <Check
                        className={cn(
                          "mr-2 h-4 w-4",
                          !selected ? "opacity-100" : "opacity-0",
                        )}
                      />
                      不限
                    </CommandItem>
                    {group.options.map((option) => (
                      <CommandItem
                        key={option}
                        value={option}
                        onSelect={() => selectOption(group.key, option)}
                        className="font-syne text-sm"
                      >
                        <Check
                          className={cn(
                            "mr-2 h-4 w-4",
                            selected === option ? "opacity-100" : "opacity-0",
                          )}
                        />
                        {option}
                      </CommandItem>
                    ))}
                  </CommandGroup>
                </CommandList>
              </Command>
            </PopoverContent>
          </Popover>
        );
      })}
    </div>
  );
};

export const EditComparisonPreview = ({
  preview,
  fonts,
  selectedVersion,
  isApplying,
  onSelectVersion,
}: {
  preview: ChatEditPreview;
  fonts?: unknown;
  selectedVersion: "original" | "modified";
  isApplying: boolean;
  onSelectVersion: (version: "original" | "modified") => void;
}) => {
  if (!preview.modifiedSlides?.length) return null;

  const cards = [
    {
      label: "原版",
      slides: preview.originalSlides,
      version: "original" as const,
    },
    {
      label: "修改后",
      slides: preview.modifiedSlides,
      version: "modified" as const,
    },
  ];

  return (
    <div className="flex w-full flex-col gap-2 font-manrope">
      <div className="flex items-center gap-1 text-[13px] leading-[18px]">
        <Image
          src="/frame.svg"
          alt=""
          width={14}
          height={14}
          className="h-[14px] w-[14px] shrink-0"
        />
        <span className="font-semibold text-[#191919]">选择修改结果</span>
        <span className="ml-auto text-[11px] font-medium leading-[normal] text-[#7A5AF8]">
          {preview.changeCount} 处修改
        </span>
      </div>
      <div className="grid grid-cols-2 gap-[5px]">
        {cards.map((card) => (
          <button
            key={card.label}
            type="button"
            onClick={() => onSelectVersion(card.version)}
            disabled={isApplying}
            className={cn(
              "min-w-0 overflow-hidden rounded-[6px] border bg-[#F9FAFB] px-[6px] py-[10px] text-left transition-[border-color,background-color,box-shadow,opacity] hover:border-[#B7ACFC] disabled:cursor-wait disabled:opacity-70",
              selectedVersion === card.version
                ? "border-[#7A5AF8] bg-[#FAFAFF]"
                : "border-[#EDEEEF]",
            )}
            aria-pressed={selectedVersion === card.version}
            aria-label={`恢复为「${card.label}」`}
          >
            <span className="mb-[7px] flex items-center justify-center gap-1 truncate text-center text-[13px] font-medium leading-[normal] text-[#191919]">
              {isApplying && selectedVersion === card.version && (
                <Loader2 className="h-3 w-3 animate-spin text-[#7A5AF8]" />
              )}
              <span>{card.label}</span>
            </span>
            <span className="flex flex-col gap-[3px]">
              {card.slides.slice(0, 2).map((slide, index) => (
                <TemplateV2HtmlSlidePreview
                  key={`${card.label}-${index}`}
                  slide={slide}
                  fonts={fonts}
                  className="overflow-hidden rounded-[2px] border border-[#EDEEEF] bg-white"
                />
              ))}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
};
