from __future__ import annotations

from dataclasses import dataclass
import difflib
import re

from module_ocr_tool.app.mappings import CATEGORY_ID_TO_JP, CATEGORY_JP_TO_ID, JP_TO_EFFECT_ID
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
CATEGORY_VARIANTS = str.maketrans(
    {
        "　": " ",
        "｜": "|",
        "l": "|",
        "I": "|",
    }
)
MODULE_NAME_VARIANTS = str.maketrans(
    {
        "　": " ",
        "｜": "|",
        "I": "|",
        "l": "|",
    }
)
MIN_EFFECT_VALUE = 1
MAX_EFFECT_VALUE = 10
VALID_EFFECT_VALUE_PAIRS: set[tuple[str, int]] = {
    (effect_id, value)
    for effect_id in JP_TO_EFFECT_ID.values()
    for value in range(MIN_EFFECT_VALUE, MAX_EFFECT_VALUE + 1)
}


@dataclass
class ParsedEffectCandidate:
    raw_line: str
    parsed_value: int | None
    resolved_effect_id: str | None
    jp_label_candidates: list[str]


@dataclass
class ParsedCategoryCandidate:
    raw_text: str
    resolved_category: str | None
    jp_label_candidates: list[str]


def normalize_label(label: str) -> str:
    sanitized = label.translate(LABEL_VARIANTS)
    sanitized = re.sub(r"[0-9０-９]", "", sanitized)
    sanitized = re.sub(r"[+＋＊*xX×<＜>＞=~〜]+", "", sanitized)
    sanitized = re.sub(r"\s+", "", sanitized)
    return sanitized.strip(":：-")


def normalize_category_label(label: str) -> str:
    sanitized = label.translate(CATEGORY_VARIANTS)
    sanitized = sanitized.replace("モジュール", "")
    sanitized = sanitized.replace("型", "")
    sanitized = sanitized.replace("|", "")
    sanitized = re.sub(r"\s+", "", sanitized)
    sanitized = re.sub(r"[^ぁ-んァ-ン一-龥]", "", sanitized)
    return sanitized.strip(":：-")


def normalize_module_name_text(label: str) -> str:
    line = next((chunk.strip() for chunk in label.splitlines() if chunk.strip()), label.strip())
    if not line:
        return ""
    sanitized = line.translate(MODULE_NAME_VARIANTS)
    sanitized = sanitized.replace("|", "")
    sanitized = re.sub(r"\s+", "", sanitized)
    sanitized = re.sub(r"[^ぁ-んァ-ンー一-龥A-Za-z0-9+._-]", "", sanitized)
    return sanitized.lower()


def infer_expected_effect_count(module_name_text: str) -> int:
    normalized = normalize_module_name_text(module_name_text)
    if not normalized:
        return 3
    if normalized.startswith("基本"):
        return 1
    if normalized.startswith("高性能"):
        return 2
    return 3


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
    if parsed_value is not None and not (MIN_EFFECT_VALUE <= parsed_value <= MAX_EFFECT_VALUE):
        parsed_value = None

    left = line[: match.start()]
    right = line[match.end() :]
    label = normalize_label(f"{left}{right}")
    return parsed_value, label


def _build_normalized_label_index() -> dict[str, str]:
    return {normalize_label(jp_label): jp_label for jp_label in JP_TO_EFFECT_ID}


def _build_normalized_category_alias_index() -> dict[str, str]:
    return {normalize_category_label(jp_label): jp_label for jp_label in CATEGORY_JP_TO_ID}


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


def _label_similarity_score(normalized_label: str, jp_label: str) -> float:
    normalized_candidate = normalize_label(jp_label)
    if not normalized_label or not normalized_candidate:
        return 0.0
    if _rapidfuzz_fuzz is not None:
        try:
            return float(_rapidfuzz_fuzz.WRatio(normalized_label, normalized_candidate)) / 100.0
        except Exception:
            pass
    return difflib.SequenceMatcher(None, normalized_label, normalized_candidate).ratio()


def _resolve_effect_id_from_candidates(
    normalized_label: str,
    candidates: list[str],
    *,
    resolve_cutoff: float,
    ambiguity_margin: float,
) -> str | None:
    if not candidates:
        return None

    top_score = _label_similarity_score(normalized_label, candidates[0])
    if top_score < resolve_cutoff:
        return None

    second_score = _label_similarity_score(normalized_label, candidates[1]) if len(candidates) >= 2 else 0.0
    if second_score > 0.0 and (top_score - second_score) < ambiguity_margin:
        return None

    return JP_TO_EFFECT_ID[candidates[0]]


