import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getRecycleBin,
  permanentlyDeleteRecycledBook,
  restoreRecycledBook,
} from "../../api/books";
import { queryKeys } from "../../lib/queryKeys";
import ConfirmActionDialog from "../ConfirmActionDialog";

export default function RecycleBinPanel() {
  const queryClient = useQueryClient();
  const [permanentDeleteTarget, setPermanentDeleteTarget] = useState<
    | NonNullable<Awaited<ReturnType<typeof getRecycleBin>>["books"]>[number]
    | null
  >(null);

  const { data: recycleBin, isLoading: recycleBinLoading } = useQuery({
    queryKey: queryKeys.recycleBin,
    queryFn: getRecycleBin,
  });

  const restoreBookMutation = useMutation({
    mutationFn: restoreRecycledBook,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.recycleBin });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.bookCatalog.all,
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.series });
    },
  });

  const permanentDeleteMutation = useMutation({
    mutationFn: permanentlyDeleteRecycledBook,
    onSuccess: () => {
      setPermanentDeleteTarget(null);
      void queryClient.invalidateQueries({ queryKey: queryKeys.recycleBin });
    },
  });

  return (
    <>
      <section className="settings-section">
        <p className="hint">
          Deleted books and all files they own stay recoverable for{" "}
          {recycleBin?.retention_days || 30} days by default. Restore a book to
          return it to the library, or permanently delete it to remove its files
          now.
        </p>
        {recycleBinLoading ? (
          <p className="hint">Loading deleted books…</p>
        ) : (recycleBin?.books || []).length === 0 ? (
          <p className="hint">The recycle bin is empty.</p>
        ) : (
          <ul className="recycle-bin-list">
            {(recycleBin?.books ?? []).map((book) => (
              <li className="recycle-bin-item" key={book.id}>
                <div>
                  <strong>{book.title}</strong>
                  <p className="hint">by {book.author || "Unknown author"}</p>
                  <p className="hint">
                    {book.purge_after
                      ? `Recovery window ends ${new Date(book.purge_after).toLocaleString()}`
                      : "No automatic purge date is set"}
                    {!book.recovery_files_available &&
                      " · EPUB recovery file is missing"}
                  </p>
                </div>
                <div className="recycle-bin-actions">
                  <button
                    type="button"
                    onClick={() => restoreBookMutation.mutate(book.id)}
                    disabled={
                      restoreBookMutation.isPending ||
                      permanentDeleteMutation.isPending
                    }
                  >
                    Restore
                  </button>
                  <button
                    type="button"
                    className="btn-danger"
                    onClick={() => setPermanentDeleteTarget(book)}
                    disabled={
                      restoreBookMutation.isPending ||
                      permanentDeleteMutation.isPending
                    }
                  >
                    Permanently delete
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
        {(restoreBookMutation.isError || permanentDeleteMutation.isError) && (
          <p className="error" role="alert">
            {
              (restoreBookMutation.error || permanentDeleteMutation.error)
                ?.message
            }
          </p>
        )}
      </section>
      <ConfirmActionDialog
        open={Boolean(permanentDeleteTarget)}
        title={`Permanently delete “${permanentDeleteTarget?.title || "this book"}”?`}
        confirmLabel="Permanently delete"
        busyLabel="Deleting…"
        danger
        isPending={permanentDeleteMutation.isPending}
        onCancel={() => setPermanentDeleteTarget(null)}
        onConfirm={() =>
          permanentDeleteTarget &&
          permanentDeleteMutation.mutate(permanentDeleteTarget.id)
        }
      >
        <p>
          This removes the database record, EPUBs, cover, audiobook files, and
          saved revision history.
        </p>
        <p>
          <strong>This cannot be undone.</strong>
        </p>
      </ConfirmActionDialog>
    </>
  );
}
