import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { components } from "../../api/schema";
import { jsonResponse, mockFetch, renderWithClient } from "../../test-utils";
import NotificationsPanel from "./NotificationsPanel";

type Webhook = components["schemas"]["NotificationWebhook"];

const webhook = (overrides: Partial<Webhook> = {}): Webhook => ({
  id: 1,
  name: "Phone",
  url_preview: "https://ntfy.sh/…",
  format: "ntfy",
  events: ["new_chapters", "job_failed"],
  enabled: true,
  created_at: "2026-11-01T00:00:00Z",
  last_delivery_at: null,
  last_delivery_status: null,
  last_delivery_error: null,
  ...overrides,
});

describe("NotificationsPanel", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.stubGlobal(
      "confirm",
      vi.fn(() => true),
    );
  });

  it("adds a webhook with the chosen service and events", async () => {
    let stored: Webhook[] = [];
    const fetchMock = mockFetch((url, options) => {
      if (url === "/api/notifications/webhooks" && options?.method === "POST") {
        stored = [webhook({ name: "Phone" })];
        return Promise.resolve(jsonResponse(stored[0], 201));
      }
      return Promise.resolve(jsonResponse(stored));
    });
    renderWithClient(<NotificationsPanel />);
    expect(await screen.findByText("No webhooks yet.")).toBeInTheDocument();
    const add = screen.getByRole("button", { name: "Add webhook" });
    expect(add).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: " Phone " },
    });
    fireEvent.change(screen.getByLabelText("Webhook URL"), {
      target: { value: "https://ntfy.sh/secret-topic" },
    });
    fireEvent.click(screen.getByLabelText("Audiobook finished"));
    fireEvent.click(add);

    expect(await screen.findByText("Added Phone.")).toBeInTheDocument();
    const post = fetchMock.mock.calls.find(
      ([, options]) => options?.method === "POST",
    );
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({
      name: "Phone",
      url: "https://ntfy.sh/secret-topic",
      format: "ntfy",
      events: ["new_chapters", "job_failed", "series_update"],
      enabled: true,
    });
    expect(
      await screen.findByText(/ntfy · https:\/\/ntfy\.sh\/…/),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Webhook URL")).toHaveValue("");
  });

  it("reports test results, pauses and deletes a webhook", async () => {
    const requests: string[] = [];
    mockFetch((url, options) => {
      const method = options?.method || "GET";
      if (method !== "GET")
        requests.push(`${method} ${url} ${String(options?.body ?? "")}`);
      if (url.endsWith("/test"))
        return Promise.resolve(jsonResponse({ ok: false, error: "HTTP 404" }));
      if (method === "PATCH")
        return Promise.resolve(jsonResponse(webhook({ enabled: false })));
      if (method === "DELETE")
        return Promise.resolve({
          ok: true,
          status: 204,
          json: () => Promise.resolve(null),
        });
      return Promise.resolve(
        jsonResponse([
          webhook({
            last_delivery_at: "2026-11-02T00:00:00Z",
            last_delivery_status: "error",
            last_delivery_error: "HTTP 500",
          }),
        ]),
      );
    });
    renderWithClient(<NotificationsPanel />);

    expect(
      await screen.findByText(/Last delivery failed .*HTTP 500/),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Send test to Phone" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Test to Phone failed: HTTP 404",
    );
    fireEvent.click(screen.getByRole("button", { name: "Pause Phone" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete Phone" }));
    await waitFor(() =>
      expect(requests).toEqual([
        "POST /api/notifications/webhooks/1/test ",
        'PATCH /api/notifications/webhooks/1 {"enabled":false}',
        "DELETE /api/notifications/webhooks/1 ",
      ]),
    );
  });
});
