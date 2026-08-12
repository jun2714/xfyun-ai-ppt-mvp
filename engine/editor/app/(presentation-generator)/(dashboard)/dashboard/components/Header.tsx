"use client";

import Wrapper from "@/components/Wrapper";
import React, { type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { trackEvent, MixpanelEvent } from "@/utils/mixpanel";
import { ArrowLeft } from "lucide-react";
import { requestTeachnovaHome } from "@/utils/teachnovaEmbed";

const PATHS_WITH_HEADER_BACK = [
  "/upload",
  "/outline",
  "/documents-preview",
  "/template-preview",
] as const;

function pathMatches(pathname: string | null, base: string) {
  return pathname === base || pathname?.startsWith(`${base}/`) === true;
}

const Header = ({ rightSlot }: { rightSlot?: ReactNode }) => {
  const pathname = usePathname();
  const showHeaderBack = PATHS_WITH_HEADER_BACK.some((p) => pathMatches(pathname, p));

  const backToUpload =
    pathMatches(pathname, "/outline") || pathMatches(pathname, "/documents-preview");
  const backToTemplates = pathMatches(pathname, "/template-preview");

  const backHref = backToUpload ? "/upload" : backToTemplates ? "/templates" : "/dashboard";
  const backLabel = backToUpload
    ? "返回新建演示"
    : backToTemplates
      ? "返回模板"
      : "返回项目";

  return (
    <div
      className="sticky top-0 z-50 w-full py-7"
      style={{
        background: "linear-gradient(180deg, #FFF 0%, rgba(255, 255, 255, 0.00) 110.67%)",
      }}
    >
      <Wrapper className="px-5 sm:px-10 lg:px-20">
        <div className="flex items-start justify-between gap-4 py-1">
          <div className="flex flex-col items-start gap-2">
            <Link
              className="flex items-center gap-3"
              href="/dashboard"
              onClick={(event) => {
                if (requestTeachnovaHome()) event.preventDefault();
                trackEvent(MixpanelEvent.Navigation, { from: pathname, to: "/dashboard" });
              }}
            >
              <img src="/teachnova-mark.png" alt="" className="h-10 w-10 object-contain" />
              <span className="hidden items-baseline gap-1.5 sm:flex">
                <span className="text-lg font-bold tracking-[-0.03em] text-[#17152d]">Teachnova</span>
                <span className="text-sm font-semibold text-[#4f4b5d]">幼教PPT</span>
              </span>
            </Link>
            {showHeaderBack ? (
              <Link
                href={backHref}
                className="ml-1 flex items-center gap-1.5 font-syne text-xs font-semibold text-[#667085] transition-colors hover:text-[#333333] sm:ml-0.5"
                onClick={() =>
                  trackEvent(MixpanelEvent.Navigation, { from: pathname, to: backHref })
                }
              >
                <ArrowLeft className="h-3.5 w-3.5 shrink-0" aria-hidden />
                <span>{backLabel}</span>
              </Link>
            ) : null}
          </div>
          <div className="flex shrink-0 items-center pt-1">{rightSlot}</div>
        </div>
      </Wrapper>
    </div>
  );
};

export default Header;
