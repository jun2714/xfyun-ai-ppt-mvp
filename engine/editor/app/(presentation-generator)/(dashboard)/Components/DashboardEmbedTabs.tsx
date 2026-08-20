"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/dashboard", label: "我的项目", match: (path: string) => path === "/dashboard" || path.startsWith("/dashboard/") },
  { href: "/templates", label: "模板中心", match: (path: string) => path === "/templates" || path.startsWith("/templates/") },
] as const;

/**
 * Top tabs used when Presenton is embedded in TeachNova (replaces the narrow left rail).
 */
export default function DashboardEmbedTabs() {
  const pathname = usePathname() || "";

  return (
    <nav
      className="sticky top-0 z-40 w-full border-b border-[#EDEEEF] bg-white px-6"
      aria-label="PPT 分区"
    >
      <ul className="flex items-stretch gap-8">
        {TABS.map((tab) => {
          const active = tab.match(pathname);
          return (
            <li key={tab.href}>
              <Link
                href={tab.href}
                prefetch={false}
                className={[
                  "relative inline-flex h-12 items-center font-syne text-[15px] transition-colors",
                  active
                    ? "font-semibold text-[#191919]"
                    : "font-medium text-[#667085] hover:text-[#191919]",
                ].join(" ")}
                aria-current={active ? "page" : undefined}
              >
                {tab.label}
                {active ? (
                  <span
                    className="absolute inset-x-0 bottom-0 h-[2px] rounded-full bg-[#5146E5]"
                    aria-hidden
                  />
                ) : null}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
