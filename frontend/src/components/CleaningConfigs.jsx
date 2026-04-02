import { useState, useEffect, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

const fetchConfigs = async () => {
  const res = await fetch("/api/cleaning-configs");
  if (!res.ok) throw new Error("Failed to fetch configs");
  return res.json();
};

function ConfigForm({ initial, onSave, onCancel, isSaving }) {
  const [name, setName] = useState(initial?.name || "");
  const [urlPattern, setUrlPattern] = useState(initial?.url_pattern || "");
  const [chapterSelectors, setChapterSelectors] = useState(
    (initial?.chapter_selectors || []).join(", "),
  );
  const [contentSelectors, setContentSelectors] = useState(
    (initial?.content_selectors || []).join(", "),
  );

  const handleSubmit = (e) => {
    e.preventDefault();
    onSave({
      name,
      url_pattern: urlPattern,
      chapter_selectors: chapterSelectors
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      content_selectors: contentSelectors
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
    });
  };

  return (
    <form className="config-form" onSubmit={handleSubmit}>
      <label>
        Name
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
      </label>
      <label>
        URL Pattern (regex)
        <input
          value={urlPattern}
          onChange={(e) => setUrlPattern(e.target.value)}
          required
          placeholder="e.g. fanfiction\\.net"
        />
      </label>
      <label>
        Chapter Selectors (comma-separated CSS)
        <input
          value={chapterSelectors}
          onChange={(e) => setChapterSelectors(e.target.value)}
          placeholder="e.g. div.author-note"
        />
      </label>
      <label>
        Content Selectors (comma-separated CSS)
        <input
          value={contentSelectors}
          onChange={(e) => setContentSelectors(e.target.value)}
          placeholder="e.g. span.note, p.footnote"
        />
      </label>
      <div className="form-actions">
        <button type="submit" disabled={isSaving}>
          {isSaving ? "Saving..." : "Save"}
        </button>
        <button type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function CleaningConfigs({ onBack }) {
  const queryClient = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState(null);

  const [reprocessStatus, setReprocessStatus] = useState(null);
  const [polling, setPolling] = useState(false);

  const pollStatus = useCallback(async () => {
    try {
      const res = await fetch("/api/books/reprocess-all/status");
      const data = await res.json();
      setReprocessStatus(data);
      if (!data.running) {
        setPolling(false);
        queryClient.invalidateQueries({ queryKey: ["book-catalog"] });
      }
    } catch {
      setPolling(false);
    }
  }, [queryClient]);

  useEffect(() => {
    // Check if a reprocess is already running on mount
    pollStatus();
  }, [pollStatus]);

  useEffect(() => {
    if (!polling) return;
    const interval = setInterval(pollStatus, 2000);
    return () => clearInterval(interval);
  }, [polling, pollStatus]);

  const reprocessMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch("/api/books/reprocess-all", { method: "POST" });
      if (res.status === 409) throw new Error("Reprocess already in progress");
      if (!res.ok) throw new Error("Failed to start reprocess");
      return res.json();
    },
    onSuccess: () => {
      setReprocessStatus({ running: true, total: 0, processed: 0, updated: 0 });
      setPolling(true);
    },
  });

  const isReprocessing = polling || reprocessStatus?.running;

  const {
    data: configs = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ["cleaning-configs"],
    queryFn: fetchConfigs,
  });

  const createMutation = useMutation({
    mutationFn: async (data) => {
      const res = await fetch("/api/cleaning-configs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Create failed");
      }
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["cleaning-configs"] });
      setCreating(false);
    },
  });

  const updateMutation = useMutation({
    mutationFn: async ({ id, data }) => {
      const res = await fetch(`/api/cleaning-configs/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Update failed");
      }
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["cleaning-configs"] });
      setEditingId(null);
      setPolling(true);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (id) => {
      const res = await fetch(`/api/cleaning-configs/${id}`, {
        method: "DELETE",
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Delete failed");
      }
    },
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["cleaning-configs"] }),
  });

  return (
    <div className={onBack ? "cleaning-configs" : undefined}>
      {onBack && (
        <div className="settings-header">
          <button className="btn-text" onClick={onBack} style={{ flexShrink: 0 }}>← Back</button>
          <h2>Cleaning Configs</h2>
        </div>
      )}
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: "0.75rem" }}>
        <button onClick={() => setCreating(true)} disabled={creating}>
          + New Config
        </button>
      </div>

      {isLoading && <p>Loading...</p>}
      {error && <p className="error">{error.message}</p>}

      {creating && (
        <div className="config-editor">
          <h3>New Config</h3>
          <ConfigForm
            onSave={(data) => createMutation.mutate(data)}
            onCancel={() => setCreating(false)}
            isSaving={createMutation.isPending}
          />
          {createMutation.isError && (
            <p className="error">{createMutation.error.message}</p>
          )}
        </div>
      )}

      <section className="settings-section">
        <h3>Clean All Books</h3>
        <p className="hint">
          Re-applies cleaning configs and selectors to every book in the library.
        </p>
        <div className="settings-actions">
          <button
            onClick={() => reprocessMutation.mutate()}
            disabled={isReprocessing || reprocessMutation.isPending}
          >
            {isReprocessing ? "Cleaning..." : "Clean All Books"}
          </button>
        </div>
        {isReprocessing && reprocessStatus?.total > 0 && (
          <p className="hint" style={{ marginTop: "0.5rem" }}>
            {reprocessStatus.processed} / {reprocessStatus.total} books processed ({reprocessStatus.updated} updated)
          </p>
        )}
        {reprocessMutation.isError && (
          <p className="error" style={{ marginTop: "0.5rem" }}>
            {reprocessMutation.error?.message}
          </p>
        )}
        {!isReprocessing && reprocessStatus && !reprocessStatus.running && reprocessStatus.total > 0 && (
          <p className="hint" style={{ marginTop: "0.5rem" }}>
            Done. {reprocessStatus.updated} / {reprocessStatus.total} books updated.
          </p>
        )}
        {reprocessStatus?.error && (
          <p className="error" style={{ marginTop: "0.5rem" }}>
            {reprocessStatus.error}
          </p>
        )}
      </section>

      <div className="config-list">
        {configs.map((config) => (
          <div key={config.id} className="config-card">
            {editingId === config.id ? (
              <div>
                <ConfigForm
                  initial={config}
                  onSave={(data) =>
                    updateMutation.mutate({ id: config.id, data })
                  }
                  onCancel={() => setEditingId(null)}
                  isSaving={updateMutation.isPending}
                />
                {updateMutation.isError && (
                  <p className="error">{updateMutation.error.message}</p>
                )}
              </div>
            ) : (
              <div>
                <div className="config-header">
                  <strong>{config.name}</strong>
                  <code className="url-pattern">{config.url_pattern}</code>
                  <div className="config-actions">
                    <button onClick={() => setEditingId(config.id)}>
                      Edit
                    </button>
                    <button
                      className="btn-danger"
                      onClick={() => {
                        if (window.confirm(`Delete config "${config.name}"?`)) {
                          deleteMutation.mutate(config.id);
                        }
                      }}
                    >
                      Delete
                    </button>
                  </div>
                </div>
                <div className="config-selectors">
                  {config.chapter_selectors?.length > 0 && (
                    <p>
                      <strong>Chapter:</strong>{" "}
                      {config.chapter_selectors.join(", ")}
                    </p>
                  )}
                  {config.content_selectors?.length > 0 && (
                    <p>
                      <strong>Content:</strong>{" "}
                      {config.content_selectors.join(", ")}
                    </p>
                  )}
                </div>
              </div>
            )}
          </div>
        ))}
        {configs.length === 0 && !isLoading && <p>No cleaning configs yet.</p>}
      </div>
    </div>
  );
}

export default CleaningConfigs;
