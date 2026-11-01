import { api, unwrap } from "./client";
import type { Schemas } from "./client";
const DISABLED_STATUS: Schemas["AdminAuthStatus"] = {
  mode: "disabled",
  authenticated: true,
};
// Servers that predate admin auth have no status endpoint and never required
// sign-in. Any other failure (network down, 5xx) is reported to the caller
// rather than guessed at, so an unreachable server is not shown as signed in.
export async function getAuthStatus() {
  const result = await api.GET("/api/auth/status");
  if (result.response.status === 404) return DISABLED_STATUS;
  return unwrap(Promise.resolve(result), "Could not check sign-in status");
}
export function login(password: string) {
  return unwrap(
    api.POST("/api/auth/login", { body: { password } }),
    "Login failed",
  );
}
export function logout() {
  return unwrap(api.POST("/api/auth/logout"), "Logout failed");
}
