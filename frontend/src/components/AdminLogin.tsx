import type { FormEvent } from "react";
import { useState } from "react";

import { login } from "../api/auth";
import Icon from "./ui/Icon";

function AdminLogin({
  onAuthenticated,
}: {
  onAuthenticated: (status: Awaited<ReturnType<typeof login>>) => void;
}) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);
    try {
      const status = await login(password);
      if (status.authenticated) {
        onAuthenticated(status);
      } else {
        setError("Login failed");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="login-page">
      <main className="login-panel">
        <div className="login-brand">
          <span className="wordmark-mark" aria-hidden="true">
            <Icon name="library" size={20} />
          </span>
          <h1>Story Manager</h1>
        </div>
        <form
          className="login-form"
          onSubmit={(event) => {
            void handleSubmit(event);
          }}
        >
          <div>
            <h2>Admin Login</h2>
            <p className="hint">Sign in to manage your library.</p>
          </div>
          <label className="field">
            Password
            <input
              type="password"
              value={password}
              autoFocus
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          <button
            className="btn-primary"
            type="submit"
            disabled={!password || isSubmitting}
          >
            {isSubmitting ? "Signing in..." : "Sign In"}
          </button>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
        </form>
      </main>
    </div>
  );
}

export default AdminLogin;
