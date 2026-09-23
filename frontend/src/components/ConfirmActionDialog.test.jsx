import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import ConfirmActionDialog from "./ConfirmActionDialog";

function Harness({ onConfirm = () => {} }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Delete book
      </button>
      <ConfirmActionDialog
        open={open}
        title="Delete this book?"
        confirmLabel="Delete"
        onConfirm={onConfirm}
        onCancel={() => setOpen(false)}
      >
        <p>It moves to the recycle bin.</p>
      </ConfirmActionDialog>
    </>
  );
}

describe("ConfirmActionDialog", () => {
  it("focuses the confirm action and closes on Escape, restoring focus", () => {
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Delete book" });
    opener.focus();
    fireEvent.click(opener);

    const confirm = screen.getByRole("button", { name: "Delete" });
    expect(confirm).toHaveFocus();

    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it("keeps Tab focus inside the dialog", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Delete book" }));
    const dialog = screen.getByRole("dialog");
    const cancel = screen.getByRole("button", { name: "Cancel" });
    const confirm = screen.getByRole("button", { name: "Delete" });

    fireEvent.keyDown(dialog, { key: "Tab" });
    expect(cancel).toHaveFocus();

    fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true });
    expect(confirm).toHaveFocus();
  });

  it("ignores Escape while the action is pending", () => {
    const onCancel = vi.fn();
    render(
      <ConfirmActionDialog
        open
        title="Delete this book?"
        confirmLabel="Delete"
        isPending
        onConfirm={() => {}}
        onCancel={onCancel}
      >
        <p>Working</p>
      </ConfirmActionDialog>,
    );

    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });

    expect(onCancel).not.toHaveBeenCalled();
  });
});
