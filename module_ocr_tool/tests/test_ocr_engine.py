from __future__ import annotations

from module_ocr_tool.app.ocr_engine import TesseractOcrEngine


class _FakeImage:
    shape = (300, 400, 3)

    def __getitem__(self, _key):
        return self


def test_extract_effect_texts_uses_whole_area_when_three_lines_exist(monkeypatch) -> None:
    engine = TesseractOcrEngine()
    call_count = {"count": 0}

    def fake_extract_text(_image, *, config_override=None, **_kwargs):  # noqa: ANN001
        call_count["count"] += 1
        assert config_override is None
        return "集中・攻撃速度+4\n集中・詠唱+9\n集中・幸運+5"

    monkeypatch.setattr(engine, "extract_text", fake_extract_text)
    lines = engine.extract_effect_texts(_FakeImage(), max_effects=3)

    assert lines == ["集中・攻撃速度+4", "集中・詠唱+9", "集中・幸運+5"]
    assert call_count["count"] == 1


def test_extract_effect_texts_fills_missing_lines_with_band_ocr(monkeypatch) -> None:
    engine = TesseractOcrEngine()
    band_calls = {"index": 0}
    band_results = [
        "集中・攻撃速度+4",  # duplicate
        "集中・詠唱+9",
        "集中・幸運+5",
    ]

    def fake_extract_text(_image, *, config_override=None, **_kwargs):  # noqa: ANN001
        if config_override is None:
            return "集中・攻撃速度+4"
        value = band_results[band_calls["index"]]
        band_calls["index"] += 1
        return value

    monkeypatch.setattr(engine, "extract_text", fake_extract_text)
    lines = engine.extract_effect_texts(_FakeImage(), max_effects=3)

    assert lines == ["集中・攻撃速度+4", "集中・詠唱+9", "集中・幸運+5"]


def test_extract_effect_line_runs_label_and_value_ocr(monkeypatch) -> None:
    engine = TesseractOcrEngine()

    def fake_extract_text(_image, *, config_override=None, lang_override=None, **_kwargs):  # noqa: ANN001
        if config_override == engine.value_config:
            assert lang_override == "eng"
            return "9"
        assert config_override == engine.single_line_config
        return "集中・詠唱+?"

    monkeypatch.setattr(engine, "extract_text", fake_extract_text)
    line = engine.extract_effect_line(_FakeImage())
    assert line == "集中・詠唱+9"


def test_extract_effect_line_skips_value_ocr_when_label_has_valid_value(monkeypatch) -> None:
    engine = TesseractOcrEngine()
    call_count = {"value": 0}

    def fake_extract_text(_image, *, config_override=None, lang_override=None, **_kwargs):  # noqa: ANN001
        if config_override == engine.value_config:
            call_count["value"] += 1
            return "9"
        return "集中・幸運+5"

    monkeypatch.setattr(engine, "extract_text", fake_extract_text)
    line = engine.extract_effect_line(_FakeImage())
    assert line == "集中・幸運+5"
    assert call_count["value"] == 0


def test_extract_effect_line_runs_value_ocr_when_label_value_is_out_of_range(monkeypatch) -> None:
    engine = TesseractOcrEngine()
    call_count = {"value": 0}

    def fake_extract_text(_image, *, config_override=None, lang_override=None, **_kwargs):  # noqa: ANN001
        if config_override == engine.value_config:
            call_count["value"] += 1
            return "7"
        return "知力強化+75"

    monkeypatch.setattr(engine, "extract_text", fake_extract_text)
    line = engine.extract_effect_line(_FakeImage())
    assert line == "知力強化+7"
    assert call_count["value"] == 1


def test_extract_effect_line_drops_ambiguous_value_ocr_digits(monkeypatch) -> None:
    engine = TesseractOcrEngine()

    def fake_extract_text(_image, *, config_override=None, lang_override=None, **_kwargs):  # noqa: ANN001
        if config_override == engine.value_config:
            return "0848"
        return "集中・詠唱+?"

    monkeypatch.setattr(engine, "extract_text", fake_extract_text)
    line = engine.extract_effect_line(_FakeImage())
    assert line == "集中・詠唱"


def test_extract_effect_line_returns_empty_when_label_missing(monkeypatch) -> None:
    engine = TesseractOcrEngine()

    def fake_extract_text(_image, *, config_override=None, lang_override=None, **_kwargs):  # noqa: ANN001
        if config_override == engine.value_config:
            return "8"
        return "   "

    monkeypatch.setattr(engine, "extract_text", fake_extract_text)
    line = engine.extract_effect_line(_FakeImage())
    assert line == ""


def test_extract_effect_line_falls_back_to_label_value_when_value_ocr_empty(monkeypatch) -> None:
    engine = TesseractOcrEngine()

    def fake_extract_text(_image, *, config_override=None, lang_override=None, **_kwargs):  # noqa: ANN001
        if config_override == engine.value_config:
            return ""
        return "集中・会心+6"

    monkeypatch.setattr(engine, "extract_text", fake_extract_text)
    line = engine.extract_effect_line(_FakeImage())
    assert line == "集中・会心+6"
