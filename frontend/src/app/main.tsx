import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { queryClient } from "@/shared/queryClient";
import "./global.css";
import App from "./App.tsx";
import { AuthProvider } from "./auth/AuthContext.tsx";

// Plotly dependencies still expect a Node-style global in some browser bundles.
// Mirror window onto global before importing any charting code at runtime.
(window as typeof window & { global?: Window }).global = window;

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter basename="/app/">
      {/*
       * QueryClientProvider debe envolver a AuthProvider.
       * Issue #6 migrará AuthContext para usar useQueryClient() — si el provider
       * estuviera dentro de App.tsx o por debajo de AuthProvider, ese hook fallaría
       * con "No QueryClient set, use QueryClientProvider to set one".
       *
       * ReactQueryDevtools se excluye automáticamente en builds de producción
       * (process.env.NODE_ENV !== "development").
       */}
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <App />
        </AuthProvider>
        <ReactQueryDevtools initialIsOpen={false} />
      </QueryClientProvider>
    </BrowserRouter>
  </StrictMode>
);
