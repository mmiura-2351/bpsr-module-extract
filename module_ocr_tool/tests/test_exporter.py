from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from module_ocr_tool.app.exporter import (
    SCHEMA_NAME,
    SCHEMA_VERSION,
    append_modules_to_existing_json,
    build_export_payload,
    write_export_json,
)
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


def test_append_modules_to_existing_json_skips_duplicates_and_keeps_order(tmp_path) -> None:
    existing_path = tmp_path / "existing.json"
    existing_payload: dict[str, Any] = {
        "schema": SCHEMA_NAME,
        "version": SCHEMA_VERSION,
        "exported_at": "2026-02-25T00:00:00.000Z",
        "modules": [
            {
                "module_category": "general",
                "effects": [
                    {"effect_id": "attack_spd", "value": 4},
                    {"effect_id": "cast_focus", "value": 9},
                    {"effect_id": "luck_focus", "value": 5},
                ],
            }
        ],
    }
    existing_path.write_text(json.dumps(existing_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    new_modules = [
        ModuleRecord(
            module_category="general",
            effects=[
                EffectEntry(effect_id="attack_spd", value=4),
                EffectEntry(effect_id="cast_focus", value=9),
                EffectEntry(effect_id="luck_focus", value=5),
            ],
        ),
        ModuleRecord(
            module_category="general",
            effects=[
                EffectEntry(effect_id="crit_focus", value=6),
                EffectEntry(effect_id="resistance", value=3),
                EffectEntry(effect_id="armor", value=2),
            ],
        ),
    ]

    added, skipped, total = append_modules_to_existing_json(str(existing_path), new_modules)
    assert added == 1
    assert skipped == 1
    assert total == 2

    merged = json.loads(existing_path.read_text(encoding="utf-8"))
    assert merged["schema"] == SCHEMA_NAME
    assert merged["version"] == SCHEMA_VERSION
    assert len(merged["modules"]) == 2
    assert merged["modules"][1]["effects"] == [
        {"effect_id": "crit_focus", "value": 6},
        {"effect_id": "resistance", "value": 3},
        {"effect_id": "armor", "value": 2},
    ]
