from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import os
from pathlib import Path
from typing import Any

from module_ocr_tool.app.capture import CaptureRegion

logger = logging.getLogger(__name__)


@dataclass
class AppConfig:
    effect_regions: list[CaptureRegion | None] = field(default_factory=lambda: [None, None, None, None])
    last_export_path: str | None = None
    last_update_json_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "effect_regions": self.effect_regions,
            "last_export_path": self.last_export_path,
            "last_update_json_path": self.last_update_json_path,
        }


def default_config_path() -> Path:
    custom_dir = os.getenv("MODULE_OCR_CONFIG_DIR")
    if custom_dir:
        return Path(custom_dir).expanduser().resolve() / "config.json"

    if os.name == "nt":
        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "ModuleOcrTool" / "config.json"

    return Path.cwd() / "config.json"


def _parse_region(value: Any) -> CaptureRegion | None:
    if not isinstance(value, dict):
        return None
    try:
        left = int(value.get("left"))
        top = int(value.get("top"))
        width = int(value.get("width"))
        height = int(value.get("height"))
    except (TypeError, ValueError):
        return None
    if left < 0 or top < 0 or width <= 0 or height <= 0:
        return None
    return {
        "left": left,
        "top": top,
        "width": width,
        "height": height,
    }


def _parse_effect_regions(value: Any) -> list[CaptureRegion | None]:
    # 旧設定ファイル(3枠)との互換を維持しつつ、カテゴリ枠を追加した4枠に拡張する。
    regions: list[CaptureRegion | None] = [None, None, None, None]
    if not isinstance(value, list):
        return regions
    for index in range(min(4, len(value))):
        regions[index] = _parse_region(value[index])
    return regions


def load_app_config(path: str | None = None) -> tuple[AppConfig, Path]:
    config_path = Path(path) if path else default_config_path()
    if not config_path.exists():
        logger.info("Config file not found. Using defaults: %s", config_path)
        return AppConfig(), config_path

    try:
        with config_path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        logger.exception("Failed to load config. Using defaults: %s", config_path)
        return AppConfig(), config_path

    if not isinstance(raw, dict):
        logger.warning("Invalid config format (not object). Using defaults: %s", config_path)
        return AppConfig(), config_path

    config = AppConfig(
        effect_regions=_parse_effect_regions(raw.get("effect_regions")),
        last_export_path=raw.get("last_export_path") if isinstance(raw.get("last_export_path"), str) else None,
        last_update_json_path=raw.get("last_update_json_path")
        if isinstance(raw.get("last_update_json_path"), str)
        else None,
    )
    logger.info("Config loaded: %s", config_path)
    return config, config_path


def save_app_config(config: AppConfig, path: str | Path | None = None) -> Path:
    config_path = Path(path) if path else default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as f:
        json.dump(config.to_dict(), f, ensure_ascii=False, indent=2)
        f.write("\n")
    logger.info("Config saved: %s", config_path)
    return config_path
