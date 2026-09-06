import { useEffect, useState } from "react";

import type { FormEvent } from "react";
import { getReaderKeys, createReaderKey, revokeReaderKey } from "../api/admin";

function formatDate(value: string | null | undefined) {
  if (!value) return "Never";
  return new Date(value).toLocaleString();
}

function ReaderKeys({ showHeading = true }) {
  const [keys, setKeys] = useState<Awaited<ReturnType<typeof getReaderKeys>>>(
    [],
  );
  const [label, setLabel] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [createdToken, setCreatedToken] = useState<Awaited<
    ReturnType<typeof createReaderKey>
  > | null>(null);

  const loadKeys = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await getReaderKeys();
      setKeys(Array.isArray(data) ? data : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadKeys();
  }, []);

  const handleCreate = async (e: FormEvent) => {
    e.preventDefault();
    if (!label.trim()) return;
    setSubmitting(true);
    setError("");
    setCreatedToken(null);
    try {
      const data = await createReaderKey(label.trim());
      setCreatedToken(data);
      setLabel("");
      await loadKeys();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const handleRevoke = async (id: number) => {
    setError("");
    try {
      await revokeReaderKey(id);
      await loadKeys();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <section className="settings-section">
      {showHeading && <h3>Reader API Keys</h3>}
      <p className="hint">
        Create a separate read-only key for each e-reader or app. The full token
        is shown only once.
      </p>

      <form
        onSubmit={handleCreate}
        style={{
          display: "flex",
          gap: "0.75rem",
          alignItems: "center",
          flexWrap: "wrap",
        }}
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
        <p className="hint" style={{ marginTop: "1rem" }}>
          Loading reader keys...
        </p>
      ) : keys.length === 0 ? (
        <p className="hint" style={{ marginTop: "1rem" }}>
          No reader keys yet.
        </p>
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
                <div className="hint">
                  Created: {formatDate(key.created_at)}
                </div>
                <div className="hint">
                  Last used: {formatDate(key.last_used_at)}
                </div>
                {key.revoked_at && (
                  <div className="hint">
                    Revoked: {formatDate(key.revoked_at)}
                  </div>
                )}
              </div>
              {!key.revoked_at && (
                <button
                  className="btn-danger"
                  onClick={() => handleRevoke(key.id)}
                >
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
