import { useState } from "react";
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
    (initial?.chapter_selectors || []).join(", ")
  );
  const [contentSelectors, setContentSelectors] = useState(
    (initial?.content_selectors || []).join(", ")
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
        <input value={name} onChange={(e) => setName(e.target.value)} required />
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

  const { data: configs = [], isLoading, error } = useQuery({
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
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (id) => {
      const res = await fetch(`/api/cleaning-configs/${id}`, { method: "DELETE" });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Delete failed");
      }
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["cleaning-configs"] }),
  });

  return (
    <div className="cleaning-configs">
      <div className="settings-header">
        <button onClick={onBack}>← Back</button>
        <h2>Cleaning Configs</h2>
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

      <div className="config-list">
        {configs.map((config) => (
          <div key={config.id} className="config-card">
            {editingId === config.id ? (
              <div>
                <ConfigForm
                  initial={config}
                  onSave={(data) => updateMutation.mutate({ id: config.id, data })}
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
                    <button onClick={() => setEditingId(config.id)}>Edit</button>
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
                      <strong>Chapter:</strong> {config.chapter_selectors.join(", ")}
                    </p>
                  )}
                  {config.content_selectors?.length > 0 && (
                    <p>
                      <strong>Content:</strong> {config.content_selectors.join(", ")}
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
