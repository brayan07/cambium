/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  test: {
    environment: "happy-dom",
    globals: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api/terminal": {
        target: "http://127.0.0.1:8352",
        ws: true,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
      "/api": {
        target: "http://127.0.0.1:8352",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
