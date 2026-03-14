import { useEffect, useState } from "react";

async function readJson(res, fallback) {
  if (res.ok) return res.json();
  let detail = fallback;
  try {
    const data = await res.json();
    detail = data.detail || fallback;
  } catch {
    // Ignore JSON parse errors and use the fallback message.
  }
  throw new Error(detail);
}

function formatDate(value) {
  if (!value) return "Never";
  return new Date(value).toLocaleString();
}

function ReaderKeys() {
  const [keys, setKeys] = useState([]);
  const [label, setLabel] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [createdToken, setCreatedToken] = useState(null);

  const loadKeys = async () => {
    setLoading(true);
    setError("");
    try {
      const res = await fetch("/api/reader-keys");
      const data = await readJson(res, "Failed to load reader keys");
      setKeys(Array.isArray(data) ? data : []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadKeys();
  }, []);

  const handleCreate = async (e) => {
    e.preventDefault();
    if (!label.trim()) return;
    setSubmitting(true);
    setError("");
    setCreatedToken(null);
    try {
      const res = await fetch("/api/reader-keys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label: label.trim() }),
      });
      const data = await readJson(res, "Failed to create reader key");
      setCreatedToken(data);
      setLabel("");
      await loadKeys();
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const handleRevoke = async (id) => {
    setError("");
    try {
      const res = await fetch(`/api/reader-keys/${id}`, { method: "DELETE" });
      if (!res.ok) {
        throw new Error("Failed to revoke reader key");
      }
      await loadKeys();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <section className="settings-section">
      <h3>Reader API Keys</h3>
      <p className="hint">
        Create a separate read-only key for each e-reader or app. The full token is shown only once.
      </p>

      <form
        onSubmit={handleCreate}
        style={{ display: "flex", gap: "0.75rem", alignItems: "center", flexWrap: "wrap" }}
      >
        <input
          type="text"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="Device label, e.g. Kobo"
          style={{ minWidth: "240px" }}
        />
        <button type="submit" disabled={submitting || !label.trim()}>
          {submitting ? "Creating..." : "Create Reader Key"}
        </button>
      </form>

      {createdToken && (
        <div style={{ marginTop: "1rem" }}>
          <p className="hint" style={{ marginBottom: "0.4rem" }}>
            Save this token now. It will not be shown again.
          </p>
          <code
            style={{
              display: "block",
              padding: "0.75rem",
              borderRadius: "6px",
              background: "var(--surface, #1a1a2e)",
              wordBreak: "break-all",
            }}
          >
            {createdToken.token}
          </code>
        </div>
      )}

      {error && (
        <p className="error" style={{ marginTop: "0.75rem" }}>
          {error}
        </p>
      )}

      {loading ? (
        <p className="hint" style={{ marginTop: "1rem" }}>Loading reader keys...</p>
      ) : keys.length === 0 ? (
        <p className="hint" style={{ marginTop: "1rem" }}>No reader keys yet.</p>
      ) : (
        <div style={{ marginTop: "1rem", display: "grid", gap: "0.75rem" }}>
          {keys.map((key) => (
            <div
              key={key.id}
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                gap: "1rem",
                padding: "0.9rem 1rem",
                borderRadius: "8px",
                background: "var(--surface, #1a1a2e)",
                opacity: key.revoked_at ? 0.7 : 1,
                flexWrap: "wrap",
              }}
            >
              <div>
                <strong>{key.label}</strong>
                <div className="hint">{key.token_prefix}</div>
                <div className="hint">Created: {formatDate(key.created_at)}</div>
                <div className="hint">Last used: {formatDate(key.last_used_at)}</div>
                {key.revoked_at && <div className="hint">Revoked: {formatDate(key.revoked_at)}</div>}
              </div>
              {!key.revoked_at && (
                <button className="btn-danger" onClick={() => handleRevoke(key.id)}>
                  Revoke
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export default ReaderKeys;
