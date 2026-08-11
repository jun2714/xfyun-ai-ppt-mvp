import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    strictPort: true,
    proxy: {
      "/api/v1/ppt": "http://127.0.0.1:8000",
      "/app_data": "http://127.0.0.1:8000",
      "/static": "http://127.0.0.1:8000"
    }
  }
});
