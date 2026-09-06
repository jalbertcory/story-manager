import type useAttentionActions from "./useAttentionActions";
import type { ActionKind, ActionItem } from "./useAttentionActions";
export default function AttentionAction({
  kind,
  item,
  actions,
}: {
  kind: ActionKind;
  item: ActionItem;
  actions: ReturnType<typeof useAttentionActions>;
}) {
  const label = {
    job: "Retry task",
    refresh: "Retry source check",
    cover: "Recover cover",
  }[kind];
  const title =
    ("title" in item ? item.title : item.book_title) || "library task";
  return (
    <div className="attention-item-actions">
      <button
        disabled={actions.busy(kind, item)}
        aria-label={`${label} for ${title}`}
        onClick={() => actions.run(kind, item)}
      >
        {actions.busy(kind, item) ? "In progress…" : label}
      </button>
    </div>
  );
}
