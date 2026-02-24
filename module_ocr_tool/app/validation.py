from __future__ import annotations

from module_ocr_tool.app.models import EffectEntry


def validate_effect_entries_for_module(effects: list[EffectEntry]) -> str | None:
    if len(effects) > 3:
        return "effects は最大3件です。"

    seen_effect_ids: set[str] = set()
    for effect in effects:
        if effect.effect_id in seen_effect_ids:
            return "同一効果が重複しています。重複がないように修正してください。"
        seen_effect_ids.add(effect.effect_id)
        if effect.value < 1 or effect.value > 10:
            return "value は 1〜10 の整数で入力してください。"
    return None
