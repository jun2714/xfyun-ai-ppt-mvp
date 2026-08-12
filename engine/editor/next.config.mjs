import path from "node:path";
import { fileURLToPath } from "node:url";

const nextjsRoot = path.dirname(fileURLToPath(import.meta.url));

const nextConfig = {
  reactStrictMode: false,
  distDir: ".next-build",
  output: "standalone",
  // 产品通过 iframe 嵌入编辑器，开发提示浮层不应暴露给最终用户。
  devIndicators: false,
  // Custom template PPTX + font uploads often exceed the default 10MB proxy body
  // limit when requests still go through the Next.js rewrite to FastAPI.
  experimental: {
    middlewareClientMaxBodySize: "64mb",
  },
  turbopack: {
    root: nextjsRoot,
  },
  ...(process.env.NODE_ENV !== "production"
    ? {
        allowedDevOrigins: [
          "127.0.0.1",
          "localhost",
        ],
      }
    : {}),

  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "pub-7c765f3726084c52bcd5d180d51f1255.r2.dev",
      },
      {
        protocol: "https",
        hostname: "pptgen-public.ap-south-1.amazonaws.com",
      },
      {
        protocol: "https",
        hostname: "pptgen-public.s3.ap-south-1.amazonaws.com",
      },
      {
        protocol: "https",
        hostname: "img.icons8.com",
      },
      {
        protocol: "https",
        hostname: "present-for-me.s3.amazonaws.com",
      },
      {
        protocol: "https",
        hostname: "yefhrkuqbjcblofdcpnr.supabase.co",
      },
      {
        protocol: "https",
        hostname: "images.unsplash.com",
      },
      {
        protocol: "https",
        hostname: "picsum.photos",
      },
      {
        protocol: "https",
        hostname: "unsplash.com",
      },
    ],
  },
  
};

export default nextConfig;
