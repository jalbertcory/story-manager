// Signals that the server rejected a request because the admin session is
// missing or expired. The query client reports every 401 here; App decides
// whether that means showing the sign-in page (it never does when the server
// runs with app auth disabled).
type Listener = () => void;

const listeners = new Set<Listener>();

export function reportUnauthorized(): void {
  listeners.forEach((listener) => listener());
}

export function onUnauthorized(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
