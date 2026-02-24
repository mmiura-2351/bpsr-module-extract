from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from module_ocr_tool.app.exporter import SCHEMA_NAME, SCHEMA_VERSION, build_export_payload, write_export_json
from module_ocr_tool.app.models import EffectEntry, ModuleRecord


def test_build_export_payload_fixed_schema_and_version() -> None:
    modules = [ModuleRecord(module_category="general", effects=[EffectEntry(effect_id="attack_spd", value=4)])]
    payload: dict[str, Any] = build_export_payload(modules)

    assert payload["schema"] == SCHEMA_NAME
    assert payload["version"] == SCHEMA_VERSION
    assert payload["modules"][0]["module_category"] == "general"

    exported_at = payload["exported_at"]
    assert isinstance(exported_at, str) and exported_at.endswith("Z")
    datetime.fromisoformat(exported_at.replace("Z", "+00:00"))


def test_write_export_json(tmp_path) -> None:
    payload = build_export_payload(
        [ModuleRecord(module_category="general", effects=[EffectEntry(effect_id="cast_focus", value=9)])],
        exported_at="2026-02-23T15:28:00.609Z",
    )
    output_path = tmp_path / "modules.json"
    write_export_json(payload, str(output_path))

    loaded: dict[str, Any] = json.loads(output_path.read_text(encoding="utf-8"))
    assert loaded["schema"] == SCHEMA_NAME
    assert loaded["version"] == SCHEMA_VERSION
    assert loaded["exported_at"] == "2026-02-23T15:28:00.609Z"
    assert loaded["modules"][0]["effects"][0]["effect_id"] == "cast_focus"
    assert loaded["modules"][0]["effects"][0]["value"] == 9
