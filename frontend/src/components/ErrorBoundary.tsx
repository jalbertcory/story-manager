import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";
import { postClientLog } from "../api/admin";

type Props = { children: ReactNode };
type State = { error: Error | null };

// Keeps a render error in one page from blanking the whole app. App keys this
// on the location, so navigating elsewhere clears the error.
export default class ErrorBoundary extends Component<Props, State> {
  override state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    void postClientLog(
      `Render error: ${error.message}\n${error.stack || ""}`,
      info.componentStack || undefined,
    ).catch(() => {});
  }

  override render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="page-error" role="alert">
        <h2>Something went wrong</h2>
        <p>This page could not be displayed: {error.message}</p>
        <button type="button" onClick={() => window.location.reload()}>
          Reload
        </button>
      </div>
    );
  }
}
