import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    strictPort: true,
    proxy: {
      // Keep SSE outline/slide streams unbuffered for progressive UI updates.
      "/api/v1/ppt": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        timeout: 0,
        proxyTimeout: 0,
      },
      "/app_data": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/static": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
