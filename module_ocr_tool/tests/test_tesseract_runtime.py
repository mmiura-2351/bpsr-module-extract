from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from module_ocr_tool.app import tesseract_runtime


def _dummy_pytesseract_module() -> SimpleNamespace:
    return SimpleNamespace(pytesseract=SimpleNamespace(tesseract_cmd=""))


def test_configure_pytesseract_sets_cmd_and_tessdata(monkeypatch, tmp_path: Path) -> None:
    exe = tmp_path / "tesseract.exe"
    exe.write_text("", encoding="utf-8")
    tessdata_dir = tmp_path / "tessdata"
    tessdata_dir.mkdir()

    monkeypatch.setattr(tesseract_runtime, "_resolve_tesseract_cmd", lambda: str(exe))
    monkeypatch.setattr(tesseract_runtime, "_resolve_tessdata_dir", lambda _path: tessdata_dir)
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)

    fake_module = _dummy_pytesseract_module()
    resolved = tesseract_runtime.configure_pytesseract(fake_module)

    assert resolved == str(exe)
    assert fake_module.pytesseract.tesseract_cmd == str(exe)
    assert tesseract_runtime.os.environ["TESSDATA_PREFIX"] == str(tessdata_dir)


def test_configure_pytesseract_raises_when_not_found(monkeypatch) -> None:
    monkeypatch.setattr(tesseract_runtime, "_resolve_tesseract_cmd", lambda: None)
    fake_module = _dummy_pytesseract_module()

    with pytest.raises(RuntimeError):
        tesseract_runtime.configure_pytesseract(fake_module)

