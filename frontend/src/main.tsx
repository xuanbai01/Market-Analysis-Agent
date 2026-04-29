import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "./App";
import "./index.css";

// Single QueryClient for the app. Defaults are fine for our shape:
// reports are cached in postgres on the backend, the frontend just
// asks for them. No optimistic updates, no infinite queries.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Don't auto-retry on errors — most of our errors (401, 429, 503)
      // are not transient or have specific UX.
      retry: false,
      refetchOnWindowFocus: false,
    },
  },
});

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("Missing #root element in index.html");

createRoot(rootEl).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
