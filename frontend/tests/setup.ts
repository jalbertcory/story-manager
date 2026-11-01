import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import type * as OpenApiFetch from "openapi-fetch";

import type { FixtureResponse } from "../src/test-utils";

// Existing component fixtures mock the browser's URL/init fetch overload.
// Keep exercising the real OpenAPI client's path, query and body serializers,
// then adapt its Request transport only at this test boundary. API transport
// tests unmock this module and inspect real Requests and Responses directly.
vi.mock("openapi-fetch", async (importOriginal) => {
  const original = await importOriginal<typeof OpenApiFetch>();
  type RequestArgs = ConstructorParameters<typeof Request>;
  class FixtureRequest extends Request {
    fixtureBody: NonNullable<RequestArgs[1]>["body"];
    constructor(...[input, init]: RequestArgs) {
      super(input, init);
      this.fixtureBody = init?.body;
    }
  }
  const createClient: typeof original.default = (options) =>
    original.default({
      ...options,
      Request: FixtureRequest,
      fetch: async (request) => {
        const url = new URL(request.url);
        const fixture: FixtureResponse = await globalThis.fetch(
          url.pathname + url.search,
          {
            method: request.method,
            headers: Object.fromEntries(request.headers),
            body: (request as FixtureRequest).fixtureBody ?? null,
            credentials: request.credentials,
            signal: request.signal,
          },
        );
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
    });
  return { ...original, default: createClient };
});

afterEach(() => {
  cleanup();
});

// jsdom does not implement IntersectionObserver; provide a no-op stub
globalThis.IntersectionObserver = class {
  readonly root = null;
  readonly rootMargin = "";
  readonly thresholds = [];
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return [];
  }
};
