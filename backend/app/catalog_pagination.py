"""Shared cursor encoding and keyset comparisons for book and group catalogs."""

import base64
import hashlib
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import and_, or_


def cursor_signature(params: dict) -> str:
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _json_value(value):
    if isinstance(value, Decimal):
        return str(value)
    return value.isoformat() if isinstance(value, datetime) else value


def encode_cursor(*, snapshot_max_id: int, position: list, signature: str) -> str:
    payload = {
        "v": 1,
        "snapshot_max_id": snapshot_max_id,
        "position": [_json_value(value) for value in position],
        "signature": signature,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str, *, signature: str, sort_by: str) -> tuple[int, list]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        payload = json.loads(raw)
        if payload.get("v") != 1 or payload.get("signature") != signature:
            raise ValueError
        snapshot_max_id = int(payload["snapshot_max_id"])
        position = payload["position"]
        if not isinstance(position, list) or len(position) != 3:
            raise ValueError
        if sort_by == "series_index":
            position[0] = Decimal(str(position[0]))
            if not position[0].is_finite():
                raise ValueError
        if sort_by == "updated_at":
            position[0] = datetime.fromisoformat(position[0])
        return snapshot_max_id, position
    except (KeyError, TypeError, ValueError, InvalidOperation, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid or stale catalog cursor") from exc


def seek_condition(expressions, values, sort_order: str):
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
