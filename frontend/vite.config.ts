/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite config for the Market Analysis Agent frontend.
// - Dev server listens on :5173 (Vite default).
// - Build output goes to dist/ for Vercel.
// - Vitest uses happy-dom (DOM-ish, much faster than jsdom).
export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: "happy-dom",
    setupFiles: ["./src/test-setup.ts"],
  },
});
