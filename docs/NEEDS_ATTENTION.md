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
