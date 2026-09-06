import { postClientLog } from "./api/admin";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "./index.css";
import App from "./App";

const queryClient = new QueryClient();

// Report uncaught JS errors and unhandled promise rejections to the backend
// so they appear in container logs alongside server-side logs.

window.addEventListener("error", (event) => {
  const msg =
    event.error instanceof Error
      ? `${event.error.message}\n${event.error.stack || ""}`
      : event.message;
  void postClientLog(msg, `${event.filename}:${event.lineno}`).catch(() => {});
});

window.addEventListener("unhandledrejection", (event) => {
  const reason: unknown = event.reason;
  const msg =
    reason instanceof Error
      ? `${reason.message}\n${reason.stack || ""}`
      : String(reason);
  void postClientLog(`Unhandled promise rejection: ${msg}`).catch(() => {});
});

const root = document.getElementById("root");
if (!root) throw new Error("Missing application root");
createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
