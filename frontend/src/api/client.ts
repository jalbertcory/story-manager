import createClient from "openapi-fetch";
import type { Middleware } from "openapi-fetch";
import { reportUnauthorized } from "../lib/authSession";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type Body<
  Path extends keyof paths,
  Method extends keyof paths[Path],
> = paths[Path][Method] extends { requestBody?: infer Request }
  ? NonNullable<Request> extends { content: infer Content }
    ? Content[keyof Content]
    : never
  : never;
export type Query<Path extends keyof paths> = paths[Path] extends {
  get: { parameters: { query?: infer Q } };
}
  ? NonNullable<Q>
  : never;
type PathParams<Path extends keyof paths> = {
  [Method in keyof paths[Path]]: paths[Path][Method] extends {
    parameters: { path: infer Params };
  }
    ? Params
    : never;
}[keyof paths[Path]];

export function apiUrl<Path extends keyof paths>(
  path: Path,
  params: PathParams<Path> & object,
): string {
  let result: string = path;
  for (const [key, value] of Object.entries(params))
    result = result.replace(`{${key}}`, encodeURIComponent(String(value)));
  return result;
}

// Resolve relative URLs in the browser and defer fetch lookup so test mocks and
// session credentials continue to work after this module has been imported.
export const api = createClient<paths>({
  baseUrl:
    typeof window === "undefined" ? "http://localhost" : window.location.origin,
  fetch: (request) => globalThis.fetch(request),
  // The API never redirects. A forward-auth proxy whose session expired does,
  // to its login page on another origin, and a followed redirect would fail
  // as an indistinguishable network error. Stop at the redirect instead so
  // signInMiddleware can recognize it.
  redirect: "manual",
});

const REDIRECT_STATUSES = new Set([301, 302, 303, 307, 308]);
export const SIGN_IN_EXPIRED_MESSAGE =
  "Your sign-in expired. Reload the page to sign in again.";

// Reports refused sign-ins for every API call, whether or not it runs through
// React Query, and turns a redirect into a plain 401 so callers see one kind
// of failure: not retried, with a message that says what happened.
export const signInMiddleware: Middleware = {
  onResponse({ response, schemaPath }) {
    if (
      response.type === "opaqueredirect" ||
      REDIRECT_STATUSES.has(response.status)
    ) {
      reportUnauthorized("redirected");
      return new Response(JSON.stringify({ detail: SIGN_IN_EXPIRED_MESSAGE }), {
        status: 401,
        statusText: "Unauthorized",
        headers: { "Content-Type": "application/json" },
      });
    }
    // A wrong password at sign-in is a 401 too, but not a lost session.
    if (response.status === 401 && schemaPath !== "/api/auth/login")
      reportUnauthorized("unauthorized");
    return undefined;
  },
};
api.use(signInMiddleware);

export type RequestOptions = { signal?: AbortSignal | undefined };

// Request init carrying only the options openapi-fetch should forward. Query
// functions pass their context here, so cancelled queries abort the fetch.
export function requestInit({ signal }: RequestOptions = {}): {
  signal?: AbortSignal;
} {
  return signal ? { signal } : {};
}

type Result<T> = { data?: T; error?: unknown; response: Response };

// A failed API response. The HTTP status lets global handlers tell an expired
// session (401) or a bad request (4xx) apart from transient server failures.
export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function isApiError(error: unknown, status?: number): error is ApiError {
  return (
    error instanceof ApiError &&
    (status === undefined || error.status === status)
  );
}

function requestError(
  error: unknown,
  fallbackMessage: string,
  status: number,
): ApiError {
  return new ApiError(errorDetail(error, fallbackMessage), status);
}

function errorDetail(error: unknown, fallbackMessage: string): string {
  if (error && typeof error === "object" && "detail" in error) {
    if (typeof error.detail === "string") return error.detail;
    if (Array.isArray(error.detail)) {
      const messages = error.detail.map((item: unknown) =>
        item &&
        typeof item === "object" &&
        "msg" in item &&
        typeof item.msg === "string"
          ? item.msg
          : "Invalid request",
      );
      return messages.join("; ");
    }
  }
  return fallbackMessage;
}

export async function unwrap<T>(
  request: Promise<Result<T>>,
  fallbackMessage = "Request failed",
): Promise<T> {
  const result = await request;
  if (!result.response.ok)
    throw requestError(result.error, fallbackMessage, result.response.status);
  if (result.data === undefined)
    throw new Error("The server returned an empty response.");
  return result.data;
}

export async function unwrapOptional<T>(
  request: Promise<Result<T>>,
): Promise<T | null> {
  const result = await request;
  return result.response.ok ? (result.data ?? null) : null;
}

// Like unwrap, but a 404 resolves to null. Any other failure (a 5xx while the
// server restarts, an expired session) still throws, so callers can keep their
// last good data and retry instead of treating the resource as gone.
export async function unwrapUnlessNotFound<T>(
  request: Promise<Result<T>>,
  fallbackMessage = "Request failed",
): Promise<T | null> {
  const result = await request;
  if (result.response.status === 404) return null;
  return unwrap(Promise.resolve(result), fallbackMessage);
}

export async function unwrapEmpty(
  request: Promise<Result<unknown>>,
  fallbackMessage = "Request failed",
): Promise<null> {
  const result = await request;
  if (!result.response.ok)
    throw requestError(result.error, fallbackMessage, result.response.status);
  return null;
}

export function multipart(body: object | undefined): FormData {
  const form = new FormData();
  const append = (key: string, value: unknown): void => {
    if (value == null) return;
    if (Array.isArray(value)) {
      value.forEach((entry: unknown) => append(key, entry));
    } else if (value instanceof Blob) {
      form.append(key, value);
    } else if (
      typeof value === "string" ||
      typeof value === "number" ||
      typeof value === "boolean"
    ) {
      form.append(key, String(value));
    } else {
      throw new Error(`Unsupported multipart field: ${key}`);
    }
  };
  for (const [key, value] of Object.entries(body ?? {})) append(key, value);
  return form;
}
