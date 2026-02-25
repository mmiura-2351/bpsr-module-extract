from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Sequence

from module_ocr_tool.app.mappings import CATEGORY_ID_TO_JP
from module_ocr_tool.app.models import EffectEntry, ModuleRecord

SCHEMA_NAME = "bpsr-module-calculator/modules"
SCHEMA_VERSION = 1
ModuleKey = tuple[str, tuple[tuple[str, int], ...]]


def utc_iso8601_now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"


def normalize_module_record(module: ModuleRecord) -> ModuleRecord:
    normalized_effects: list[EffectEntry] = []
    for effect in module.effects[:3]:
        effect_id = effect.effect_id.strip()
        if not effect_id:
            continue
        normalized_effects.append(EffectEntry(effect_id=effect_id, value=int(effect.value)))

    category = module.module_category.strip().lower() if isinstance(module.module_category, str) else "general"
    allowed_categories = set(CATEGORY_ID_TO_JP.keys()) | {"general"}
    if category not in allowed_categories:
        category = "general"
    return ModuleRecord(module_category=category, effects=normalized_effects)


def module_key_from_record(module: ModuleRecord) -> ModuleKey:
    normalized = normalize_module_record(module)
    return (
        normalized.module_category,
        tuple((effect.effect_id, int(effect.value)) for effect in normalized.effects),
    )


def _module_key_from_dict(module_obj: Any) -> ModuleKey | None:
    if not isinstance(module_obj, dict):
        return None
    category = module_obj.get("module_category", "general")
    if not isinstance(category, str):
        return None
    effects_obj = module_obj.get("effects", [])
    if not isinstance(effects_obj, list):
        return None

    effect_pairs: list[tuple[str, int]] = []
    for effect in effects_obj[:3]:
        if not isinstance(effect, dict):
            return None
        effect_id = effect.get("effect_id")
        value_obj = effect.get("value")
        if not isinstance(effect_id, str):
            return None
        try:
            value = int(value_obj)
        except (TypeError, ValueError):
            return None
        effect_pairs.append((effect_id, value))
    return category, tuple(effect_pairs)


def is_duplicate_module(module: ModuleRecord, existing_modules: Sequence[ModuleRecord]) -> bool:
    target_key = module_key_from_record(module)
    for existing in existing_modules:
        if module_key_from_record(existing) == target_key:
            return True
    return False


def build_export_payload(modules: Sequence[ModuleRecord], exported_at: str | None = None) -> dict[str, object]:
    normalized_modules = [normalize_module_record(module).to_dict() for module in modules]
    return {
        "schema": SCHEMA_NAME,
        "version": SCHEMA_VERSION,
        "exported_at": exported_at or utc_iso8601_now(),
        "modules": normalized_modules,
    }


def write_export_json(payload: dict[str, object], output_path: str) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def append_modules_to_existing_json(existing_path: str, new_modules: Sequence[ModuleRecord]) -> tuple[int, int, int]:
    path = Path(existing_path)
    if not path.exists():
        raise RuntimeError(f"既存JSONが見つかりません: {existing_path}")

    try:
        with path.open("r", encoding="utf-8") as f:
            payload: Any = json.load(f)
    except Exception as exc:
        raise RuntimeError(f"既存JSONの読み込みに失敗しました: {existing_path}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("既存JSONの形式が不正です。トップレベルは object である必要があります。")

    modules_obj = payload.get("modules")
    if not isinstance(modules_obj, list):
        raise RuntimeError("既存JSONの形式が不正です。`modules` は配列である必要があります。")

    existing_keys: set[ModuleKey] = set()
    for module in modules_obj:
        key = _module_key_from_dict(module)
        if key is not None:
            existing_keys.add(key)

    added = 0
    skipped = 0
    for module in new_modules:
        normalized = normalize_module_record(module)
        if not normalized.effects:
            skipped += 1
            continue

        key = module_key_from_record(normalized)
        if key in existing_keys:
            skipped += 1
            continue

        modules_obj.append(normalized.to_dict())
        existing_keys.add(key)
        added += 1

    payload["schema"] = SCHEMA_NAME
    payload["version"] = SCHEMA_VERSION
    payload["exported_at"] = utc_iso8601_now()
    payload["modules"] = modules_obj
    write_export_json(payload, existing_path)
    return added, skipped, len(modules_obj)
