// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

vi.unmock("openapi-fetch");

import { apiUrl } from "./client";
import { deleteBook, getBook, getBookCatalog, updateBook } from "./books";
import { uploadEpubs } from "./imports";

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
