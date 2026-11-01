import { postClientLog } from "./api/admin";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import "./index.css";
import App from "./App";
import { applyThemePreference, readThemePreference } from "./lib/theme";
import { createQueryClient } from "./lib/queryClient";
import { reloadAfterStaleChunk } from "./lib/staleChunk";

// Apply the saved theme before the first render to avoid a flash of the
// wrong colors.
applyThemePreference(readThemePreference());

const queryClient = createQueryClient();

// After a deploy, lazily loaded pages may point at chunks the server no longer
// has. Reload once to pick up the new build instead of showing a broken page.
window.addEventListener("vite:preloadError", (event) => {
  if (reloadAfterStaleChunk()) event.preventDefault();
});

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
