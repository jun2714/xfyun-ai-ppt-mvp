"use client";

import Wrapper from "@/components/Wrapper";
import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { trackEvent, MixpanelEvent } from "@/utils/mixpanel";
import { ArrowLeft } from "lucide-react";

const PATHS_WITH_HEADER_BACK = [
  "/upload",
  "/outline",
  "/documents-preview",
  "/template-preview",
] as const;

function pathMatches(pathname: string | null, base: string) {
  return pathname === base || pathname?.startsWith(`${base}/`) === true;
}

const Header = () => {
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
    <div className="w-full   sticky top-0 z-50 py-7 "
      style={{
        background: "linear-gradient(180deg, #FFF 0%, rgba(255, 255, 255, 0.00) 110.67%)",

      }}
    >
      <Wrapper className="px-5 sm:px-10 lg:px-20">
        <div className="flex items-center justify-between py-1">
          <div className="flex items-center gap-3">
            <Link className="flex items-center gap-3" href="/dashboard" onClick={() => trackEvent(MixpanelEvent.Navigation, { from: pathname, to: "/dashboard" })}>
              <img
                src="/teachnova-logo.png"
                alt="Teachnova"
                className="h-10 w-auto max-w-[190px] object-contain"
              />
              <span className="hidden text-sm font-semibold text-[#101323] sm:inline">幼教PPT</span>
            </Link>
          </div>
          <div className="flex items-center">
            {showHeaderBack ? (
              <Link
                href={backHref}
                className="text-[#333333] text-xs font-syne font-semibold flex items-center gap-2"
                onClick={() =>
                  trackEvent(MixpanelEvent.Navigation, { from: pathname, to: backHref })
                }
              >
                <ArrowLeft className="w-4 h-4 shrink-0 text-[#333333]" aria-hidden />
                <span>{backLabel}</span>
              </Link>
            ) : null}
          </div>
        </div>
      </Wrapper>
    </div>
  );
};

export default Header;
