from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
from typing import Any


def _project_package_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _runtime_base_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return _project_package_root()


def _candidate_executable_paths() -> list[Path]:
    base_dir = _runtime_base_dir()
    package_root = _project_package_root()

    candidates: list[Path] = []
    if os.name == "nt":
        exe_name = "tesseract.exe"
        candidates.extend(
            [
                base_dir / "tesseract" / exe_name,
                base_dir / "vendor" / "tesseract" / exe_name,
                package_root / "vendor" / "tesseract" / exe_name,
            ]
        )
        if getattr(sys, "frozen", False):
            candidates.append(Path(sys.executable).resolve().parent / "tesseract" / exe_name)
    else:
        path_cmd = shutil.which("tesseract")
        if path_cmd:
            candidates.append(Path(path_cmd))
        candidates.extend(
            [
                base_dir / "tesseract" / "tesseract",
                base_dir / "vendor" / "tesseract" / "tesseract",
                package_root / "vendor" / "tesseract" / "tesseract",
            ]
        )

    # Deduplicate while preserving order.
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _resolve_tesseract_cmd() -> str | None:
    if os.name == "nt":
        path_cmd = shutil.which("tesseract.exe")
    else:
        path_cmd = shutil.which("tesseract")

    for candidate in _candidate_executable_paths():
        if candidate.exists() and candidate.is_file():
            return str(candidate)

    if path_cmd:
        return path_cmd
    return None


def _resolve_tessdata_dir(executable_path: Path) -> Path | None:
    base_dir = _runtime_base_dir()
    package_root = _project_package_root()

    candidates = [
        executable_path.parent / "tessdata",
        executable_path.parent.parent / "tessdata",
        base_dir / "tesseract" / "tessdata",
        base_dir / "vendor" / "tesseract" / "tessdata",
        package_root / "vendor" / "tesseract" / "tessdata",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def configure_pytesseract(pytesseract_module: Any) -> str:
    tesseract_cmd = _resolve_tesseract_cmd()
    if not tesseract_cmd:
        raise RuntimeError(
            "Tesseract が見つかりません。"
            "同梱する場合は `module_ocr_tool/vendor/tesseract/` に `tesseract.exe` と "
            "`tessdata/jpn.traineddata` を配置してください。"
        )

    pytesseract_module.pytesseract.tesseract_cmd = tesseract_cmd
    tessdata_dir = _resolve_tessdata_dir(Path(tesseract_cmd))
    if tessdata_dir is not None and "TESSDATA_PREFIX" not in os.environ:
        os.environ["TESSDATA_PREFIX"] = str(tessdata_dir)
    return tesseract_cmd

