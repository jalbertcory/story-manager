import { useRef, useState } from "react";
import type { DragEvent } from "react";

import { isBookFile } from "../../lib/importFiles";
import { SelectedFiles } from "./ImportLayout";

export default function BookFilesInput({
  files,
  onAddFiles,
  onAddEntries,
  onRemove,
}: {
  files: File[];
  onAddFiles: (files: File[]) => void;
  onAddEntries: (entries: FileSystemEntry[]) => Promise<void>;
  onRemove: (index: number) => void;
}) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const handleDrop = async (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    // App also listens for drops anywhere on the page; this one is handled.
    event.stopPropagation();
    setDragging(false);
    const entries = Array.from(event.dataTransfer.items)
      .map((item) => item.webkitGetAsEntry?.())
      .filter((entry): entry is FileSystemEntry => entry != null);
    if (entries.length) {
      await onAddEntries(entries);
      return;
    }
    onAddFiles(
      Array.from(event.dataTransfer.files).filter((file) =>
        isBookFile(file.name),
      ),
    );
  };

  return (
    <>
      <div
        id="drop-zone"
        className={`drop-zone import-drop-zone${dragging ? " dragging" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          void handleDrop(event);
        }}
        onClick={() => fileInputRef.current?.click()}
      >
        <strong>Drop EPUBs, ZIPs, or folders here</strong>
        <span>or click to browse for files</span>
        <input
          id="file-upload"
          ref={fileInputRef}
          type="file"
          accept=".epub,.zip"
          multiple
          hidden
          onChange={(event) => {
            onAddFiles(Array.from(event.target.files || []));
            event.target.value = "";
          }}
        />
      </div>
      <SelectedFiles files={files} onRemove={onRemove} />
    </>
  );
}
