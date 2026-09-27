import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// `npm run dev` proxies the API to a locally running `python -m crm.server`.
const backend = process.env.CRM_BACKEND ?? "http://localhost:8080";

export default defineConfig({
  plugins: [react()],
  base: "./",
  server: {
    proxy: {
      "/api": backend,
      "/media": backend,
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 700,
  },
  test: {
    environment: "node",
  },
});
