import type { CatalogBook } from "../../types";
import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { updateBook } from "../../api/books";

export default function StandaloneTagAction({
  book,
  seriesOptions,
}: {
  book: Pick<CatalogBook, "id" | "series">;
  seriesOptions: string[];
}) {
  const queryClient = useQueryClient();
  const [value, setValue] = useState(book.series || "");

  useEffect(() => {
    setValue(book.series || "");
  }, [book.id, book.series]);

  const saveMutation = useMutation({
    mutationFn: (nextSeries: string) =>
      updateBook(book.id, { series: nextSeries.trim() || null }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["book-catalog"] });
      void queryClient.invalidateQueries({ queryKey: ["series"] });
      void queryClient.invalidateQueries({ queryKey: ["library-groups"] });
      void queryClient.invalidateQueries({ queryKey: ["series-books"] });
      void queryClient.invalidateQueries({
        queryKey: ["library-book-info", book.id],
      });
    },
  });

  const unchanged = (book.series || "") === value.trim();

  return (
    <form
      className="standalone-tag-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (!unchanged) {
          saveMutation.mutate(value);
        }
      }}
    >
      <label className="standalone-tag-label" htmlFor={`series-tag-${book.id}`}>
        Series
      </label>
      <input
        id={`series-tag-${book.id}`}
        list={`series-options-${book.id}`}
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder="Add to a series"
      />
      <datalist id={`series-options-${book.id}`}>
        {seriesOptions.map((series) => (
          <option key={series} value={series} />
        ))}
      </datalist>
      <button
        type="submit"
        className="btn"
        disabled={unchanged || saveMutation.isPending}
      >
        {saveMutation.isPending ? "Saving..." : "Save"}
      </button>
      {saveMutation.error && (
        <p role="alert" className="error">
          {saveMutation.error.message}
        </p>
      )}
    </form>
  );
}
