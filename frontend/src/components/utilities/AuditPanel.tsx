import { useMutation } from "@tanstack/react-query";
import { validateLibrary as runLibraryValidation } from "../../api/admin";

function formatAuditIssue(issue: { issue: string }) {
  switch (issue.issue) {
    case "pending_web_import":
      return "pending web import";
    case "failed_web_import":
      return "failed web import";
    default:
      return issue.issue.replace(/_/g, " ");
  }
}

export default function AuditPanel() {
  const validateMutation = useMutation({
    mutationFn: runLibraryValidation,
  });
  const validationResult = validateMutation.data;

  return (
    <section className="settings-section">
      <p className="hint">Find missing EPUB files and covers.</p>
      <div className="settings-actions">
        <button
          onClick={() => validateMutation.mutate()}
          disabled={validateMutation.isPending}
        >
          {validateMutation.isPending ? "Auditing..." : "Run Library Audit"}
        </button>
        {validationResult && (
          <button className="btn-text" onClick={() => validateMutation.reset()}>
            Reset
          </button>
        )}
      </div>
      {validateMutation.isError && (
        <p className="error" role="alert" style={{ marginTop: "0.5rem" }}>
          {validateMutation.error?.message}
        </p>
      )}
      {validationResult && (
        <div style={{ marginTop: "1rem" }}>
          <h4>
            {validationResult.issues_count === 0
              ? "No Issues Found"
              : "Issues Found"}
            <span
              className="hint"
              style={{ fontWeight: "normal", marginLeft: "0.5rem" }}
            >
              {validationResult.total_books} book
              {validationResult.total_books !== 1 ? "s" : ""} checked,{" "}
              {validationResult.issues_count} issue
              {validationResult.issues_count !== 1 ? "s" : ""}
            </span>
          </h4>
          {validationResult.issues_count === 0 ? (
            <p className="hint">
              All books have valid file paths. Library is healthy.
            </p>
          ) : (
            <ul
              style={{
                listStyle: "none",
                padding: 0,
                margin: 0,
                display: "flex",
                flexDirection: "column",
                gap: "0.35rem",
              }}
            >
              {validationResult.issues.map((issue, i) => (
                <li
                  key={i}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "baseline",
                    fontSize: "0.85rem",
                    padding: "0.4rem 0.6rem",
                    borderRadius: "4px",
                    background: "var(--surface, #1a1a2e)",
                    gap: "1rem",
                  }}
                >
                  <span style={{ wordBreak: "break-word" }}>
                    <strong>{issue.title}</strong>
                    {issue.author && (
                      <span className="hint"> by {issue.author}</span>
                    )}
                  </span>
                  <span
                    style={{
                      flexShrink: 0,
                      color: "#f87171",
                      fontFamily: "monospace",
                      fontSize: "0.8rem",
                    }}
                  >
                    {formatAuditIssue(issue)}
                    {issue.path && (
                      <span className="hint" style={{ marginLeft: "0.5rem" }}>
                        {issue.path}
                      </span>
                    )}
                    {!issue.path && issue.source_url && (
                      <span className="hint" style={{ marginLeft: "0.5rem" }}>
                        {issue.source_url}
                      </span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
