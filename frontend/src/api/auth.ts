import { api, unwrap, unwrapOptional } from "./client";
import type { Schemas } from "./client";
const DISABLED_STATUS: Schemas["AdminAuthStatus"] = {
  mode: "disabled",
  authenticated: true,
};
export async function getAuthStatus() {
  try {
    return (
      (await unwrapOptional(api.GET("/api/auth/status"))) ?? DISABLED_STATUS
    );
  } catch {
    return DISABLED_STATUS;
  }
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
