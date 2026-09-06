import type { OpenBook } from "../../types";
import { useQuery } from "@tanstack/react-query";
import { getAllBookCatalog } from "../../api/books";
import { getSeries } from "../../api/series";
import SeriesSummaryRow from "../book-list/SeriesSummaryRow";
import UniverseMembership from "../UniverseMembership";

export default function SeriesOrganizer({
  series,
  onEdit,
  onSeriesChange,
}: {
  series: string;
  onEdit: OpenBook;
  onSeriesChange: (series: string) => void;
}) {
  // Only mounted by an explicit organizer action; never reorder a filtered page.
  const books = useQuery({
    queryKey: ["series-books", series],
    queryFn: () => getAllBookCatalog({ series, sortBy: "series_index" }),
  });
  const allSeries = useQuery({ queryKey: ["series"], queryFn: getSeries });
  if (books.isLoading || allSeries.isLoading)
    return <p role="status">Loading complete series for organizing…</p>;
  if (books.error || allSeries.error)
    return (
      <div role="alert">
        Could not load the complete series.{" "}
        {books.error?.message || allSeries.error?.message}
        <button
          onClick={() => {
            void books.refetch();
            void allSeries.refetch();
          }}
        >
          Try again
        </button>
      </div>
    );
  return (
    <>
      <UniverseMembership
        key={`${series}-${books.data?.[0]?.universe_name}`}
        series={series}
        currentName={books.data?.[0]?.universe_name}
      />
      <SeriesSummaryRow
        series={series}
        books={books.data ?? []}
        allSeries={allSeries.data ?? []}
        onEdit={onEdit}
        onSeriesChange={onSeriesChange}
        defaultExpanded
        hideHeading
      />
    </>
  );
}
