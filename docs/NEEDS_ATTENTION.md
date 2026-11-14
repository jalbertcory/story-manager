# Resolving library issues

Open **Background activity → Overview** to see Needs Attention.

- **Retry task** queues another attempt of the selected failed processing job.
- **Retry source check** checks a failed web novel again. **Retry shown checks**
  applies to the actionable items displayed in that card, not every hidden result.
- **Recover cover** queues extraction from an available original EPUB.
  **Recover shown covers** applies to the eligible items displayed in that card.
  If the original EPUB is unavailable, **Choose a cover** opens the book details.

Recent actions report queuing, running, completion, and errors. A queued action is
not a completed repair. Completed work refreshes library health; errors remain visible
and can be retried. If a completed extraction finds no usable cover, the missing-cover
issue remains for manual resolution. Work continues through the durable processing
queue after leaving the page; follow it under **Processing jobs**.

Metadata decisions, stale audiobook editions, and broken book files retain their
contextual review links because those decisions need the book or edition details.

The dashboard's rendering, action execution/progress, and shared job labels are
separate modules. Backup management is also isolated from the Utilities page in
`components/utilities/BackupsPanel.jsx`.

## Series gaps and new releases

- **Series gaps** lists numbered series where a whole-numbered book between 1 and the
  highest one you own is missing (for example books 1, 2 and 4). Gaps are computed from
  the library each time the page loads. **Dismiss** hides the current gaps of a series;
  a different gap in the same series appears again.
- **New in your series** lists recent and upcoming books that Google Books attributes to
  the same author and whose title or subtitle names the series. It needs Google Books to
  be enabled, covers only series with at least one non-web book, and shows release dates
  as publishers supplied them, so treat it as a hint rather than a catalogue.

A daily `series_check` job (also available through **Check series now**) refreshes the
release list and announces new findings through the `series_update` notification event.

## Notifications

**Settings → Notifications** manages outbound webhooks for ntfy, Discord, Slack, or a
generic JSON receiver. Each webhook subscribes to any of: new chapters found, audiobook
finished, background task failed (including backups and update checks), and series
updates. Deliveries run as `deliver_notification` jobs with retries. The webhook address
is write-only: after saving, the API and UI show only its host.
