import type { ReactNode } from "react";
function ConfirmActionDialog({
  open,
  title,
  children,
  confirmLabel,
  busyLabel = "Working…",
  danger = false,
  isPending = false,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  confirmLabel: string;
  busyLabel?: string;
  danger?: boolean;
  isPending?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  if (!open) return null;

  return (
    <div
      className="confirm-action-backdrop"
      role="presentation"
      onMouseDown={() => {
        if (!isPending) onCancel();
      }}
    >
      <section
        className="confirm-action-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-action-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <h2 id="confirm-action-title">{title}</h2>
        <div className="confirm-action-body">{children}</div>
        <div className="confirm-action-buttons">
          <button
            type="button"
            className="btn-text"
            onClick={onCancel}
            disabled={isPending}
          >
            Cancel
          </button>
          <button
            type="button"
            className={danger ? "btn-danger" : ""}
            onClick={onConfirm}
            disabled={isPending}
            autoFocus
          >
            {isPending ? busyLabel : confirmLabel}
          </button>
        </div>
      </section>
    </div>
  );
}

export default ConfirmActionDialog;
