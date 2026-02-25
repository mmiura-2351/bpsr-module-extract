from __future__ import annotations

from module_ocr_tool.app.normalizer import normalize_module_name_text, parse_category_text, parse_ocr_text


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


def test_parse_category_text_attack() -> None:
    parsed = parse_category_text("攻撃型モジュール")
    assert parsed.resolved_category == "attack"


def test_parse_category_text_survival_alias_maps_to_defense() -> None:
    parsed = parse_category_text("生存型モジュール |")
    assert parsed.resolved_category == "defense"


def test_parse_category_text_defense_alias_maps_to_defense() -> None:
    parsed = parse_category_text("防御型モジュール")
    assert parsed.resolved_category == "defense"


def test_parse_category_text_empty_falls_back_to_general() -> None:
    parsed = parse_category_text("")
    assert parsed.resolved_category == "general"
    assert "汎用" in parsed.jp_label_candidates


def test_parse_category_text_unknown_falls_back_to_general() -> None:
    parsed = parse_category_text("不明カテゴリ")
    assert parsed.resolved_category == "general"


def test_normalize_module_name_text() -> None:
    normalized = normalize_module_name_text("EXC攻撃型モジュール・精選 |")
    assert normalized == "exc攻撃型モジュール精選"


def test_normalize_module_name_text_empty() -> None:
    assert normalize_module_name_text("   ") == ""
