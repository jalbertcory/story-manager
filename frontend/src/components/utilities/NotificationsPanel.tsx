import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createNotificationWebhook,
  deleteNotificationWebhook,
  getNotificationWebhooks,
  setNotificationWebhookEnabled,
  testNotificationWebhook,
} from "../../api/notifications";
import type {
  NotificationEvent,
  NotificationWebhook,
  WebhookFormat,
} from "../../api/notifications";
import { errorMessage } from "../../lib/errors";
import { queryKeys } from "../../lib/queryKeys";

const EVENTS: { key: NotificationEvent; label: string }[] = [
  { key: "new_chapters", label: "New chapters found" },
  { key: "audiobook_finished", label: "Audiobook finished" },
  { key: "job_failed", label: "Background task failed" },
  { key: "series_update", label: "Series gaps and new releases" },
];
const FORMATS: { key: WebhookFormat; label: string }[] = [
  { key: "ntfy", label: "ntfy" },
  { key: "discord", label: "Discord" },
  { key: "slack", label: "Slack" },
  { key: "json", label: "Generic JSON" },
];
const ALL_EVENTS = EVENTS.map((event) => event.key);

function lastDelivery(webhook: NotificationWebhook) {
  if (!webhook.last_delivery_at) return "Nothing sent yet";
  const when = new Date(webhook.last_delivery_at).toLocaleString();
  return webhook.last_delivery_status === "ok"
    ? `Last delivered ${when}`
    : `Last delivery failed ${when}: ${webhook.last_delivery_error || "unknown error"}`;
}

function NotificationsPanel() {
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [format, setFormat] = useState<WebhookFormat>("ntfy");
  const [events, setEvents] = useState<NotificationEvent[]>(ALL_EVENTS);
  const [notice, setNotice] = useState<{ error: boolean; text: string }>();

  const webhooks = useQuery({
    queryKey: queryKeys.notificationWebhooks,
    queryFn: ({ signal }) => getNotificationWebhooks({ signal }),
  });
  const reload = () =>
    client.invalidateQueries({ queryKey: queryKeys.notificationWebhooks });
  const fail = (error: unknown) =>
    setNotice({ error: true, text: errorMessage(error) });

  const create = useMutation({
    mutationFn: createNotificationWebhook,
    onSuccess: (webhook) => {
      setName("");
      setUrl("");
      setNotice({ error: false, text: `Added ${webhook.name}.` });
      return reload();
    },
    onError: fail,
  });
  const toggle = useMutation({
    mutationFn: (webhook: NotificationWebhook) =>
      setNotificationWebhookEnabled(webhook.id, !webhook.enabled),
    onSuccess: reload,
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: (webhook: NotificationWebhook) =>
      deleteNotificationWebhook(webhook.id),
    onSuccess: (_result, webhook) => {
      setNotice({ error: false, text: `Deleted ${webhook.name}.` });
      return reload();
    },
    onError: fail,
  });
  const test = useMutation({
    mutationFn: (webhook: NotificationWebhook) =>
      testNotificationWebhook(webhook.id),
    onSuccess: (result, webhook) => {
      setNotice(
        result.ok
          ? { error: false, text: `Test sent to ${webhook.name}.` }
          : {
              error: true,
              text: `Test to ${webhook.name} failed: ${result.error || "unknown error"}`,
            },
      );
      return reload();
    },
    onError: fail,
  });

  const canSubmit =
    name.trim() !== "" && url.trim() !== "" && events.length > 0;
  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!canSubmit) return;
    setNotice(undefined);
    create.mutate({ name: name.trim(), url: url.trim(), format, events });
  };
  const toggleEvent = (key: NotificationEvent) =>
    setEvents((current) =>
      current.includes(key)
        ? current.filter((item) => item !== key)
        : ALL_EVENTS.filter((item) => item === key || current.includes(item)),
    );

  return (
    <section className="settings-section">
      <p className="hint">
        Story Manager posts a short message to each webhook when something
        happens. The address is stored as a secret: after saving, only its host
        is shown.
      </p>

      <form className="webhook-form" onSubmit={handleSubmit}>
        <label>
          Name
          <input
            type="text"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="e.g. Phone"
          />
        </label>
        <label>
          Service
          <select
            value={format}
            onChange={(event) => setFormat(event.target.value as WebhookFormat)}
          >
            {FORMATS.map((item) => (
              <option key={item.key} value={item.key}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label className="webhook-form-url">
          Webhook URL
          <input
            type="url"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://ntfy.sh/my-topic"
            autoComplete="off"
          />
        </label>
        <fieldset>
          <legend>Notify me about</legend>
          {EVENTS.map((item) => (
            <label key={item.key}>
              <input
                type="checkbox"
                checked={events.includes(item.key)}
                onChange={() => toggleEvent(item.key)}
              />
              {item.label}
            </label>
          ))}
        </fieldset>
        <button type="submit" disabled={!canSubmit || create.isPending}>
          {create.isPending ? "Adding…" : "Add webhook"}
        </button>
      </form>

      {notice && (
        <p
          className={notice.error ? "error" : "hint"}
          role={notice.error ? "alert" : "status"}
        >
          {notice.text}
        </p>
      )}
      {webhooks.error && (
        <p className="error" role="alert">
          {webhooks.error.message}
        </p>
      )}

      {webhooks.isLoading ? (
        <p className="hint">Loading webhooks…</p>
      ) : !webhooks.data?.length ? (
        <p className="hint">No webhooks yet.</p>
      ) : (
        <ul className="webhook-list">
          {webhooks.data.map((webhook) => (
            <li key={webhook.id} className={webhook.enabled ? "" : "is-paused"}>
              <div>
                <strong>{webhook.name}</strong>
                <div className="hint">
                  {FORMATS.find((item) => item.key === webhook.format)?.label} ·{" "}
                  {webhook.url_preview}
                  {!webhook.enabled && " · Paused"}
                </div>
                <div className="hint">
                  {EVENTS.filter((item) => webhook.events.includes(item.key))
                    .map((item) => item.label)
                    .join(", ")}
                </div>
                <div className="hint">{lastDelivery(webhook)}</div>
              </div>
              <div className="webhook-actions">
                <button
                  onClick={() => test.mutate(webhook)}
                  disabled={test.isPending}
                  aria-label={`Send test to ${webhook.name}`}
                >
                  Send test
                </button>
                <button
                  onClick={() => toggle.mutate(webhook)}
                  disabled={toggle.isPending}
                  aria-label={`${webhook.enabled ? "Pause" : "Resume"} ${webhook.name}`}
                >
                  {webhook.enabled ? "Pause" : "Resume"}
                </button>
                <button
                  className="btn-danger"
                  onClick={() => {
                    if (window.confirm(`Delete the webhook "${webhook.name}"?`))
                      remove.mutate(webhook);
                  }}
                  disabled={remove.isPending}
                  aria-label={`Delete ${webhook.name}`}
                >
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default NotificationsPanel;
