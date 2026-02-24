from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Sequence

from module_ocr_tool.app.models import ModuleRecord

SCHEMA_NAME = "bpsr-module-calculator/modules"
SCHEMA_VERSION = 1


def utc_iso8601_now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"


def build_export_payload(modules: Sequence[ModuleRecord], exported_at: str | None = None) -> dict[str, object]:
    return {
        "schema": SCHEMA_NAME,
        "version": SCHEMA_VERSION,
        "exported_at": exported_at or utc_iso8601_now(),
        "modules": [module.to_dict() for module in modules],
    }


def write_export_json(payload: dict[str, object], output_path: str) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
