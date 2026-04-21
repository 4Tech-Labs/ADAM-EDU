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
    // Use forked processes instead of worker_threads so each worker gets an
    // isolated V8 heap and event loop. Without this, jsdom timer pressure from
    // heavy test files (AuthoringForm, TeacherCoursePage) causes timeouts in the
    // full-suite run. maxForks caps parallelism; on CI (2 vCPUs) Vitest clamps
    // automatically to min(maxForks, cpuCount).
    pool: "forks",
    // @ts-expect-error -- vitest 4.1.2 InlineConfig type omits poolOptions; valid at runtime
    poolOptions: {
      forks: { maxForks: 3 },
    },
    // Slow async-UI tests (MSW + jsdom) can legitimately take >5s under load.
    testTimeout: 10_000,
  },
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        // selfHandleResponse desactiva el buffering interno de http-proxy y hace pipe
        // directo de la respuesta para mantener el comportamiento de streaming/chunks
        // cuando el backend emite respuestas largas o progresivas.
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
