"""The checked-in contract cannot depend on an optional frontend build."""

import json

from backend.app import api_schemas
from backend.app.main import app
from backend.export_openapi import export_schema


def test_openapi_export_is_stable_and_does_not_mutate_the_app_schema():
    original = json.dumps(app.openapi(), sort_keys=True)

    assert export_schema() == export_schema()
    assert json.dumps(app.openapi(), sort_keys=True) == original


def test_optional_spa_route_and_its_schema_do_not_change_the_export():
    before = export_schema()
    routes = list(app.router.routes)
    cached_schema = app.openapi_schema
    try:

        def fallback() -> dict[str, str]:
            return {"message": "Frontend is not built"}

        app.add_api_route("/__spa_probe", fallback, response_model=api_schemas.MessageResponse)
        app.openapi_schema = None

        assert "MessageResponse" in app.openapi()["components"]["schemas"]
        assert export_schema() == before
    finally:
        app.router.routes[:] = routes
        app.openapi_schema = cached_schema
