import { IMPORT_TYPES } from "./importTypes";

export function ImportHeader({
  stage,
  directImport = false,
}: {
  stage: number;
  directImport?: boolean;
}) {
  const steps = directImport
    ? ["Select", "Results"]
    : ["Select", "Review", "Results"];
  return (
    <header className="import-workflow-header">
      <h2>Add to library</h2>
      <ol className="import-steps" aria-label="Import progress">
        {steps.map((label, index) => (
          <li
            key={label}
            className={stage >= index + 1 ? "import-steps--active" : ""}
            aria-current={stage === index + 1 ? "step" : undefined}
          >
            <span>{index + 1}</span>
            {label}
          </li>
        ))}
      </ol>
    </header>
  );
}

export function ImportTypePicker({
  selected,
  onSelect,
  disabled = false,
}: {
  selected: string;
  onSelect: (type: string) => void;
  disabled?: boolean;
}) {
  return (
    <div
      className="import-type-picker"
      role="group"
      aria-label="Import source type"
    >
      {IMPORT_TYPES.map((item) => (
        <button
          key={item.key}
          type="button"
          className={selected === item.key ? "import-type--active" : ""}
          disabled={disabled}
          aria-pressed={selected === item.key}
          onClick={() => onSelect(item.key)}
        >
          <strong>{item.label}</strong>
          <span>{item.description}</span>
        </button>
      ))}
    </div>
  );
}

export function SelectedFiles({
  files,
  onRemove,
}: {
  files: File[];
  onRemove?: (index: number) => void;
}) {
  if (!files.length) return null;
  return (
    <ul className="import-selected-files">
      {files.map((file, index) => (
        <li key={`${file.name}-${index}`}>
          <span>{file.webkitRelativePath || file.name}</span>
          {onRemove && (
            <button
              type="button"
              className="btn-text"
              aria-label={`Remove ${file.name}`}
              onClick={() => onRemove(index)}
            >
              Remove
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}
