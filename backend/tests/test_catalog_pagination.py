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
        ("word_count", -1),
        ("author", ""),
        ("audiobook_enabled", 0),
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


@pytest.mark.parametrize(
    ("field", "value", "sort_by"),
    [
        ("v", True, "title"),
        ("snapshot_max_id", True, "title"),
        ("snapshot_max_id", "42", "title"),
        ("snapshot_max_id", -1, "title"),
        ("snapshot_max_id", float("inf"), "title"),
        ("snapshot_max_id", 2**100, "title"),
        ("position", [None, "title", 7], "title"),
        ("position", [123, "title", 7], "title"),
        ("position", ["title", None, 7], "title"),
        ("position", ["title", 123, 7], "title"),
        ("position", ["title", "title", None], "title"),
        ("position", ["title", "title", True], "title"),
        ("position", ["title", "title", "7"], "title"),
        ("position", ["title", "title", 43], "title"),
        ("position", ["title", "title", 0], "title"),
        ("position", ["many", "title", 7], "word_count"),
        ("position", [True, "title", 7], "word_count"),
        ("position", [float("nan"), "title", 7], "word_count"),
        ("position", [2**100, "title", 7], "word_count"),
        ("position", [2, "title", 7], "audiobook_enabled"),
        ("position", ["NaN", "title", 7], "series_index"),
    ],
)
def test_cursor_rejects_values_unsafe_for_database_comparisons(field, value, sort_by):
    payload = {"v": 1, "signature": "query", "snapshot_max_id": 42, "position": ["title", "title", 7]}
    payload[field] = value
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    with pytest.raises(HTTPException) as error:
        decode_cursor(encoded, signature="query", sort_by=sort_by)
    assert error.value.status_code == 400


def test_cursor_rejects_invalid_base64_characters():
    encoded = encode_cursor(snapshot_max_id=42, position=["title", "title", 7], signature="query")
    with pytest.raises(HTTPException) as error:
        decode_cursor("!" + encoded, signature="query", sort_by="title")
    assert error.value.status_code == 400
