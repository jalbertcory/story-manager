import type { KeyboardEvent, ReactNode } from "react";
import { useEffect, useRef } from "react";

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

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
  const dialogRef = useRef<HTMLElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);

  // Move focus into the dialog, and return it to whatever opened the dialog
  // once it closes.
  useEffect(() => {
    if (!open) return;
    const opener =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    confirmRef.current?.focus();
    return () => {
      if (opener?.isConnected) opener.focus();
    };
  }, [open]);

  if (!open) return null;

  const handleKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      if (!isPending) onCancel();
      return;
    }
    if (event.key !== "Tab" || !dialogRef.current) return;
    // Keep keyboard focus inside the modal dialog.
    const focusable = Array.from(
      dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE),
    );
    if (!focusable.length) {
      event.preventDefault();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  };

  return (
    <div
      className="confirm-action-backdrop"
      role="presentation"
      onMouseDown={() => {
        if (!isPending) onCancel();
      }}
    >
      <section
        ref={dialogRef}
        className="confirm-action-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-action-title"
        onMouseDown={(event) => event.stopPropagation()}
        onKeyDown={handleKeyDown}
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
            ref={confirmRef}
            type="button"
            className={danger ? "btn-danger" : ""}
            onClick={onConfirm}
            disabled={isPending}
          >
            {isPending ? busyLabel : confirmLabel}
          </button>
        </div>
      </section>
    </div>
  );
}

export default ConfirmActionDialog;