def parse_ocr_text(
    ocr_text: str,
    *,
    max_effects: int = 3,
    candidate_limit: int = 4,
    cutoff: float = 0.50,
    resolve_cutoff: float = 0.68,
    ambiguity_margin: float = 0.08,
) -> list[ParsedEffectCandidate]:
    normalized_to_label = _build_normalized_label_index()
    parsed: list[ParsedEffectCandidate] = []

    for raw_line in (line for line in ocr_text.splitlines() if line.strip()):
        if len(parsed) >= max_effects:
            break

        parsed_value, normalized_label = _extract_value_and_label(raw_line)
        exact_label = normalized_to_label.get(normalized_label)

        if exact_label is not None:
            resolved_effect_id = JP_TO_EFFECT_ID[exact_label]
            if parsed_value is not None and (resolved_effect_id, parsed_value) not in VALID_EFFECT_VALUE_PAIRS:
                parsed_value = None
            parsed.append(
                ParsedEffectCandidate(
                    raw_line=raw_line,
                    parsed_value=parsed_value,
                    resolved_effect_id=resolved_effect_id,
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
        resolved_effect_id = _resolve_effect_id_from_candidates(
            normalized_label,
            candidates,
            resolve_cutoff=resolve_cutoff,
            ambiguity_margin=ambiguity_margin,
        )

        if resolved_effect_id is not None and parsed_value is not None:
            if (resolved_effect_id, parsed_value) not in VALID_EFFECT_VALUE_PAIRS:
                parsed_value = None
        parsed.append(
            ParsedEffectCandidate(
                raw_line=raw_line,
                parsed_value=parsed_value,
                resolved_effect_id=resolved_effect_id,
                jp_label_candidates=candidates,
            )
        )

    return parsed


def parse_category_text(
    raw_text: str,
    *,
    candidate_limit: int = 3,
    cutoff: float = 0.40,
    resolve_cutoff: float = 0.62,
    ambiguity_margin: float = 0.08,
) -> ParsedCategoryCandidate:
    normalized_to_alias = _build_normalized_category_alias_index()
    normalized_aliases = list(normalized_to_alias.keys())
    raw_lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if not raw_lines and raw_text.strip():
        raw_lines = [raw_text.strip()]

    normalized_samples = [normalize_category_label(line) for line in raw_lines if normalize_category_label(line)]
    if not normalized_samples and raw_text.strip():
        fallback = normalize_category_label(raw_text)
        if fallback:
            normalized_samples = [fallback]

    for sample in normalized_samples:
        for normalized_alias, jp_alias in normalized_to_alias.items():
            if normalized_alias and normalized_alias in sample:
                category_id = CATEGORY_JP_TO_ID[jp_alias]
                return ParsedCategoryCandidate(
                    raw_text=raw_text,
                    resolved_category=category_id,
                    jp_label_candidates=[CATEGORY_ID_TO_JP[category_id]],
                )

    if not normalized_samples:
        return ParsedCategoryCandidate(
            raw_text=raw_text,
            resolved_category="general",
            jp_label_candidates=list(CATEGORY_ID_TO_JP.values()),
        )

    best_sample = max(normalized_samples, key=len)
    if _rapidfuzz_process is not None and _rapidfuzz_fuzz is not None:
        matched = _rapidfuzz_process.extract(
            best_sample,
            normalized_aliases,
            scorer=_rapidfuzz_fuzz.WRatio,
            limit=max(candidate_limit, 1),
            score_cutoff=int(cutoff * 100),
        )
        matched_aliases = [normalized_to_alias[str(key)] for key, _score, _idx in matched]
    else:
        close_keys = difflib.get_close_matches(
            best_sample,
            normalized_aliases,
            n=max(candidate_limit, 1),
            cutoff=cutoff,
        )
        matched_aliases = [normalized_to_alias[key] for key in close_keys]

    category_candidates: list[str] = []
    for alias in matched_aliases:
        category_id = CATEGORY_JP_TO_ID[alias]
        jp_label = CATEGORY_ID_TO_JP[category_id]
        if jp_label not in category_candidates:
            category_candidates.append(jp_label)

    if not category_candidates:
        category_candidates = list(CATEGORY_ID_TO_JP.values())

    resolved_category: str | None = "general"
    top_score = _label_similarity_score(best_sample, category_candidates[0])
    second_score = _label_similarity_score(best_sample, category_candidates[1]) if len(category_candidates) >= 2 else 0.0
    if top_score >= resolve_cutoff and ((top_score - second_score) >= ambiguity_margin or second_score == 0.0):
        resolved_category = CATEGORY_JP_TO_ID[category_candidates[0]]

    return ParsedCategoryCandidate(
        raw_text=raw_text,
        resolved_category=resolved_category,
        jp_label_candidates=category_candidates,
    )


def build_effect_entries(candidates: list[ParsedEffectCandidate]) -> list[EffectEntry]:
    effects: list[EffectEntry] = []
    for candidate in candidates:
        if candidate.resolved_effect_id is None or candidate.parsed_value is None:
            continue
        effects.append(EffectEntry(effect_id=candidate.resolved_effect_id, value=candidate.parsed_value))
    return effects[:3]
