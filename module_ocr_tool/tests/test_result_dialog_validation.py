from __future__ import annotations

from module_ocr_tool.app.models import EffectEntry
from module_ocr_tool.app.validation import validate_effect_entries_for_module


def test_validate_effect_entries_allows_valid_values() -> None:
    effects = [
        EffectEntry(effect_id="attack_spd", value=4),
        EffectEntry(effect_id="cast_focus", value=9),
        EffectEntry(effect_id="luck_focus", value=5),
    ]
    assert validate_effect_entries_for_module(effects) is None


def test_validate_effect_entries_rejects_duplicate_effect_id() -> None:
    effects = [
        EffectEntry(effect_id="attack_spd", value=4),
        EffectEntry(effect_id="attack_spd", value=5),
    ]
    assert validate_effect_entries_for_module(effects) == "同一効果が重複しています。重複がないように修正してください。"


def test_validate_effect_entries_rejects_out_of_range_value() -> None:
    effects = [
        EffectEntry(effect_id="attack_spd", value=0),
    ]
    assert validate_effect_entries_for_module(effects) == "value は 1〜10 の整数で入力してください。"
