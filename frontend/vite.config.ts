import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies /api to the local FastAPI backend so the browser talks to
// one origin (no CORS headaches in development). In production the frontend is
// static and the API lives under /api on the same domain.
const API_TARGET = process.env.VITE_API_TARGET ?? "http://127.0.0.1:8010";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5310,
    strictPort: true,
    proxy: {
      "/api": {
        target: API_TARGET,
        changeOrigin: true,
        // SSE needs no buffering
        configure: (proxy) => {
          proxy.on("proxyRes", (proxyRes) => {
            if (proxyRes.headers["content-type"]?.includes("text/event-stream")) {
              proxyRes.headers["cache-control"] = "no-cache, no-transform";
            }
          });
        },
      },
    },
  },
});
