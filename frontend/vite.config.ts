import type { IncomingMessage, ServerResponse } from "node:http";
import path from "node:path";
// defineConfig from vitest/config re-exports vite's defineConfig and adds the
// typed `test` field so TypeScript recognises test configuration.
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react-swc";
import tailwindcss from "@tailwindcss/vite";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "/app/",
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("react-plotly.js/factory")) {
            return "plotly-react";
          }
          if (id.includes("plotly.js/lib/")) {
            return "plotly-traces";
          }
          if (
            id.includes("plotly.js/src/") ||
            id.includes("gl-") ||
            id.includes("regl") ||
            id.includes("mapbox")
          ) {
            return "plotly-core";
          }
        },
      },
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        // selfHandleResponse desactiva el buffering interno de http-proxy y hace pipe
        // directo de la respuesta — necesario para que los eventos SSE lleguen en tiempo real
        // (sin esto, el proxy acumula toda la respuesta antes de enviarla al browser).
        selfHandleResponse: true,
        configure: (proxy) => {
          proxy.on("proxyRes", (proxyRes: IncomingMessage, _req: IncomingMessage, res: ServerResponse) => {
            res.writeHead(proxyRes.statusCode ?? 502, proxyRes.headers);
            proxyRes.pipe(res, { end: true });
          });
          proxy.on("error", (_err: Error, _req: IncomingMessage, res: ServerResponse) => {
            if (!res.headersSent) {
              res.writeHead(502, { "Content-Type": "text/plain" });
            }
            res.end("Bad Gateway — backend no disponible");
          });
        },
      },
    },
  },
});
