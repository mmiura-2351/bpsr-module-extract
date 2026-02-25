from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import threading
from typing import Any

from module_ocr_tool.app.capture import CaptureRegion
from module_ocr_tool.app.config_store import default_config_path

logger = logging.getLogger(__name__)

CACHE_SCHEMA = "module-ocr-tool/position-cache"
CACHE_VERSION = 1


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_region(region: CaptureRegion | None) -> CaptureRegion | None:
    if region is None:
        return None
    try:
        left = int(region["left"])
        top = int(region["top"])
        width = int(region["width"])
        height = int(region["height"])
    except (TypeError, ValueError, KeyError):
        return None
    if left < 0 or top < 0 or width <= 0 or height <= 0:
        return None
    return {"left": left, "top": top, "width": width, "height": height}


def default_position_cache_path(config_path: str | Path | None = None) -> Path:
    if config_path is not None:
        path = Path(config_path)
        return path.parent / "ocr_position_cache.json"
    return default_config_path().parent / "ocr_position_cache.json"


@dataclass
class PositionCacheEntry:
    module_name_key: str
    module_name_raw: str = ""
    effect_regions: list[CaptureRegion | None] = field(default_factory=lambda: [None, None, None])
    category_region: CaptureRegion | None = None
    hit_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    last_used_at: str | None = None
    last_success_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "module_name_key": self.module_name_key,
            "module_name_raw": self.module_name_raw,
            "effect_regions": [_normalize_region(region) for region in (self.effect_regions + [None, None, None])[:3]],
            "category_region": _normalize_region(self.category_region),
            "hit_count": int(self.hit_count),
            "success_count": int(self.success_count),
            "failure_count": int(self.failure_count),
            "last_used_at": self.last_used_at,
            "last_success_at": self.last_success_at,
        }

    @classmethod
    def from_dict(cls, obj: Any) -> PositionCacheEntry | None:
        if not isinstance(obj, dict):
            return None
        module_name_key = obj.get("module_name_key")
        if not isinstance(module_name_key, str) or not module_name_key.strip():
            return None
        effect_regions_raw = obj.get("effect_regions")
        effect_regions: list[CaptureRegion | None] = [None, None, None]
        if isinstance(effect_regions_raw, list):
            for index in range(min(3, len(effect_regions_raw))):
                effect_regions[index] = _normalize_region(effect_regions_raw[index])
        category_region = _normalize_region(obj.get("category_region"))
        return cls(
            module_name_key=module_name_key.strip(),
            module_name_raw=obj.get("module_name_raw", "") if isinstance(obj.get("module_name_raw"), str) else "",
            effect_regions=effect_regions,
            category_region=category_region,
            hit_count=_to_int(obj.get("hit_count", 0), 0),
            success_count=_to_int(obj.get("success_count", 0), 0),
            failure_count=_to_int(obj.get("failure_count", 0), 0),
            last_used_at=obj.get("last_used_at") if isinstance(obj.get("last_used_at"), str) else None,
            last_success_at=obj.get("last_success_at") if isinstance(obj.get("last_success_at"), str) else None,
        )


class PositionCacheStore:
    def __init__(self, *, config_path: str | Path | None = None) -> None:
        self.path = default_position_cache_path(config_path)
        self._entries: dict[str, PositionCacheEntry] = {}
        self._lock = threading.Lock()

    def load(self) -> None:
        with self._lock:
            if not self.path.exists():
                logger.info("Position cache file not found. Start empty: %s", self.path)
                self._entries = {}
                return
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                logger.exception("Failed to load position cache: %s", self.path)
                self._entries = {}
                return
            if not isinstance(raw, dict):
                logger.warning("Invalid position cache format (not object): %s", self.path)
                self._entries = {}
                return
            entries_obj = raw.get("entries", [])
            parsed: dict[str, PositionCacheEntry] = {}
            if isinstance(entries_obj, list):
                for item in entries_obj:
                    entry = PositionCacheEntry.from_dict(item)
                    if entry is None:
                        continue
                    parsed[entry.module_name_key] = entry
            self._entries = parsed
            logger.info("Position cache loaded: %s (entries=%s)", self.path, len(self._entries))

    def save(self) -> None:
        with self._lock:
            payload = {
                "schema": CACHE_SCHEMA,
                "version": CACHE_VERSION,
                "updated_at": _utc_now_iso(),
                "entries": [entry.to_dict() for entry in self._entries.values()],
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            logger.info("Position cache saved: %s (entries=%s)", self.path, len(self._entries))

    def lookup(self, module_name_key: str) -> PositionCacheEntry | None:
        key = module_name_key.strip()
        if not key:
            return None
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            entry.hit_count += 1
            entry.last_used_at = _utc_now_iso()
            self._save_unlocked()
            return PositionCacheEntry.from_dict(entry.to_dict())

    def mark_failure(self, module_name_key: str) -> None:
        key = module_name_key.strip()
        if not key:
            return
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return
            entry.failure_count += 1
            entry.last_used_at = _utc_now_iso()
            self._save_unlocked()

    def update_success(
        self,
        *,
        module_name_key: str,
        module_name_raw: str,
        effect_regions: list[CaptureRegion | None],
        category_region: CaptureRegion | None,
    ) -> None:
        key = module_name_key.strip()
        if not key:
            return
        normalized_effect_regions = [_normalize_region(region) for region in (effect_regions + [None, None, None])[:3]]
        if not any(region is not None for region in normalized_effect_regions):
            return
        normalized_category = _normalize_region(category_region)

        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                entry = PositionCacheEntry(module_name_key=key)
                self._entries[key] = entry
            entry.module_name_raw = module_name_raw.strip() if module_name_raw.strip() else entry.module_name_raw
            entry.effect_regions = normalized_effect_regions
            entry.category_region = normalized_category
            entry.success_count += 1
            entry.failure_count = 0
            now = _utc_now_iso()
            entry.last_success_at = now
            entry.last_used_at = now
            self._save_unlocked()

    def _save_unlocked(self) -> None:
        payload = {
            "schema": CACHE_SCHEMA,
            "version": CACHE_VERSION,
            "updated_at": _utc_now_iso(),
            "entries": [entry.to_dict() for entry in self._entries.values()],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
