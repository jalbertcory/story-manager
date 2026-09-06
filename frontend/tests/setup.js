import { expect, afterEach, vi } from "vitest";
import * as matchers from "@testing-library/jest-dom/matchers";
import { cleanup } from "@testing-library/react";

// Existing component fixtures mock the browser's URL/init fetch overload.
// Keep exercising the real OpenAPI client's path, query and body serializers,
// then adapt its Request transport only at this test boundary. API transport
// tests unmock this module and inspect real Requests and Responses directly.
vi.mock("openapi-fetch", async (importOriginal) => {
  const original = await importOriginal();
  class FixtureRequest extends Request {
    constructor(input, init) {
      super(input, init);
      this.fixtureBody = init?.body;
    }
  }
  return {
    ...original,
    default: (options) =>
      original.default({
        ...options,
        Request: FixtureRequest,
        fetch: async (request) => {
          const url = new URL(request.url);
          const fixture = await globalThis.fetch(url.pathname + url.search, {
            method: request.method,
            headers: Object.fromEntries(request.headers),
            body: request.fixtureBody,
            credentials: request.credentials,
            signal: request.signal,
          });
          if (fixture instanceof Response) return fixture;
          const status = fixture.status ?? (fixture.ok === false ? 500 : 200);
          return new Response(
            status === 204 ? null : JSON.stringify(await fixture.json()),
            {
              status,
              headers: { "Content-Type": "application/json" },
            },
          );
        },
      }),
  };
});

expect.extend(matchers);

afterEach(() => {
  cleanup();
});

// jsdom does not implement IntersectionObserver; provide a no-op stub
globalThis.IntersectionObserver = class IntersectionObserver {
  constructor() {}
  observe() {}
  unobserve() {}
  disconnect() {}
};
