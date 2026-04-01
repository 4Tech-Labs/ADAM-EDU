import type { IncomingMessage, ServerResponse } from "node:http";
import path from "node:path";
import { defineConfig } from "vite";
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
