import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { PencilIcon, X } from "lucide-react";
import type { KeyboardEvent, ReactNode } from "react";
import type { TeachingContextState } from "../../presentation/components/chat/chat-prompts";
import { TeachingContextBar } from "../../presentation/components/chat/chat-widgets";

interface PromptReference {
  id: string;
  label: string;
}

interface PromptInputProps {
  value: string;
  onChange: (value: string) => void;
  references?: PromptReference[];
  onRemoveReference?: (id: string) => void;
  variant?: "smart" | "standard";
  footer?: ReactNode;
  onSubmit?: () => void;
  hasAttachments?: boolean;
  teachingContext?: TeachingContextState;
  onTeachingContextChange?: (next: TeachingContextState) => void;
  teachingContextDisabled?: boolean;
  toolbarRight?: ReactNode;
}

export function PromptInput({
  value,
  onChange,
  references = [],
  onRemoveReference,
  variant: _variant = "standard",
  footer,
  onSubmit,
  hasAttachments = false,
  teachingContext,
  onTeachingContextChange,
  teachingContextDisabled = false,
  toolbarRight,
}: PromptInputProps) {
  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      onSubmit?.();
    }
  };

  const showTeachingContext =
    teachingContext !== undefined && onTeachingContextChange !== undefined;

  return (
    <div
      className={cn(
        "relative flex flex-col gap-2.5 rounded-lg border border-[#DBDBDB99] bg-white px-[10px] py-3 font-syne shadow-[0_4px_7px_rgba(0,0,0,0.04)]",
        hasAttachments ? "min-h-[215px]" : "min-h-[180px]",
      )}
    >
      {(showTeachingContext || toolbarRight) && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#F2F2F4] pb-2.5">
          {showTeachingContext ? (
            <TeachingContextBar
              value={teachingContext}
              onChange={onTeachingContextChange}
              disabled={teachingContextDisabled}
              className="gap-1.5"
            />
          ) : (
            <span />
          )}
          {toolbarRight ? (
            <div className="ml-auto flex flex-wrap items-center gap-2">{toolbarRight}</div>
          ) : null}
        </div>
      )}

      {references.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          {references.map((reference) => (
            <span
              key={reference.id}
              className="inline-flex h-[22px] max-w-full items-center gap-1.5 rounded-full bg-[#F4F4F4] px-[5px] py-1 font-manrope text-[10px] font-medium leading-none text-[#333333]"
            >
              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-[#7A5AF8]" />
              <span className="max-w-[220px] truncate">{reference.label}</span>
              {onRemoveReference && (
                <button
                  type="button"
                  onClick={() => onRemoveReference(reference.id)}
                  className="flex h-3.5 w-3.5 items-center justify-center rounded-full text-[#666666] hover:bg-[#E4E4E7] hover:text-[#191919]"
                  aria-label={`移除 ${reference.label}`}
                >
                  <X className="h-2.5 w-2.5" />
                </button>
              )}
            </span>
          ))}
        </div>
      )}

      <div className="flex min-h-0 flex-1 items-start gap-2">
        <span className="flex h-[21px] shrink-0 items-center">
          <PencilIcon className="h-3.5 w-3.5 text-[#191919]" strokeWidth={1.75} />
        </span>
        <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-1">
          <p className="text-sm font-normal leading-normal text-[#333333]">
            描述演示内容
          </p>
          <Textarea
            value={value}
            autoFocus
            rows={3}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="例如：为幼儿园中班制作一套认识海洋动物的互动课件"
            data-testid="prompt-input"
            className={cn(
              "custom_scrollbar max-h-[400px] min-h-[57px] resize-y overflow-y-auto rounded-none border-none bg-transparent p-0 text-base font-normal leading-normal text-[#191919] shadow-none placeholder:text-[#999999] focus-visible:ring-0 focus-visible:ring-offset-0",
              references.length === 0 && "min-h-[79px]",
            )}
          />
        </div>
      </div>

      {footer}
    </div>
  );
}
