"""Cursor boundary validation and round trips for supported sort values."""

import base64
import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException

from backend.app.catalog_pagination import decode_cursor, encode_cursor


@pytest.mark.parametrize(
    ("sort_by", "value"),
    [
        ("title", "a title"),
        ("series_index", Decimal("1.25")),
        ("updated_at", datetime(2026, 1, 2, tzinfo=timezone.utc)),
        ("word_count", 12000),
    ],
)
def test_cursor_round_trip_preserves_sort_values(sort_by, value):
    encoded = encode_cursor(snapshot_max_id=42, position=[value, "title", 7], signature="query")
    assert decode_cursor(encoded, signature="query", sort_by=sort_by) == (42, [value, "title", 7])


@pytest.mark.parametrize(
    ("payload", "sort_by"),
    [
        ([], "title"),
        (None, "title"),
        ({"v": 1, "signature": "query", "snapshot_max_id": 42, "position": [{}, "title", 7]}, "title"),
        ({"v": 1, "signature": "query", "snapshot_max_id": 42, "position": [[], "title", 7]}, "title"),
        ({"v": 1, "signature": "query", "snapshot_max_id": 42, "position": [123, "title", 7]}, "updated_at"),
    ],
)
def test_malformed_cursor_shape_returns_client_error(payload, sort_by):
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    with pytest.raises(HTTPException) as error:
        decode_cursor(encoded, signature="query", sort_by=sort_by)
    assert error.value.status_code == 400
