from __future__ import annotations

"""Conservative JSON file helpers for the pipeline.

The helpers expose explicit options instead of silently imposing a schema or
serialization policy. Baseline scripts are not wired to these functions in
Commit 1.
"""

import json
from pathlib import Path
from typing import Any


def ensure_directory(path: Path) -> None:
    """Create ``path`` and missing parents if necessary."""
    path.mkdir(parents=True, exist_ok=True)


def load_json_object(path: Path, *, encoding: str = "utf-8") -> dict[str, Any]:
    """Load a JSON document and require an object at the root."""
    with path.open("r", encoding=encoding) as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise TypeError(f'File "{path}" phải chứa object JSON ở cấp gốc.')

    return data


def save_json(
    data: Any,
    path: Path,
    *,
    indent: int = 2,
    ensure_ascii: bool = False,
    encoding: str = "utf-8",
    create_parent: bool = True,
) -> None:
    """Write JSON using explicitly supplied serialization settings."""
    if create_parent:
        ensure_directory(path.parent)

    with path.open("w", encoding=encoding) as file:
        json.dump(data, file, ensure_ascii=ensure_ascii, indent=indent)
        file.write("\n")
