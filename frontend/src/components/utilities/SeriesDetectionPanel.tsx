import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { detectSeries } from "../../api/imports";
import { queryKeys } from "../../lib/queryKeys";

export default function SeriesDetectionPanel() {
  const queryClient = useQueryClient();
  const [detectState, setDetectState] = useState<
    | (Awaited<ReturnType<typeof detectSeries>> & { error?: boolean })
    | "pending"
    | null
  >(null); // null | "pending" | { updated, series_detected, error? }

  const handleDetectSeries = async () => {
    setDetectState("pending");
    try {
      const data = await detectSeries();
      if (data.updated > 0) {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.bookCatalog.all,
        });
      }
      setDetectState(data);
    } catch {
      setDetectState({ updated: 0, series_detected: [], error: true });
    }
  };

  return (
    <section className="settings-section">
      <p className="hint">
        Assigns series names found in book titles to books without a series.
      </p>
      <div className="settings-actions">
        <button
          onClick={() => {
            void handleDetectSeries();
          }}
          disabled={detectState === "pending"}
        >
          {detectState === "pending"
            ? "Detecting…"
            : "Detect Series in Library"}
        </button>
      </div>
      {detectState && detectState !== "pending" && (
        <p
          className={detectState.error ? "error" : "hint"}
          style={{ marginTop: "0.5rem" }}
        >
          {detectState.error
            ? "Error running detection."
            : detectState.updated === 0
              ? "No new series found."
              : `Updated ${detectState.updated} book${detectState.updated > 1 ? "s" : ""}: ${detectState.series_detected.join(", ")}`}
        </p>
      )}
    </section>
  );
}
