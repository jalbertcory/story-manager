import { createContext, useContext, useSyncExternalStore } from "react";
import type { NavigationState } from "../types";

// The app owns the browser history: it decides when a location change is
// allowed (unsaved-work guards) and remembers scroll and return paths. Pages
// read the location and navigate through these hooks instead of touching
// window.history themselves.

export interface AppLocation {
  pathname: string;
  search: string;
  hash: string;
}

export type Navigate = (href: string, state?: NavigationState) => void;

export const RouterContext = createContext<{
  location: AppLocation;
  navigate: Navigate;
} | null>(null);

function subscribeToHistory(onChange: () => void) {
  window.addEventListener("popstate", onChange);
  return () => window.removeEventListener("popstate", onChange);
}

const windowHref = () => window.location.href;

// Outside App (a page rendered on its own, as in tests) pages follow the
// window's history directly.
function windowNavigate(href: string, state: NavigationState = {}) {
  window.history.pushState(state, "", href);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function useLocation(): AppLocation {
  const router = useContext(RouterContext);
  const href = useSyncExternalStore(subscribeToHistory, windowHref);
  if (router) return router.location;
  const { pathname, search, hash } = new URL(href);
  return { pathname, search, hash };
}

export function useNavigate(): Navigate {
  return useContext(RouterContext)?.navigate ?? windowNavigate;
}
