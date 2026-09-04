import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiTarget = process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    strictPort: true,
    proxy: {
      // Keep SSE outline/slide streams unbuffered for progressive UI updates.
      "/api/v1/ppt": {
        target: apiTarget,
        changeOrigin: true,
        timeout: 0,
        proxyTimeout: 0,
      },
      "/app_data": {
        target: apiTarget,
        changeOrigin: true,
      },
      "/static": {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
});
