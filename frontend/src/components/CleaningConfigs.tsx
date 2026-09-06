import { useState, useEffect, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import type { FormEvent } from "react";
import type { components } from "../api/schema";
import {
  getCleaningConfigs as fetchConfigs,
  createCleaningConfig,
  updateCleaningConfig,
  deleteCleaningConfig,
  reprocessAllBooks,
  getReprocessAllStatus,
} from "../api/cleaning";
type Config = components["schemas"]["CleaningConfig"];
type ConfigInput = components["schemas"]["CleaningConfigCreate"];

function ConfigForm({
  initial,
  onSave,
  onCancel,
  isSaving,
}: {
  initial?: Config;
  onSave: (data: ConfigInput) => void;
  onCancel: () => void;
  isSaving: boolean;
}) {
  const [name, setName] = useState(initial?.name || "");
  const [urlPattern, setUrlPattern] = useState(initial?.url_pattern || "");
  const [chapterSelectors, setChapterSelectors] = useState(
    (initial?.chapter_selectors || []).join(", "),
  );
  const [contentSelectors, setContentSelectors] = useState(
    (initial?.content_selectors || []).join(", "),
  );

  const handleSubmit = (e: FormEvent) => {
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

function CleaningConfigs({ onBack }: { onBack?: () => void }) {
  const queryClient = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [jobNotice, setJobNotice] = useState("");

  const [reprocessStatus, setReprocessStatus] = useState<Awaited<
    ReturnType<typeof getReprocessAllStatus>
  > | null>(null);
  const [polling, setPolling] = useState(false);

  const pollStatus = useCallback(async () => {
    try {
      const data = await getReprocessAllStatus();
      setReprocessStatus(data);
      if (!data.running) {
        setPolling(false);
        void queryClient.invalidateQueries({ queryKey: ["book-catalog"] });
      }
    } catch {
      setPolling(false);
    }
  }, [queryClient]);

  useEffect(() => {
    // Check if a reprocess is already running on mount
    void pollStatus();
  }, [pollStatus]);

  useEffect(() => {
    if (!polling) return;
    const interval = setInterval(() => {
      void pollStatus();
    }, 2000);
    return () => clearInterval(interval);
  }, [polling, pollStatus]);

  const reprocessMutation = useMutation({
    mutationFn: reprocessAllBooks,
    onSuccess: () => {
      setJobNotice("Library cleaning job queued.");
      setReprocessStatus({ running: true, total: 0, processed: 0 });
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
    mutationFn: createCleaningConfig,
    onSuccess: () => {
      setJobNotice("Cleaning config saved; affected book cleaning is queued.");
      void queryClient.invalidateQueries({ queryKey: ["cleaning-configs"] });
      setCreating(false);
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: ConfigInput }) =>
      updateCleaningConfig(id, data),
    onSuccess: () => {
      setJobNotice(
        "Cleaning config updated; affected book cleaning is queued.",
      );
      void queryClient.invalidateQueries({ queryKey: ["cleaning-configs"] });
      setEditingId(null);
      setPolling(true);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteCleaningConfig,
    onSuccess: () => {
      setJobNotice(
        "Cleaning config deleted; restoring affected books is queued.",
      );
      void queryClient.invalidateQueries({ queryKey: ["cleaning-configs"] });
      void queryClient.invalidateQueries({
        queryKey: ["active-processing-jobs"],
      });
    },
  });

  return (
    <div className={onBack ? "cleaning-configs" : undefined}>
      <div className="settings-header">
        {onBack && (
          <button
            className="btn-text"
            onClick={onBack}
            style={{ flexShrink: 0 }}
          >
            ← Back
          </button>
        )}
        <h2>Cleaning Rules</h2>
        <button onClick={() => setCreating(true)} disabled={creating}>
          + New Config
        </button>
      </div>
      {isLoading && <p>Loading...</p>}
      {error && <p className="error">{error.message}</p>}

      <section className="settings-section">
        <h3>Clean All Books</h3>
        <p className="hint">
          Applies the current cleaning rules to every book in your library.
        </p>
        <div className="settings-actions">
          <button
            onClick={() => reprocessMutation.mutate()}
            disabled={isReprocessing || reprocessMutation.isPending}
          >
            {isReprocessing ? "Cleaning..." : "Clean All Books"}
          </button>
        </div>
        {jobNotice && (
          <p className="job-queued-notice" role="status">
            {jobNotice} <a href="/processing">View processing</a>
          </p>
        )}
        {isReprocessing &&
          reprocessStatus &&
          (reprocessStatus.total ?? 0) > 0 && (
            <p className="hint" style={{ marginTop: "0.5rem" }}>
              {reprocessStatus.processed} / {reprocessStatus.total} books
              processed
            </p>
          )}
        {reprocessMutation.isError && (
          <p className="error" style={{ marginTop: "0.5rem" }}>
            {reprocessMutation.error?.message}
          </p>
        )}
        {!isReprocessing &&
          reprocessStatus &&
          !reprocessStatus.running &&
          (reprocessStatus.total ?? 0) > 0 && (
            <p className="hint" style={{ marginTop: "0.5rem" }}>
              Cleaning job {reprocessStatus.status || "completed"}.
            </p>
          )}
        {reprocessStatus?.error && (
          <p className="error" style={{ marginTop: "0.5rem" }}>
            {reprocessStatus.error}
          </p>
        )}
      </section>

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
                  {(config.chapter_selectors?.length ?? 0) > 0 && (
                    <p>
                      <strong>Chapter:</strong>{" "}
                      {config.chapter_selectors?.join(", ")}
                    </p>
                  )}
                  {(config.content_selectors?.length ?? 0) > 0 && (
                    <p>
                      <strong>Content:</strong>{" "}
                      {config.content_selectors?.join(", ")}
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
