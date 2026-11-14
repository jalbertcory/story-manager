"""Notification webhook CRUD operations."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models


async def get_notification_webhooks(db: AsyncSession) -> list[models.NotificationWebhook]:
    result = await db.execute(select(models.NotificationWebhook).order_by(models.NotificationWebhook.id))
    return list(result.scalars().all())


async def get_notification_webhook(db: AsyncSession, webhook_id: int) -> models.NotificationWebhook | None:
    return await db.get(models.NotificationWebhook, webhook_id)


async def get_webhooks_for_event(db: AsyncSession, event: str) -> list[models.NotificationWebhook]:
    result = await db.execute(
        select(models.NotificationWebhook)
        .where(models.NotificationWebhook.enabled.is_(True))
        .order_by(models.NotificationWebhook.id)
    )
    # The events list is JSON; filter in Python so SQLite and PostgreSQL agree.
    return [webhook for webhook in result.scalars().all() if event in (webhook.events or [])]


async def create_notification_webhook(
    db: AsyncSession,
    *,
    name: str,
    url: str,
    format: str,
    events: list[str],
    enabled: bool,
) -> models.NotificationWebhook:
    webhook = models.NotificationWebhook(name=name, url=url, format=format, events=events, enabled=enabled)
    db.add(webhook)
    await db.commit()
    await db.refresh(webhook)
    return webhook


async def update_notification_webhook(
    db: AsyncSession,
    webhook: models.NotificationWebhook,
    *,
    name: str | None = None,
    url: str | None = None,
    format: str | None = None,
    events: list[str] | None = None,
    enabled: bool | None = None,
) -> models.NotificationWebhook:
    if name is not None:
        webhook.name = name
    if url is not None:
        webhook.url = url
    if format is not None:
        webhook.format = format
    if events is not None:
        webhook.events = events
    if enabled is not None:
        webhook.enabled = enabled
    await db.commit()
    await db.refresh(webhook)
    return webhook


async def delete_notification_webhook(db: AsyncSession, webhook_id: int) -> bool:
    webhook = await db.get(models.NotificationWebhook, webhook_id)
    if webhook is None:
        return False
    await db.delete(webhook)
    await db.commit()
    return True


async def record_webhook_delivery(db: AsyncSession, webhook_id: int, error: str | None) -> None:
    webhook = await db.get(models.NotificationWebhook, webhook_id)
    if webhook is None:
        return
    webhook.last_delivery_at = datetime.now(timezone.utc)
    webhook.last_delivery_status = "error" if error else "ok"
    webhook.last_delivery_error = error
    await db.commit()
