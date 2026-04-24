import { useState } from "react";

import { login } from "../api/auth";

function AdminLogin({ onAuthenticated }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (event) => {
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
      setError(err.message || "Login failed");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="app-container">
      <header className="app-header">
        <h1>Story Manager</h1>
      </header>
      <main className="login-panel">
        <form className="login-form" onSubmit={handleSubmit}>
          <h2>Admin Login</h2>
          <label>
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
