import createClient from "openapi-fetch";
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
});

type Result<T> = { data?: T; error?: unknown; response: Response };

function requestError(error: unknown, fallbackMessage: string): Error {
  if (error && typeof error === "object" && "detail" in error) {
    if (typeof error.detail === "string") return new Error(error.detail);
    if (Array.isArray(error.detail)) {
      const messages = error.detail.map((item: unknown) =>
        item &&
        typeof item === "object" &&
        "msg" in item &&
        typeof item.msg === "string"
          ? item.msg
          : "Invalid request",
      );
      return new Error(messages.join("; "));
    }
  }
  return new Error(fallbackMessage);
}

export async function unwrap<T>(
  request: Promise<Result<T>>,
  fallbackMessage = "Request failed",
): Promise<T> {
  const result = await request;
  if (!result.response.ok) throw requestError(result.error, fallbackMessage);
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

export async function unwrapEmpty(
  request: Promise<Result<unknown>>,
  fallbackMessage = "Request failed",
): Promise<null> {
  const result = await request;
  if (!result.response.ok) throw requestError(result.error, fallbackMessage);
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
