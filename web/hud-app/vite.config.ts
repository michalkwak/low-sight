/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The backend serves the built app at /hud/ (from web/hud-app/dist).
// `npm run dev` serves it with hot reload at http://localhost:5173/hud/ and proxies the
// backend's /ws and /api (uvicorn on :8000), so the same-origin WebSocket URL still works.
export default defineConfig({
  base: "/hud/",
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true, target: "es2022" },
  server: {
    proxy: {
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
      "/api": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    // The toolkit ships ESM that imports its own CSS: let Vitest transform it instead of Node.
    server: { deps: { inline: [/@wearables-ui-toolkit/] } },
  },
});
