// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.unmock("openapi-fetch");

import { apiUrl, isApiError, SIGN_IN_EXPIRED_MESSAGE } from "./client";
import { login } from "./auth";
import { deleteBook, getBook, getBookCatalog, updateBook } from "./books";
import { uploadEpubs } from "./imports";
import { onUnauthorized } from "../lib/authSession";
import type { UnauthorizedReason } from "../lib/authSession";

afterEach(() => vi.unstubAllGlobals());

describe("OpenAPI HTTP transport", () => {
  it("serializes the declared URL parameters and JSON body", async () => {
    let sent: Request | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (request: Request) => {
        sent = request;
        return Response.json({ id: 12, title: "Typed" });
      }),
    );

    await updateBook(12, { title: "Typed" });

    expect(sent).toBeInstanceOf(Request);
    expect(sent?.url).toBe("http://localhost/api/books/12");
    expect(sent?.method).toBe("PUT");
    expect(sent?.headers.get("content-type")).toBe("application/json");
    expect(await sent?.json()).toEqual({ title: "Typed" });
    expect(
      apiUrl("/api/series/{series_name}/reorder", { series_name: "A/B & C" }),
    ).toBe("/api/series/A%2FB%20%26%20C/reorder");
  });

  it("serializes query values without turning punctuation into query parameters", async () => {
    let sent: Request | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (request: Request) => {
        sent = request;
        return Response.json({
          items: [],
          next_cursor: null,
          total_count: 0,
          facets: {},
        });
      }),
    );

    await getBookCatalog({
      q: "a & b",
      universe: 0,
      sortBy: "updated_at",
      sortOrder: "desc",
    });
    const url = new URL(sent!.url);
    expect(url.searchParams.get("q")).toBe("a & b");
    expect(url.searchParams.get("universe")).toBe("0");
    expect(url.searchParams.get("sort_by")).toBe("updated_at");
    expect(url.searchParams.get("sort_order")).toBe("desc");
  });

  it("omits absent optional catalog filters from the request", async () => {
    let sent: Request | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (request: Request) => {
        sent = request;
        return Response.json({
          items: [],
          next_cursor: null,
          total_count: 0,
          facets: {},
        });
      }),
    );
    await getBookCatalog({
      series: null,
      universe: null,
      source: "",
      review: "",
    });
    const url = new URL(sent!.url);
    for (const name of [
      "series",
      "universe",
      "source",
      "review",
      "audiobook",
      "genre",
      "cursor",
    ]) {
      expect(url.searchParams.has(name)).toBe(false);
    }
  });

  it("sends real multipart files with browser-generated boundaries", async () => {
    let sent: Request | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (request: Request) => {
        sent = request;
        return Response.json([]);
      }),
    );

    await uploadEpubs([new File(["epub bytes"], "sample.epub")]);

    expect(sent?.headers.get("content-type")).toMatch(
      /^multipart\/form-data; boundary=/,
    );
    const form = await sent?.formData();
    const file = form?.get("files");
    expect(file).toBeInstanceOf(File);
    expect((file as File).name).toBe("sample.epub");
    expect(await (file as File).text()).toBe("epub bytes");
  });

  it("handles no-content responses and optional missing resources", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(new Response(null, { status: 204 }))
        .mockResolvedValueOnce(
          Response.json({ detail: "Book not found" }, { status: 404 }),
        ),
    );

    await expect(deleteBook(12)).resolves.toBeNull();
    await expect(getBook(12)).resolves.toBeNull();
  });

  it("surfaces book load failures other than not-found", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json({ detail: "Bad gateway" }, { status: 502 }),
      ),
    );

    await expect(getBook(12)).rejects.toThrow("Bad gateway");
  });

  it("reports structured API validation errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json({ detail: [{ msg: "Invalid title" }] }, { status: 422 }),
      ),
    );
    await expect(updateBook(12, { title: "" })).rejects.toThrow(
      "Invalid title",
    );
  });
});

describe("refused sign-ins", () => {
  let reasons: UnauthorizedReason[] = [];
  let stopListening = () => {};
  beforeEach(() => {
    reasons = [];
    stopListening = onUnauthorized((reason) => reasons.push(reason));
  });
  afterEach(() => stopListening());

  function loginRedirect() {
    return new Response(null, {
      status: 302,
      headers: { Location: "https://auth.example.com/login" },
    });
  }

  it("stops at an auth proxy's login redirect and reports it as a 401", async () => {
    let sent: Request | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (request: Request) => {
        sent = request;
        return loginRedirect();
      }),
    );

    const error: unknown = await getBook(12).catch((caught: unknown) => caught);

    expect(sent?.redirect).toBe("manual");
    expect(isApiError(error, 401)).toBe(true);
    expect(error).toHaveProperty("message", SIGN_IN_EXPIRED_MESSAGE);
    expect(reasons).toEqual(["redirected"]);
  });

  it("recognizes the opaque response browsers give for a manual redirect", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        // Browsers hide the redirect: no status, no headers, no body.
        const response = new Response(null, { status: 200 });
        Object.defineProperty(response, "type", { value: "opaqueredirect" });
        Object.defineProperty(response, "status", { value: 0 });
        Object.defineProperty(response, "ok", { value: false });
        return response;
      }),
    );

    await expect(getBook(12)).rejects.toThrow(SIGN_IN_EXPIRED_MESSAGE);
    expect(reasons).toEqual(["redirected"]);
  });

  it("reports an expired session but not a mistyped password", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (request: Request) =>
        Response.json(
          {
            detail: request.url.endsWith("/api/auth/login")
              ? "Invalid password"
              : "Admin authentication required",
          },
          { status: 401 },
        ),
      ),
    );

    await expect(login("wrong")).rejects.toThrow("Invalid password");
    expect(reasons).toEqual([]);

    await expect(getBook(12)).rejects.toThrow("Admin authentication required");
    expect(reasons).toEqual(["unauthorized"]);
  });
});
