from __future__ import annotations

from dataclasses import dataclass
import difflib
import re

from module_ocr_tool.app.mappings import JP_TO_EFFECT_ID
from module_ocr_tool.app.models import EffectEntry

try:
    from rapidfuzz import fuzz as _rapidfuzz_fuzz
    from rapidfuzz import process as _rapidfuzz_process
except Exception:  # pragma: no cover - optional dependency
    _rapidfuzz_fuzz = None
    _rapidfuzz_process = None

VALUE_PATTERN = re.compile(r"([+-]?\d+)")
LABEL_VARIANTS = str.maketrans(
    {
        "･": "・",
        "·": "・",
        "・": "・",
        "＋": "+",
        "　": " ",
    }
)


@dataclass
class ParsedEffectCandidate:
    raw_line: str
    parsed_value: int | None
    resolved_effect_id: str | None
    jp_label_candidates: list[str]


def normalize_label(label: str) -> str:
    sanitized = label.translate(LABEL_VARIANTS)
    sanitized = re.sub(r"[0-9０-９]", "", sanitized)
    sanitized = re.sub(r"[+＋＊*xX×<＜>＞=~〜]+", "", sanitized)
    sanitized = re.sub(r"\s+", "", sanitized)
    return sanitized.strip(":：-")


def _extract_value_and_label(raw_line: str) -> tuple[int | None, str]:
    line = raw_line.strip()
    match = VALUE_PATTERN.search(line)
    if not match:
        return None, normalize_label(line)

    value_text = match.group(1)
    try:
        parsed_value = int(value_text.replace("+", ""))
    except ValueError:
        parsed_value = None

    left = line[: match.start()]
    right = line[match.end() :]
    label = normalize_label(f"{left}{right}")
    return parsed_value, label


def _build_normalized_label_index() -> dict[str, str]:
    return {normalize_label(jp_label): jp_label for jp_label in JP_TO_EFFECT_ID}


def _build_candidates(
    normalized_label: str,
    normalized_to_label: dict[str, str],
    *,
    candidate_limit: int,
    cutoff: float,
) -> list[str]:
    if not normalized_label:
        return []
    keys = list(normalized_to_label.keys())
    if _rapidfuzz_process is not None and _rapidfuzz_fuzz is not None:
        matched = _rapidfuzz_process.extract(
            normalized_label,
            keys,
            scorer=_rapidfuzz_fuzz.WRatio,
            limit=candidate_limit,
            score_cutoff=int(cutoff * 100),
        )
        return [normalized_to_label[str(key)] for key, _score, _idx in matched]

    matched_keys = difflib.get_close_matches(
        normalized_label,
        keys,
        n=candidate_limit,
        cutoff=cutoff,
    )
    return [normalized_to_label[key] for key in matched_keys]


def parse_ocr_text(
    ocr_text: str,
    *,
    max_effects: int = 3,
    candidate_limit: int = 4,
    cutoff: float = 0.50,
) -> list[ParsedEffectCandidate]:
    normalized_to_label = _build_normalized_label_index()
    parsed: list[ParsedEffectCandidate] = []

    for raw_line in (line for line in ocr_text.splitlines() if line.strip()):
        if len(parsed) >= max_effects:
            break

        parsed_value, normalized_label = _extract_value_and_label(raw_line)
        exact_label = normalized_to_label.get(normalized_label)

        if exact_label is not None:
            parsed.append(
                ParsedEffectCandidate(
                    raw_line=raw_line,
                    parsed_value=parsed_value,
                    resolved_effect_id=JP_TO_EFFECT_ID[exact_label],
                    jp_label_candidates=[exact_label],
                )
            )
            continue

        candidates = _build_candidates(
            normalized_label,
            normalized_to_label,
            candidate_limit=candidate_limit,
            cutoff=cutoff,
        )
        resolved_effect_id = JP_TO_EFFECT_ID[candidates[0]] if candidates else None
        parsed.append(
            ParsedEffectCandidate(
                raw_line=raw_line,
                parsed_value=parsed_value,
                resolved_effect_id=resolved_effect_id,
                jp_label_candidates=candidates,
            )
        )

    return parsed


def build_effect_entries(candidates: list[ParsedEffectCandidate]) -> list[EffectEntry]:
    effects: list[EffectEntry] = []
    for candidate in candidates:
        if candidate.resolved_effect_id is None or candidate.parsed_value is None:
            continue
        effects.append(EffectEntry(effect_id=candidate.resolved_effect_id, value=candidate.parsed_value))
    return effects[:3]
