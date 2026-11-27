import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built into the Python package so the app (and PyInstaller bundle) serves it at /app/.
export default defineConfig({
  plugins: [react()],
  base: "/app/",
  build: { outDir: "../notetaker/static/app", emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:8010" } },
});
