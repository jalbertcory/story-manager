"""Durable measurements and summaries for routed AI endpoint attempts."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import SessionLocal
from ..endpoint_types import EndpointConfig, EndpointStats, EndpointSpeedBuckets
from ..models import AiEndpointRequestMetric, AudiobookSettings
from .endpoint_pool import configured_endpoints


async def record_attempt(
    settings_id: int,
    capability: str,
    endpoint: EndpointConfig,
    *,
    success: bool,
    duration_ms: float,
    error_type: str | None = None,
) -> None:
    """Commit one metric independently from the audiobook job transaction."""
    async with SessionLocal() as db:
        db.add(
            AiEndpointRequestMetric(
                settings_id=settings_id,
                capability=capability,
                endpoint_id=str(endpoint.id or "unknown"),
                endpoint_name=str(endpoint.name or "Unnamed endpoint"),
                provider=str(endpoint.provider or "unknown"),
                model=str(endpoint.model) if endpoint.model else None,
                success=success,
                duration_ms=max(0.0, duration_ms),
                error_type=error_type,
            )
        )
        await db.commit()


def _percentile(sorted_values: list[float], percentile: float) -> float | None:
    if not sorted_values:
        return None
    position = (len(sorted_values) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction


def _rounded(value: float | None) -> float | None:
    return round(value, 1) if value is not None else None


async def endpoint_summaries(
    db: AsyncSession,
    settings: AudiobookSettings | None,
    capability: str,
) -> list[EndpointStats]:
    """Return all-time and recent comparison metrics for configured endpoints."""
    endpoints = configured_endpoints(settings, capability) if settings is not None else []
    rows: list[AiEndpointRequestMetric] = []
    if settings is not None and settings.id is not None:
        rows = list(
            (
                await db.scalars(
                    select(AiEndpointRequestMetric)
                    .where(
                        AiEndpointRequestMetric.settings_id == settings.id,
                        AiEndpointRequestMetric.capability == capability,
                    )
                    .order_by(AiEndpointRequestMetric.created_at.asc())
                )
            ).all()
        )

    by_endpoint: dict[str, list[AiEndpointRequestMetric]] = defaultdict(list)
    for row in rows:
        by_endpoint[row.endpoint_id].append(row)

    now = datetime.now(timezone.utc)
    recent_cutoff = now - timedelta(hours=24)
    summaries: list[EndpointStats] = []
    for index, endpoint in enumerate(endpoints):
        endpoint_id = str(endpoint.id or f"{capability}-{index + 1}")
        attempts = by_endpoint.get(endpoint_id, [])
        answered = [row for row in attempts if row.success]
        durations = sorted(float(row.duration_ms) for row in answered)
        recent = [
            row
            for row in answered
            if row.created_at is not None
            and (row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=timezone.utc)) >= recent_cutoff
        ]
        recent_durations = [float(row.duration_ms) for row in recent]
        summaries.append(
            EndpointStats(
                endpoint_id=endpoint_id,
                name=str(endpoint.name or f"Endpoint {index + 1}"),
                provider=str(endpoint.provider or "unknown"),
                model=endpoint.model,
                requests=len(attempts),
                answered=len(answered),
                failed=len(attempts) - len(answered),
                success_rate=_rounded(100 * len(answered) / len(attempts)) if attempts else None,
                average_ms=_rounded(sum(durations) / len(durations)) if durations else None,
                p50_ms=_rounded(_percentile(durations, 0.50)),
                p95_ms=_rounded(_percentile(durations, 0.95)),
                fastest_ms=_rounded(durations[0]) if durations else None,
                slowest_ms=_rounded(durations[-1]) if durations else None,
                answered_24h=len(recent),
                average_24h_ms=_rounded(sum(recent_durations) / len(recent_durations)) if recent_durations else None,
                speed_buckets=EndpointSpeedBuckets(
                    under_5s=sum(duration < 5_000 for duration in durations),
                    from_5s_to_15s=sum(5_000 <= duration < 15_000 for duration in durations),
                    from_15s_to_60s=sum(15_000 <= duration < 60_000 for duration in durations),
                    over_60s=sum(duration >= 60_000 for duration in durations),
                ),
                last_answered_at=answered[-1].created_at if answered else None,
            )
        )
    return summaries
