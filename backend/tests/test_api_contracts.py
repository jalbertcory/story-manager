"""Protect the OpenAPI boundary consumed by the generated frontend client."""

import pytest
from pydantic import TypeAdapter, ValidationError

from backend.app import api_schemas, models
from backend.app.main import app


def _has_concrete_shape(schema, document):
    if "$ref" in schema:
        return _has_concrete_shape(document["components"]["schemas"][schema["$ref"].split("/")[-1]], document)
    for union in ("anyOf", "oneOf", "allOf"):
        if union in schema:
            return bool(schema[union]) and all(_has_concrete_shape(branch, document) for branch in schema[union])
    if schema.get("type") == "array":
        return _has_concrete_shape(schema.get("items", {}), document)
    if schema.get("type") == "object":
        return bool(schema.get("properties")) or (
            isinstance(schema.get("additionalProperties"), dict)
            and _has_concrete_shape(schema["additionalProperties"], document)
        )
    return schema.get("type") in {"string", "integer", "number", "boolean", "null"}


def test_every_json_success_response_has_a_concrete_contract():
    document = app.openapi()
    checked = []
    for path, operations in document["paths"].items():
        if not path.startswith(("/api/", "/reader/", "/health")):
            continue
        for method, operation in operations.items():
            for status, response in operation.get("responses", {}).items():
                if not status.startswith("2"):
                    continue
                content = response.get("content", {}).get("application/json")
                if content is None:
                    continue
                checked.append((method, path, status))
                assert _has_concrete_shape(content.get("schema", {}), document), (method, path, status)
    assert len(checked) > 100


@pytest.mark.parametrize(
    ("path", "media_type", "binary"),
    [
        ("/api/books/{book_id}/download", "application/epub+zip", True),
        ("/api/audiobook/sentences/{sentence_id}/audio", "audio/mpeg", True),
        ("/api/backups/{filename}/download", "application/zip", True),
        ("/api/observability/diagnostics", "application/zip", True),
        ("/api/covers/{book_id}", "image/*", True),
        ("/reader/opds", "application/atom+xml", False),
        ("/reader/books/{book_id}/audiobook/chapters/{chapter_key}/smil", "application/smil+xml", False),
    ],
)
def test_native_media_is_not_advertised_as_json(path, media_type, binary):
    content = app.openapi()["paths"][path]["get"]["responses"]["200"]["content"]
    assert "application/json" not in content
    assert content[media_type]["schema"]["type"] == "string"
    assert (content[media_type]["schema"].get("format") == "binary") is binary


def test_optional_success_keys_remain_absent_and_null_remains_null():
    reprocess = TypeAdapter(api_schemas.ReprocessStatus)
    payload = {"running": False}
    assert reprocess.dump_python(reprocess.validate_python(payload), mode="json") == payload
    pipeline = TypeAdapter(api_schemas.PipelineQueued)
    payload = {"status": None, "queued": True}
    assert pipeline.dump_python(pipeline.validate_python(payload), mode="json") == payload
    with pytest.raises(ValidationError):
        pipeline.validate_python({"status": "paused", "queued": []})


@pytest.mark.asyncio
@pytest.mark.parametrize("download_status", ["pending", "error"])
async def test_catalog_preserves_web_import_source_link(db, app_client, download_status):
    book = models.Book(
        title="Web import",
        author="Web author",
        source_type=models.SourceType.web,
        source_url="https://example.com/story/source-link",
        download_status=download_status,
    )
    db.add(book)
    await db.commit()
    response = app_client.get("/api/books/catalog?view=all")
    assert response.status_code == 200
    entry = next(item for item in response.json()["items"] if item["id"] == book.id)
    assert entry["source_url"] == book.source_url
    assert entry["download_status"] == download_status


def test_response_defaults_are_required_without_changing_request_defaults():
    from backend.app import schemas

    output = schemas.BookCatalogPage.model_json_schema(mode="serialization")
    assert set(output["required"]) == set(output["properties"])
    request = schemas.BookUpdate.model_json_schema(mode="validation")
    assert request.get("required", []) == []
    assert schemas.BookUpdate().model_dump(exclude_unset=True) == {}
