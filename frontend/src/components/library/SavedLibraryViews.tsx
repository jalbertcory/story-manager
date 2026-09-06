import type { Navigate } from "../../types";
import { useState } from "react";

const STORAGE_KEY = "story-manager.library-views.v1";
interface SavedView {
  name: string;
  path: string;
}
function readViews(): SavedView[] {
  try {
    const data: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
    return Array.isArray(data)
      ? data.filter(
          (v): v is SavedView =>
            v != null &&
            typeof v === "object" &&
            typeof v.name === "string" &&
            typeof v.path === "string" &&
            /^\/(?:\?|$)/.test(v.path),
        )
      : [];
  } catch {
    return [];
  }
}

export default function SavedLibraryViews({
  path,
  onNavigate,
}: {
  path: string;
  onNavigate: Navigate;
}) {
  const [views, setViews] = useState(readViews);
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const save = (next: SavedView[]) => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      setViews(next);
      setError("");
    } catch {
      setError(
        "This browser could not save your views. Check its storage settings.",
      );
    }
  };
  return (
    <details className="workspace-disclosure">
      <summary>Saved views</summary>
      <p className="hint">
        Save this search, grouping, filters, and sort order in this browser.
      </p>
      <form
        className="workspace-actions"
        onSubmit={(event) => {
          event.preventDefault();
          const label = name.trim();
          if (!label) return;
          save([
            ...views.filter((v) => v.name !== label),
            { name: label, path },
          ]);
          setName("");
        }}
      >
        <input
          aria-label="View name"
          maxLength={80}
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Name this view"
        />
        <button disabled={!name.trim()} type="submit">
          Save current view
        </button>
      </form>
      {views.map((view) => (
        <div className="workspace-actions" key={view.name}>
          <button onClick={() => onNavigate(view.path)}>{view.name}</button>
          <button
            aria-label={`Delete saved view ${view.name}`}
            onClick={() => save(views.filter((v) => v.name !== view.name))}
          >
            Delete
          </button>
        </div>
      ))}
      {error && <p role="alert">{error}</p>}
    </details>
  );
}
