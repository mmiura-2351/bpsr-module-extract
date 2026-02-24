from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EffectEntry:
    effect_id: str
    value: int

    def to_dict(self) -> dict[str, int | str]:
        return {
            "effect_id": self.effect_id,
            "value": self.value,
        }


@dataclass
class ModuleRecord:
    module_category: str = "general"
    effects: list[EffectEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "module_category": self.module_category,
            "effects": [effect.to_dict() for effect in self.effects],
        }

