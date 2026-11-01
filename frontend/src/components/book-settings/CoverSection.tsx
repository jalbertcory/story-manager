import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getApiCoverUrl,
  retryBookCover,
  setBookCoverUrl,
  uploadBookCover,
} from "../../api/covers";
import { invalidateBookViews, queryKeys } from "../../lib/queryKeys";
import type { Book } from "../../types";

export default function CoverSection({
  book,
  onNotice,
}: {
  book: Book;
  onNotice: (message: string) => void;
}) {
  const queryClient = useQueryClient();
  const coverInputRef = useRef<HTMLInputElement>(null);
  const [coverUrl, setCoverUrl] = useState("");

  // Cover files live at a deterministic URL (/api/covers/{book_id}), so the
  // browser happily caches them. Whenever any cover mutation succeeds we bump
  // `coverVersion` and append it as a cache-busting query param on the <img>,
  // forcing the browser to fetch the freshly-written file.
  const [coverVersion, setCoverVersion] = useState(0);
  const bumpCoverVersion = () => setCoverVersion((v) => v + 1);
  const coverSaved = () => {
    bumpCoverVersion();
    invalidateBookViews(queryClient, book.id);
    void queryClient.invalidateQueries({
      queryKey: queryKeys.books.detail(book.id),
    });
  };

  const coverMutation = useMutation({
    mutationFn: (file: File) => uploadBookCover(book.id, file),
    onSuccess: coverSaved,
  });

  const retryCoverMutation = useMutation({
    mutationFn: () => retryBookCover(book.id),
    onSuccess: () => {
      onNotice("Cover re-extraction job queued.");
      void queryClient.invalidateQueries({
        queryKey: queryKeys.activeProcessingJobs,
      });
    },
  });

  const coverUrlMutation = useMutation({
    mutationFn: (url: string) => setBookCoverUrl(book.id, url),
    onSuccess: () => {
      coverSaved();
      setCoverUrl("");
    },
  });

  return (
    <div className="settings-cover-aside">
      {book.cover_path ? (
        <img
          src={`${getApiCoverUrl(book.id)}?v=${coverVersion}`}
          alt="Cover"
          className="settings-cover-img"
        />
      ) : (
        <div className="settings-cover-placeholder">No cover</div>
      )}
      <input
        ref={coverInputRef}
        type="file"
        accept=".jpg,.jpeg,.png,.webp"
        style={{ display: "none" }}
        onChange={(e) =>
          e.target.files?.[0] && coverMutation.mutate(e.target.files[0])
        }
      />
      <button
        className="btn-sm"
        onClick={() => coverInputRef.current?.click()}
        disabled={coverMutation.isPending || coverUrlMutation.isPending}
      >
        {coverMutation.isPending
          ? "Uploading…"
          : book.cover_path
            ? "Replace"
            : "Upload"}
      </button>
      {book.immutable_path && (
        <button
          className="btn-sm btn-secondary"
          onClick={() => retryCoverMutation.mutate()}
          disabled={
            retryCoverMutation.isPending ||
            coverMutation.isPending ||
            coverUrlMutation.isPending
          }
        >
          {retryCoverMutation.isPending ? "Queueing…" : "Queue re-extract"}
        </button>
      )}
      <div className="cover-url-row">
        <input
          type="text"
          placeholder="Image URL…"
          value={coverUrl}
          onChange={(e) => setCoverUrl(e.target.value)}
          onKeyDown={(e) =>
            e.key === "Enter" &&
            coverUrl.trim() &&
            coverUrlMutation.mutate(coverUrl.trim())
          }
        />
        <button
          className="btn-sm"
          onClick={() => coverUrlMutation.mutate(coverUrl.trim())}
          disabled={
            !coverUrl.trim() ||
            coverUrlMutation.isPending ||
            coverMutation.isPending
          }
        >
          {coverUrlMutation.isPending ? "…" : "Set"}
        </button>
      </div>
      {coverMutation.isError && (
        <p className="error" role="alert">
          {coverMutation.error.message}
        </p>
      )}
      {coverUrlMutation.isError && (
        <p className="error" role="alert">
          {coverUrlMutation.error.message}
        </p>
      )}
      {retryCoverMutation.isError && (
        <p className="error" role="alert">
          {retryCoverMutation.error.message}
        </p>
      )}
    </div>
  );
}
