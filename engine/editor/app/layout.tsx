import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import "katex/dist/katex.min.css";
import { Providers } from "./providers";
import MixpanelInitializer from "./MixpanelInitializer";
import { Toaster } from "@/components/ui/sonner";
import TailwindCdnRuntime from "@/components/runtime/TailwindCdnRuntime";
import { ChunkLoadRecovery } from "@/components/runtime/ChunkLoadRecovery";

// Avoid next/font/google here: fonts.gstatic.com is often unreachable in CN,
// which crashes the editor during Turbopack compile.
const inter = localFont({
  src: [
    {
      path: "./fonts/Inter.ttf",
      weight: "400",
      style: "normal",
    },
  ],
  variable: "--font-inter",
});

const systemUi = localFont({
  src: [
    {
      path: "./fonts/Inter.ttf",
      weight: "400",
      style: "normal",
    },
  ],
  variable: "--font-syne",
  fallback: [
    "Segoe UI",
    "PingFang SC",
    "Microsoft YaHei",
    "Noto Sans SC",
    "sans-serif",
  ],
});

const manrope = localFont({
  src: [
    {
      path: "./fonts/Inter.ttf",
      weight: "400",
      style: "normal",
    },
  ],
  variable: "--font-manrope",
  fallback: [
    "Segoe UI",
    "PingFang SC",
    "Microsoft YaHei",
    "Noto Sans SC",
    "sans-serif",
  ],
});

const unbounded = localFont({
  src: [
    {
      path: "./fonts/Inter.ttf",
      weight: "400",
      style: "normal",
    },
  ],
  variable: "--font-unbounded",
  fallback: [
    "Segoe UI",
    "PingFang SC",
    "Microsoft YaHei",
    "Noto Sans SC",
    "sans-serif",
  ],
});

const notoSansSC = localFont({
  src: [
    {
      path: "./fonts/Inter.ttf",
      weight: "400",
      style: "normal",
    },
  ],
  variable: "--font-noto-sans-sc",
  fallback: ["Microsoft YaHei", "PingFang SC", "Noto Sans SC", "sans-serif"],
});

export const metadata: Metadata = {
  title: "Teachnova 幼教PPT",
  description: "面向幼儿园教学、家长会与教研场景的 AI 演示文稿生成与编辑工具。",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {

  return (
    <html lang="zh-CN">
      <head>
        <link rel="preload" href="/Presenton_Splash.png" as="image" />
      </head>
      <body
        className={`${inter.variable} ${systemUi.variable} ${manrope.variable} ${unbounded.variable} ${notoSansSC.variable} antialiased`}
      >
        <Providers>
          <ChunkLoadRecovery />
          <MixpanelInitializer>

            {children}

          </MixpanelInitializer>
        </Providers>
        <TailwindCdnRuntime />
        <Toaster
          position="top-right"
          offset={{ top: 84, right: 20 }}
          mobileOffset={{ top: 76, right: 12, left: 12 }}
          expand
          gap={10}
          visibleToasts={3}
        />
      </body>
    </html>
  );
}
