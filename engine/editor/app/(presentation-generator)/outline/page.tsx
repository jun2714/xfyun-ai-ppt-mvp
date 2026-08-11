import React from "react";
import { Metadata } from "next";
import OutlinePage from "./components/OutlinePage";

export const metadata: Metadata = {
  title: "确认大纲 | Teachnova 幼教PPT",
  description: "编辑页面大纲并选择演示模板。",
  alternates: {
    canonical: "https://presenton.ai/create"
  },
  keywords: [
    "presentation generator",
    "AI presentations",
    "data visualization",
    "automatic presentation maker",
    "professional slides",
    "data-driven presentations",
    "document to presentation",
    "presentation automation",
    "smart presentation tool",
    "business presentations"
  ]
};

const page = () => {
  return (
    <div className="relative min-h-screen" translate="no">
      <OutlinePage />
    </div>
  );
};

export default page;
