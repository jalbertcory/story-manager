import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "./index.css";
import App from "./App.jsx";

const queryClient = new QueryClient();

// Report uncaught JS errors and unhandled promise rejections to the backend
// so they appear in container logs alongside server-side logs.
function sendClientLog(level, message, source) {
  fetch("/api/logs/client", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ level, message, source }),
  }).catch(() => {});
}

window.addEventListener("error", (event) => {
  const msg = event.error
    ? `${event.error.message}\n${event.error.stack || ""}`
    : event.message;
  sendClientLog("ERROR", msg, `${event.filename}:${event.lineno}`);
});

window.addEventListener("unhandledrejection", (event) => {
  const reason = event.reason;
  const msg = reason instanceof Error
    ? `${reason.message}\n${reason.stack || ""}`
    : String(reason);
  sendClientLog("ERROR", `Unhandled promise rejection: ${msg}`);
});

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
