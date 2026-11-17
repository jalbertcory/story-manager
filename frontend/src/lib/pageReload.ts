export type ReloadLocation = Pick<Location, "href" | "reload" | "replace">;

export type GuardedReload = {
  // Call before the app reads the URL. A reload made without session storage
  // carries a marker in the query string; remember it and take it out of the
  // address bar so it is not bookmarked or shared.
  consumeMarker: () => void;
  // Reloads the page, unless this page load already used its reload or a
  // reload for the same reason happened within `windowMs` (reloading again
  // would loop forever). Returns whether a reload was started.
  reload: (location?: ReloadLocation) => boolean;
};

// A full page reload for one reason, allowed at most once per page load and
// once per `windowMs` across page loads.
export function createGuardedReload({
  storageKey,
  urlParam,
  windowMs,
}: {
  storageKey: string;
  urlParam: string;
  windowMs: number;
}): GuardedReload {
  // True once this page load has used its reload: either it started one, or
  // it is the result of one that marked the URL.
  let reloadSpent = false;

  return {
    consumeMarker() {
      const url = new URL(window.location.href);
      if (!url.searchParams.has(urlParam)) return;
      reloadSpent = true;
      url.searchParams.delete(urlParam);
      window.history.replaceState(
        window.history.state,
        "",
        `${url.pathname}${url.search}${url.hash}`,
      );
    },
    reload(location = window.location) {
      if (reloadSpent) return false;
      reloadSpent = true;
      const now = Date.now();
      try {
        const last = Number(window.sessionStorage.getItem(storageKey) || 0);
        if (now - last < windowMs) return false;
        window.sessionStorage.setItem(storageKey, String(now));
      } catch {
        // Session storage is unavailable (private mode or blocked site data),
        // so mark the reload in the URL instead; consumeMarker reads it.
        const url = new URL(location.href);
        url.searchParams.set(urlParam, "1");
        location.replace(url.href);
        return true;
      }
      location.reload();
      return true;
    },
  };
}
