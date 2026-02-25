from __future__ import annotations

from module_ocr_tool.app.normalizer import parse_ocr_text


def test_parse_normal_line() -> None:
    parsed = parse_ocr_text("集中・攻撃速度+4")
    assert len(parsed) == 1
    assert parsed[0].resolved_effect_id == "attack_spd"
    assert parsed[0].parsed_value == 4


def test_parse_misrecognized_label_returns_candidates() -> None:
    parsed = parse_ocr_text("集中・攻事速度+4")
    assert len(parsed) == 1
    assert parsed[0].resolved_effect_id == "attack_spd"
    assert "集中・攻撃速度" in parsed[0].jp_label_candidates


def test_parse_label_with_symbol_noise_still_matches() -> None:
    parsed = parse_ocr_text("集中・詠喝*9")
    assert len(parsed) == 1
    assert parsed[0].resolved_effect_id == "cast_focus"
    assert parsed[0].parsed_value == 9


def test_parse_missing_value() -> None:
    parsed = parse_ocr_text("集中・詠唱")
    assert len(parsed) == 1
    assert parsed[0].resolved_effect_id == "cast_focus"
    assert parsed[0].parsed_value is None


def test_parse_out_of_range_value_is_treated_as_missing() -> None:
    parsed = parse_ocr_text("集中・詠唱+75")
    assert len(parsed) == 1
    assert parsed[0].resolved_effect_id == "cast_focus"
    assert parsed[0].parsed_value is None


def test_parse_numeric_only_line_does_not_resolve_effect() -> None:
    parsed = parse_ocr_text("8")
    assert len(parsed) == 1
    assert parsed[0].resolved_effect_id is None
    assert parsed[0].parsed_value == 8
    assert parsed[0].jp_label_candidates == []


def test_parse_limit_to_three_effects() -> None:
    text = "\n".join(
        [
            "集中・攻撃速度+4",
            "集中・詠唱+9",
            "集中・幸運+5",
            "集中・会心+2",
        ]
    )
    parsed = parse_ocr_text(text)
    assert len(parsed) == 3
