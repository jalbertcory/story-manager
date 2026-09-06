"""Shared cursor encoding and keyset comparisons for book and group catalogs."""

import base64
import hashlib
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, or_
from sqlalchemy.sql.elements import ColumnElement, SQLColumnExpression

CursorValue = str | int | float | Decimal | datetime | None


def cursor_signature(params: Mapping[str, object]) -> str:
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _json_value(value: CursorValue) -> str | int | float | None:
    if isinstance(value, Decimal):
        return str(value)
    return value.isoformat() if isinstance(value, datetime) else value


def encode_cursor(*, snapshot_max_id: int, position: Sequence[CursorValue], signature: str) -> str:
    payload = {
        "v": 1,
        "snapshot_max_id": snapshot_max_id,
        "position": [_json_value(value) for value in position],
        "signature": signature,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str, *, signature: str, sort_by: str) -> tuple[int, list[CursorValue]]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError
        if payload.get("v") != 1 or payload.get("signature") != signature:
            raise ValueError
        snapshot_max_id = int(payload["snapshot_max_id"])
        raw_position = payload["position"]
        if not isinstance(raw_position, list) or len(raw_position) != 3:
            raise ValueError
        position: list[CursorValue] = []
        for value in raw_position:
            if value is not None and not isinstance(value, (str, int, float)):
                raise ValueError
            position.append(value)
        if sort_by == "series_index":
            series_index = Decimal(str(position[0]))
            if not series_index.is_finite():
                raise ValueError
            position[0] = series_index
        if sort_by == "updated_at":
            timestamp = position[0]
            if not isinstance(timestamp, str):
                raise ValueError
            position[0] = datetime.fromisoformat(timestamp)
        return snapshot_max_id, position
    except (KeyError, TypeError, ValueError, InvalidOperation, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid or stale catalog cursor") from exc


def seek_condition(
    expressions: Sequence[SQLColumnExpression[Any]], values: Sequence[CursorValue], sort_order: str
) -> ColumnElement[bool]:
    primary, title, identifier = expressions
    primary_value, title_value, identifier_value = values
    primary_after = primary < primary_value if sort_order == "desc" else primary > primary_value
    return or_(
        primary_after,
        and_(
            primary == primary_value,
            or_(title > title_value, and_(title == title_value, identifier > identifier_value)),
        ),
    )
