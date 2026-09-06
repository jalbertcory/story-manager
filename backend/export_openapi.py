"""Export the API contract without a running server or database connection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.main import app


def _schema_references(value: object) -> set[str]:
    references: set[str] = set()
    if isinstance(value, dict):
        reference = value.get("$ref")
        prefix = "#/components/schemas/"
        if isinstance(reference, str) and reference.startswith(prefix):
            references.add(reference.removeprefix(prefix).replace("~1", "/").replace("~0", "~"))
        for item in value.values():
            references.update(_schema_references(item))
    elif isinstance(value, list):
        for item in value:
            references.update(_schema_references(item))
    return references


def export_schema() -> str:
    """Exclude conditional SPA routes so exports do not depend on a UI build."""
    schema = dict(app.openapi())
    schema["paths"] = {
        path: operations for path, operations in schema["paths"].items() if path.startswith(("/api/", "/reader/", "/health"))
    }
    # A conditional SPA/root route can introduce a component even after its
    # path is removed. Keep only schemas reachable from the retained API.
    components = dict(schema.get("components", {}))
    definitions = components.get("schemas", {})
    roots = {key: value for key, value in schema.items() if key != "components"}
    roots.update({key: value for key, value in components.items() if key != "schemas"})
    required = _schema_references(roots)
    pending = list(required)
    while pending:
        name = pending.pop()
        discovered = _schema_references(definitions.get(name, {})) - required
        required.update(discovered)
        pending.extend(discovered)
    components["schemas"] = {name: definition for name, definition in definitions.items() if name in required}
    schema["components"] = components
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    contents = export_schema()
    if arguments.output is None:
        print(contents, end="")
    else:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(contents, encoding="utf-8")


if __name__ == "__main__":
    main()
