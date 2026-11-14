"""Outbound webhook notifications for library events.

Producers call :func:`emit_notification`; it queues one durable delivery job per
subscribed webhook, so a slow or unreachable receiver never blocks the work that
raised the event and failed deliveries are retried by the processing queue.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

import requests

from .. import crud, models
from ..database import SessionLocal
from ..job_payloads import DeliverNotificationPayload
from ..logging_config import redact_text

logger = logging.getLogger(__name__)

EVENT_NEW_CHAPTERS = "new_chapters"
EVENT_AUDIOBOOK_FINISHED = "audiobook_finished"
EVENT_JOB_FAILED = "job_failed"
EVENT_SERIES_UPDATE = "series_update"
NOTIFICATION_EVENTS: tuple[str, ...] = (
    EVENT_NEW_CHAPTERS,
    EVENT_AUDIOBOOK_FINISHED,
    EVENT_JOB_FAILED,
    EVENT_SERIES_UPDATE,
)
WEBHOOK_FORMATS: tuple[str, ...] = ("json", "ntfy", "discord", "slack")
DELIVERY_JOB_TYPE = "deliver_notification"
WEBHOOK_TARGET_TYPE = "notification_webhook"

_CONNECT_TIMEOUT_SECONDS = 5
_READ_TIMEOUT_SECONDS = 10
_USER_AGENT = "story-manager/0.1"
_DISCORD_CONTENT_LIMIT = 2000
_MESSAGE_LIMIT = 3500


class WebhookDeliveryError(RuntimeError):
    """A webhook could not be delivered; the message never contains the URL."""


@dataclass(frozen=True)
class WebhookRequest:
    headers: dict[str, str]
    json_body: dict[str, object] | None = None
    text_body: str | None = None


def validate_webhook_url(url: str) -> str:
    cleaned = url.strip()
    parts = urlsplit(cleaned)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("Webhook URL must be an http:// or https:// address.")
    try:
        parts.port
    except ValueError:
        raise ValueError("Webhook URL has an invalid port.") from None
    return cleaned


def webhook_url_preview(url: str) -> str:
    """Show where a webhook points without revealing the token in its path or query."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    try:
        port = parts.port
    except ValueError:  # never let one bad stored row break the whole list
        port = None
    if port:
        host = f"{host}:{port}"
    return f"{parts.scheme}://{host}/…"


def _header_value(value: str) -> str:
    """HTTP headers are Latin-1; ntfy accepts RFC 2047 for anything else."""
    single_line = " ".join(value.split())
    try:
        single_line.encode("ascii")
    except UnicodeEncodeError:
        encoded = base64.b64encode(single_line.encode("utf-8")).decode("ascii")
        return f"=?UTF-8?B?{encoded}?="
    return single_line


def build_webhook_request(webhook_format: str, *, event: str, title: str, message: str) -> WebhookRequest:
    message = message[:_MESSAGE_LIMIT]
    headers = {"User-Agent": _USER_AGENT}
    if webhook_format == "ntfy":
        headers["Title"] = _header_value(title)
        headers["Tags"] = event
        headers["Content-Type"] = "text/plain; charset=utf-8"
        return WebhookRequest(headers=headers, text_body=message or title)
    text = f"**{title}**\n{message}" if message else f"**{title}**"
    if webhook_format == "discord":
        return WebhookRequest(headers=headers, json_body={"content": text[:_DISCORD_CONTENT_LIMIT]})
    if webhook_format == "slack":
        slack_text = f"*{title}*\n{message}" if message else f"*{title}*"
        return WebhookRequest(headers=headers, json_body={"text": slack_text})
    if webhook_format == "json":
        return WebhookRequest(
            headers=headers,
            json_body={
                "event": event,
                "title": title,
                "message": message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
    raise ValueError(f"Unsupported webhook format: {webhook_format}")


def send_webhook(url: str, webhook_format: str, *, event: str, title: str, message: str) -> None:
    """POST one notification. Blocking; call through ``asyncio.to_thread``."""
    request = build_webhook_request(webhook_format, event=event, title=title, message=message)
    try:
        response = requests.post(
            validate_webhook_url(url),
            headers=request.headers,
            json=request.json_body,
            data=request.text_body.encode("utf-8") if request.text_body is not None else None,
            timeout=(_CONNECT_TIMEOUT_SECONDS, _READ_TIMEOUT_SECONDS),
            # A redirect could forward the notification to an unintended host.
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        # requests embeds the full URL (and so the token) in its messages.
        raise WebhookDeliveryError(f"Could not reach the webhook ({type(exc).__name__}).") from None
    if response.status_code >= 300:
        raise WebhookDeliveryError(f"The webhook responded with HTTP {response.status_code}.")


async def deliver_to_webhook(
    webhook_id: int, *, event: str, title: str, message: str, require_subscription: bool = True
) -> str:
    """Send one notification and record the outcome on the webhook.

    Queued deliveries re-check the subscription, so pausing a webhook or
    unsubscribing it from an event also stops deliveries already waiting.
    Test messages pass ``require_subscription=False``.
    """
    async with SessionLocal() as db:
        webhook = await crud.get_notification_webhook(db, webhook_id)
        if webhook is None:
            return "Webhook was deleted; nothing sent"
        if require_subscription and not webhook.enabled:
            return f"{webhook.name} is paused; nothing sent"
        if require_subscription and event not in (webhook.events or []):
            return f"{webhook.name} no longer subscribes to this event; nothing sent"
        url, webhook_format, name = webhook.url, webhook.format, webhook.name
    error: str | None = None
    try:
        await asyncio.to_thread(send_webhook, url, webhook_format, event=event, title=title, message=message)
    except (WebhookDeliveryError, ValueError) as exc:
        error = redact_text(str(exc))
    async with SessionLocal() as db:
        await crud.record_webhook_delivery(db, webhook_id, error)
    if error is not None:
        raise WebhookDeliveryError(error)
    return f"Notification sent to {name}"


async def emit_notification(event: str, title: str, message: str = "", *, book_id: int | None = None) -> int:
    """Queue ``event`` for every subscribed webhook. Never raises; returns jobs queued."""
    from .processing_queue import queue_processing_job

    try:
        async with SessionLocal() as db:
            webhooks: list[models.NotificationWebhook] = await crud.get_webhooks_for_event(db, event)
            for webhook in webhooks:
                await queue_processing_job(
                    db=db,
                    job_type=DELIVERY_JOB_TYPE,
                    book_id=book_id,
                    target_type=WEBHOOK_TARGET_TYPE,
                    target_id=webhook.id,
                    payload=DeliverNotificationPayload(event=event, title=title, message=message),
                    progress_detail=f"Queued for {webhook.name}",
                )
            return len(webhooks)
    except Exception:
        logger.exception("Could not queue %s notifications.", event)
        return 0
