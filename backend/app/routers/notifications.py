"""Admin endpoints for outbound notification webhooks."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, models, schemas
from ..database import get_db
from ..services.notifications import (
    WebhookDeliveryError,
    deliver_to_webhook,
    validate_webhook_url,
    webhook_url_preview,
)

router = APIRouter()


def _response(webhook: models.NotificationWebhook) -> schemas.NotificationWebhook:
    return schemas.NotificationWebhook.model_validate(
        {
            "id": webhook.id,
            "name": webhook.name,
            "url_preview": webhook_url_preview(webhook.url),
            "format": webhook.format,
            "events": list(webhook.events or []),
            "enabled": webhook.enabled,
            "created_at": webhook.created_at,
            "last_delivery_at": webhook.last_delivery_at,
            "last_delivery_status": webhook.last_delivery_status,
            "last_delivery_error": webhook.last_delivery_error,
        }
    )


def _checked_url(url: str) -> str:
    try:
        return validate_webhook_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _required_webhook(db: AsyncSession, webhook_id: int) -> models.NotificationWebhook:
    webhook = await crud.get_notification_webhook(db, webhook_id)
    if webhook is None:
        raise HTTPException(status_code=404, detail="Notification webhook not found")
    return webhook


@router.get("/api/notifications/webhooks", response_model=list[schemas.NotificationWebhook])
async def list_notification_webhooks(db: AsyncSession = Depends(get_db)) -> list[schemas.NotificationWebhook]:
    return [_response(webhook) for webhook in await crud.get_notification_webhooks(db)]


@router.post(
    "/api/notifications/webhooks",
    response_model=schemas.NotificationWebhook,
    status_code=status.HTTP_201_CREATED,
)
async def create_notification_webhook(
    request: schemas.NotificationWebhookCreate,
    db: AsyncSession = Depends(get_db),
) -> schemas.NotificationWebhook:
    webhook = await crud.create_notification_webhook(
        db,
        name=request.name.strip(),
        url=_checked_url(request.url),
        format=request.format,
        events=list(dict.fromkeys(request.events)),
        enabled=request.enabled,
    )
    return _response(webhook)


@router.patch("/api/notifications/webhooks/{webhook_id}", response_model=schemas.NotificationWebhook)
async def update_notification_webhook(
    webhook_id: int,
    request: schemas.NotificationWebhookUpdate,
    db: AsyncSession = Depends(get_db),
) -> schemas.NotificationWebhook:
    webhook = await _required_webhook(db, webhook_id)
    updated = await crud.update_notification_webhook(
        db,
        webhook,
        name=request.name.strip() if request.name is not None else None,
        url=_checked_url(request.url) if request.url is not None else None,
        format=request.format,
        events=list(dict.fromkeys(request.events)) if request.events is not None else None,
        enabled=request.enabled,
    )
    return _response(updated)


@router.delete("/api/notifications/webhooks/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification_webhook(webhook_id: int, db: AsyncSession = Depends(get_db)) -> None:
    if not await crud.delete_notification_webhook(db, webhook_id):
        raise HTTPException(status_code=404, detail="Notification webhook not found")
    return None


@router.post("/api/notifications/webhooks/{webhook_id}/test", response_model=schemas.NotificationTestResult)
async def test_notification_webhook(
    webhook_id: int,
    db: AsyncSession = Depends(get_db),
) -> schemas.NotificationTestResult:
    """Send a test message now and report whether the receiver accepted it."""
    webhook = await _required_webhook(db, webhook_id)
    try:
        await deliver_to_webhook(
            webhook.id,
            event="test",
            title="Story Manager test notification",
            message=f"Webhook “{webhook.name}” is set up correctly.",
            require_subscription=False,
        )
    except WebhookDeliveryError as exc:
        return schemas.NotificationTestResult(ok=False, error=str(exc))
    return schemas.NotificationTestResult(ok=True, error=None)
