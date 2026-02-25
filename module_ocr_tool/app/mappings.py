from __future__ import annotations

JP_TO_EFFECT_ID: dict[str, str] = {
    "集中・詠唱": "cast_focus",
    "集中・会心": "crit_focus",
    "集中・幸運": "luck_focus",
    "集中・攻撃速度": "attack_spd",
    "極・HP変動": "extreme_life_wave",
    "極・HP吸収": "extreme_life_steal",
    "極・幸運会心": "extreme_team_luck_crit",
    "筋力強化": "strength_boost",
    "敏捷強化": "agility_boost",
    "知力強化": "intellect_boost",
    "特攻ダメージ強化": "special_attack",
    "精鋭打撃": "elite_strike",
    "極・ダメージ増強": "extreme_dmg_stack",
    "極・適応力": "extreme_agile",
    "特攻回復強化": "healing_boost",
    "マスタリー回復強化": "healing_enhance",
    "極・HP凝縮": "extreme_life_condense",
    "極・応急処置": "extreme_first_aid",
    "魔法耐性": "resistance",
    "物理耐性": "armor",
    "極・絶境守護": "extreme_final_protection",
}

EFFECT_ID_TO_JP: dict[str, str] = {value: key for key, value in JP_TO_EFFECT_ID.items()}

CATEGORY_ID_TO_JP: dict[str, str] = {
    "general": "汎用",
    "attack": "攻撃",
    "defense": "生存",
    "support": "支援",
}

# OCR揺れ・表記揺れを吸収するための別名。
CATEGORY_JP_TO_ID: dict[str, str] = {
    "汎用": "general",
    "一般": "general",
    "攻撃": "attack",
    "生存": "defense",
    "防御": "defense",
    "支援": "support",
}
