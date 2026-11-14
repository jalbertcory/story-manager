import { api, unwrap, unwrapEmpty, requestInit } from "./client";
import type { RequestOptions, Schemas } from "./client";

export type NotificationWebhook = Schemas["NotificationWebhook"];
export type NotificationEvent = NotificationWebhook["events"][number];
export type WebhookFormat = NotificationWebhook["format"];

export const getNotificationWebhooks = (options?: RequestOptions) =>
  unwrap(
    api.GET("/api/notifications/webhooks", requestInit(options)),
    "Failed to load notification webhooks",
  );
export const createNotificationWebhook = (body: {
  name: string;
  url: string;
  format: WebhookFormat;
  events: NotificationEvent[];
}) =>
  unwrap(
    api.POST("/api/notifications/webhooks", {
      body: { ...body, enabled: true },
    }),
    "Failed to add webhook",
  );
export const setNotificationWebhookEnabled = (id: number, enabled: boolean) =>
  unwrap(
    api.PATCH("/api/notifications/webhooks/{webhook_id}", {
      params: { path: { webhook_id: id } },
      body: { enabled },
    }),
    "Failed to update webhook",
  );
export const deleteNotificationWebhook = (id: number) =>
  unwrapEmpty(
    api.DELETE("/api/notifications/webhooks/{webhook_id}", {
      params: { path: { webhook_id: id } },
    }),
    "Failed to delete webhook",
  );
export const testNotificationWebhook = (id: number) =>
  unwrap(
    api.POST("/api/notifications/webhooks/{webhook_id}/test", {
      params: { path: { webhook_id: id } },
    }),
    "Failed to send test notification",
  );
