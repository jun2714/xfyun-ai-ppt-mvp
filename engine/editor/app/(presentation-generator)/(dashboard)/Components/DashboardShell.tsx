"use client";

import { useState, type ReactNode } from "react";
import DashboardSidebar from "./DashboardSidebar";
import DashboardEmbedTabs from "./DashboardEmbedTabs";
import { isTeachnovaEmbed } from "@/utils/teachnovaEmbed";

export default function DashboardShell({ children }: { children: ReactNode }) {
  const [embedded] = useState(() =>
    typeof window !== "undefined" ? isTeachnovaEmbed() : false
  );

  if (embedded) {
    return (
      <div className="flex min-h-screen w-full flex-col bg-white">
        <DashboardEmbedTabs />
        <div className="min-h-0 min-w-0 flex-1">{children}</div>
      </div>
    );
  }

  return (
    <div className="flex bg-white pr-4">
      <DashboardSidebar />
      <div className="w-full">{children}</div>
    </div>
  );
}
