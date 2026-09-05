import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getUniverses, setUniverseMembership } from "../api/library";

export default function UniverseMembership({
  bookId,
  series,
  currentName = "",
}) {
  const client = useQueryClient();
  const [name, setName] = useState(currentName || "");
  const { data: universes = [], error } = useQuery({
    queryKey: ["universes"],
    queryFn: getUniverses,
  });
  const mutation = useMutation({
    mutationFn: () =>
      setUniverseMembership({
        name: name.trim() || null,
        ...(series ? { series } : { book_id: bookId }),
      }),
    onSuccess: () => {
      for (const key of [
        "universes",
        "library-groups",
        "library-book-info",
        "book-catalog",
        "series-books",
      ]) {
        client.invalidateQueries({ queryKey: [key] });
      }
    },
  });
  return (
    <form
      className="universe-form"
      onSubmit={(e) => {
        e.preventDefault();
        mutation.mutate();
      }}
    >
      <label htmlFor={`universe-${bookId || "series"}`}>
        Universe{" "}
        {series && (
          <span className="hint">· applies to every book in {series}</span>
        )}
      </label>
      <div className="workspace-actions">
        <input
          id={`universe-${bookId || "series"}`}
          list="universe-options"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Choose or create a universe"
          maxLength={200}
        />
        <datalist id="universe-options">
          {universes.map((u) => (
            <option key={u.id} value={u.name} />
          ))}
        </datalist>
        <button
          disabled={mutation.isPending || name.trim() === (currentName || "")}
          type="submit"
        >
          {mutation.isPending ? "Saving…" : "Save universe"}
        </button>
      </div>
      <p className="hint">
        Leave blank to remove this membership. Series reading order stays
        unchanged.
      </p>
      {(mutation.error || error) && (
        <p role="alert" className="error">
          {(mutation.error || error).message}
        </p>
      )}
      {mutation.isSuccess && <p role="status">Universe saved.</p>}
    </form>
  );
}
