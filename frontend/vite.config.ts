import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  build: {
    // Served by `eos run` straight from the Python package, so `uv run eos run`
    // works without Node.js; rebuild after changing the UI.
    outDir: "../src/eyes_on_screen/web/static",
    emptyOutDir: true,
  },
  server: {
    // `npm run dev` with hot reload, talking to a running `eos run`.
    proxy: { "/ws": { target: "ws://127.0.0.1:8765", ws: true } },
  },
  test: {
    environment: "jsdom",
  },
});
