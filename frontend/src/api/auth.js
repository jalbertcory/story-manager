import { sendJson, sendWithoutBody } from "./client";

const DISABLED_STATUS = { mode: "disabled", authenticated: true };

export async function getAuthStatus() {
  try {
    const response = await fetch("/api/auth/status");
    if (!response.ok) {
      return DISABLED_STATUS;
    }
    const status = await response.json();
    if (!status || typeof status !== "object" || !("authenticated" in status)) {
      return DISABLED_STATUS;
    }
    return status;
  } catch {
    return DISABLED_STATUS;
  }
}

export async function login(password) {
  return sendJson("/api/auth/login", {
    body: { password },
    fallbackMessage: "Login failed",
  });
}

export async function logout() {
  return sendWithoutBody("/api/auth/logout", {
    fallbackMessage: "Logout failed",
  });
}
