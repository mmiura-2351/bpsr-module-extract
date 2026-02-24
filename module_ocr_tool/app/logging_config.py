from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys

LOGGER_NAMESPACE = "module_ocr_tool"
LOG_FILENAME = "module_ocr_tool.log"

_configured = False
_log_file_path: Path | None = None


def _default_log_dir() -> Path:
    custom_dir = os.getenv("MODULE_OCR_LOG_DIR")
    if custom_dir:
        return Path(custom_dir).expanduser().resolve()

    if os.name == "nt":
        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "ModuleOcrTool" / "logs"

    if getattr(sys, "frozen", False):
        return Path.home() / ".module_ocr_tool" / "logs"

    return Path.cwd() / "logs"


def setup_logging(level: int = logging.INFO) -> Path:
    global _configured, _log_file_path

    if _configured and _log_file_path is not None:
        return _log_file_path

    log_dir = _default_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / LOG_FILENAME

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(threadName)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    file_handler = RotatingFileHandler(
        filename=log_file,
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(level)
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

    logging.getLogger("PIL").setLevel(logging.WARNING)

    _configured = True
    _log_file_path = log_file
    logging.getLogger(__name__).info("Logging initialized: %s", log_file)
    return log_file


def get_log_file_path() -> Path | None:
    return _log_file_path

