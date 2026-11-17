import { createGuardedReload } from "./pageReload";

// Signals that the server, or an auth proxy in front of it, refused an API
// request because the sign-in is missing or expired. The API client reports
// every such response here; App decides what to do about it.
//
// - "unauthorized": a 401. With app password auth this is our own session and
//   App shows the sign-in page. Otherwise (auth disabled behind a proxy) it
//   came from the proxy.
// - "redirected": the request was redirected. The API never redirects, so this
//   is a forward-auth proxy (Authentik, Authelia, Cloudflare Access, ...)
//   sending an expired session to its login page, whatever the app auth mode.
//
// A proxy can only run its sign-in flow on a top-level navigation, so for
// proxy sign-ins App reloads the page.
export type UnauthorizedReason = "unauthorized" | "redirected";
type Listener = (reason: UnauthorizedReason) => void;

const listeners = new Set<Listener>();

export function reportUnauthorized(reason: UnauthorizedReason): void {
  listeners.forEach((listener) => listener(reason));
}

export function onUnauthorized(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

// The proxy's sign-in can take a while (the user may have to type a password
// at the identity provider), but a page that is refused again within this
// window was not fixed by reloading, so it is not reloaded again.
const signInReload = createGuardedReload({
  storageKey: "story-manager:sign-in-reload",
  urlParam: "sign-in-reload",
  windowMs: 30_000,
});

export const consumeSignInReloadMarker = signInReload.consumeMarker;
export const reloadForSignIn = signInReload.reload;
