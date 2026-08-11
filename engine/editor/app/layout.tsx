import type { Metadata } from "next";
import localFont from "next/font/local";
import { Manrope, Noto_Sans_SC, Syne, Unbounded } from "next/font/google";
import "./globals.css";
import "katex/dist/katex.min.css";
import { Providers } from "./providers";
import MixpanelInitializer from "./MixpanelInitializer";
import { Toaster } from "@/components/ui/sonner";
import TailwindCdnRuntime from "@/components/runtime/TailwindCdnRuntime";
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

const syne = Syne({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
  variable: "--font-syne",
});

const manrope = Manrope({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
  variable: "--font-manrope",
});

const unbounded = Unbounded({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
  variable: "--font-unbounded",
});

const notoSansSC = Noto_Sans_SC({
  subsets: ["latin"],
  variable: "--font-noto-sans-sc",
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
        className={`${inter.variable} ${syne.variable} ${manrope.variable} ${unbounded.variable} ${notoSansSC.variable} antialiased`}
      >
        <Providers>
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
