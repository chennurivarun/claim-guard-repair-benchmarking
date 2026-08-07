"""JSON result-graph export."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.exports.common import full_export_payload


def build_json_bytes(result: Mapping[str, Any], *, indent: int = 2) -> bytes:
    """Serialize the complete result graph with stable, audit-friendly ordering."""

    return (
        json.dumps(
            full_export_payload(result),
            ensure_ascii=False,
            indent=indent,
            sort_keys=True,
            separators=(",", ": "),
        )
        + "\n"
    ).encode("utf-8")


def write_json_export(result: Mapping[str, Any], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_json_bytes(result))
    return path
