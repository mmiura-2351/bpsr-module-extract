from __future__ import annotations

from dataclasses import dataclass, field
import logging
import re
from threading import Lock
from typing import Any

from module_ocr_tool.app.tesseract_runtime import configure_pytesseract

logger = logging.getLogger(__name__)

VALUE_PATTERN = re.compile(r"\d+")
FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


@dataclass
class _OcrAttempt:
    text: str
    confidence: float
    score: float
    variant_name: str


@dataclass
class TesseractOcrEngine:
    lang: str = "jpn+eng"
    config: str = "--oem 1 --psm 6 -c load_system_dawg=0 -c load_freq_dawg=0"
    single_line_config: str = "--oem 1 --psm 7 -c load_system_dawg=0 -c load_freq_dawg=0"
    value_config: str = "--oem 1 --psm 10 -c tessedit_char_whitelist=0123456789"
    resize_scale: float = 2.0
    timeout_sec: float = 12.0
    label_variant_limit: int = 1
    value_variant_limit: int = 1
    _deps: tuple[Any, Any] | None = field(default=None, init=False, repr=False)
    _deps_lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def _load_dependencies(self):
        if self._deps is not None:
            return self._deps

        with self._deps_lock:
            if self._deps is not None:
                return self._deps
            try:
                import cv2
                import pytesseract
            except ImportError as exc:
                raise RuntimeError(
                    "OpenCV と pytesseract が必要です。`pip install opencv-python pytesseract` を実行してください。"
                ) from exc
            tesseract_cmd = configure_pytesseract(pytesseract)
            logger.debug("OCR dependencies loaded (tesseract_cmd=%s)", tesseract_cmd)
            self._deps = (cv2, pytesseract)
            return self._deps

    def _prepare_preprocess_variants(
        self,
        image: Any,
        *,
        cv2: Any,
        max_variants: int | None = None,
    ) -> list[tuple[str, Any]]:
        def reached_limit(current_count: int) -> bool:
            return max_variants is not None and max_variants > 0 and current_count >= max_variants

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if self.resize_scale and self.resize_scale != 1.0:
            gray = cv2.resize(gray, None, fx=self.resize_scale, fy=self.resize_scale, interpolation=cv2.INTER_CUBIC)

        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
        variants: list[tuple[str, Any]] = []

        _, otsu = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        variants.append(("otsu", otsu))
        if reached_limit(len(variants)):
            logger.debug("Prepared preprocess variants (count=%s)", len(variants))
            return variants

        adaptive = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            4,
        )
        variants.append(("adaptive", adaptive))
        if reached_limit(len(variants)):
            logger.debug("Prepared preprocess variants (count=%s)", len(variants))
            return variants

        _, otsu_inv = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        variants.append(("otsu_inv", otsu_inv))
        logger.debug("Prepared preprocess variants (count=%s)", len(variants))
        return variants

    def _compute_confidence(self, pytesseract: Any, preprocessed: Any, *, lang: str, config: str) -> float:
        try:
            data = pytesseract.image_to_data(
                preprocessed,
                lang=lang,
                config=config,
                timeout=self.timeout_sec,
                output_type=pytesseract.Output.DICT,
            )
        except RuntimeError:
            logger.warning("image_to_data failed while computing confidence")
            return 0.0

        conf_values: list[float] = []
        for raw_conf in data.get("conf", []):
            try:
                parsed = float(raw_conf)
            except (TypeError, ValueError):
                continue
            if parsed >= 0:
                conf_values.append(parsed)
        if not conf_values:
            return 0.0
        return sum(conf_values) / len(conf_values)

    def _extract_with_variant(
        self,
        preprocessed: Any,
        *,
        variant_name: str,
        lang: str,
        config: str,
        pytesseract: Any,
        use_confidence: bool,
    ) -> _OcrAttempt:
        text = pytesseract.image_to_string(
            preprocessed,
            lang=lang,
            config=config,
            timeout=self.timeout_sec,
        ).strip()
        confidence = 0.0
        if use_confidence and text:
            confidence = self._compute_confidence(pytesseract, preprocessed, lang=lang, config=config)
        compact_len = len(re.sub(r"\s+", "", text))
        score = (2.0 if text else 0.0) + (confidence / 100.0) + (min(compact_len, 32) / 32.0)
        return _OcrAttempt(text=text, confidence=confidence, score=score, variant_name=variant_name)

    def extract_text(
        self,
        image,
        *,
        config_override: str | None = None,
        lang_override: str | None = None,
        max_variants: int | None = None,
        use_confidence: bool = True,
    ) -> str:
        logger.info("OCR extract start")
        cv2, pytesseract = self._load_dependencies()
        config = config_override or self.config
        lang = lang_override or self.lang

        variants = self._prepare_preprocess_variants(image, cv2=cv2, max_variants=max_variants)

        attempts: list[_OcrAttempt] = []
        errors: list[Exception] = []
        for variant_name, preprocessed in variants:
            try:
                attempt = self._extract_with_variant(
                    preprocessed,
                    variant_name=variant_name,
                    lang=lang,
                    config=config,
                    pytesseract=pytesseract,
                    use_confidence=use_confidence,
                )
            except RuntimeError as exc:
                errors.append(exc)
                logger.warning("OCR attempt failed (variant=%s)", variant_name)
                continue
            attempts.append(attempt)

        if not attempts:
            logger.exception("OCR extract timeout or runtime error")
            if errors:
                raise RuntimeError(f"Tesseract OCR timeout ({self.timeout_sec}秒)") from errors[0]
            raise RuntimeError(f"Tesseract OCR timeout ({self.timeout_sec}秒)")

        best = max(
            attempts,
            key=lambda attempt: (
                1 if attempt.text else 0,
                attempt.score,
                attempt.confidence,
                len(attempt.text),
            ),
        )
        logger.info(
            "OCR extract done (chars=%s, variant=%s, conf=%.1f)",
            len(best.text),
            best.variant_name,
            best.confidence,
        )
        return best.text

    def _sanitize_effect_label(self, raw_text: str) -> str:
        line = next((chunk.strip() for chunk in raw_text.splitlines() if chunk.strip()), raw_text.strip())
        if not line:
            return ""
        line = line.translate(str.maketrans({"･": "・", "·": "・", "＋": "+", "　": " "}))
        line = re.sub(r"[+＋*＊xX×<＜>＞=~〜]?\s*[0-9０-９]+\s*$", "", line)
        line = re.sub(r"[+＋*＊xX×<＜>＞=~〜?？!！]+$", "", line)
        return line.strip()

    def _parse_value_text(self, raw_text: str) -> int | None:
        normalized = raw_text.translate(FULLWIDTH_DIGITS)
        tokens = VALUE_PATTERN.findall(normalized)
        if not tokens:
            return None

        candidates: list[int] = []
        for token in tokens:
            if len(token) == 1:
                candidates.append(int(token))
                continue
            if token == "10":
                candidates.append(10)
                continue
            if len(token) == 2 and token.startswith("0") and token[1] != "0":
                candidates.append(int(token[1]))

        valid = sorted({value for value in candidates if 1 <= value <= 10})
        if len(valid) != 1:
            return None
        return valid[0]

    def extract_effect_line(self, image) -> str:
        label_text = self.extract_text(
            image,
            config_override=self.single_line_config,
            max_variants=self.label_variant_limit,
            use_confidence=False,
        )
        label = self._sanitize_effect_label(label_text)
        parsed_value = self._parse_value_text(label_text)
        value_text = ""

        # OCR済み行から 1-10 が取れないときだけ、数値専用OCRを追加で実行する。
        if parsed_value is None or parsed_value < 1 or parsed_value > 10:
            value_text = self.extract_text(
                image,
                config_override=self.value_config,
                lang_override="eng",
                max_variants=self.value_variant_limit,
                use_confidence=False,
            )
            parsed_value = self._parse_value_text(value_text)

        if not label:
            combined = ""
        elif parsed_value is not None:
            combined = f"{label}+{parsed_value}"
        else:
            combined = label

        logger.info(
            "Effect OCR done (label=%s, value_text=%s, combined=%s)",
            label or "<empty>",
            value_text or "<empty>",
            combined or "<empty>",
        )
        return combined

    def extract_effect_texts(self, image, *, max_effects: int = 3) -> list[str]:
        logger.info("Extract effect texts start (max_effects=%s)", max_effects)
        lines: list[str] = []
        seen_normalized: set[str] = set()

        def add_line(raw_text: str) -> None:
            for line in raw_text.splitlines():
                cleaned = line.strip()
                if not cleaned:
                    continue
                normalized = re.sub(r"\s+", "", cleaned)
                if not normalized or normalized in seen_normalized:
                    continue
                seen_normalized.add(normalized)
                lines.append(cleaned)
                if len(lines) >= max_effects:
                    return

        whole_text = self.extract_text(image)
        add_line(whole_text)
        if len(lines) >= max_effects:
            logger.info("Extract effect texts done via whole-area OCR only (count=%s)", len(lines))
            return lines[:max_effects]

        image_height = int(getattr(image, "shape", [0])[0]) if getattr(image, "shape", None) is not None else 0
        if image_height <= 0:
            logger.warning("Image height unavailable for multi-band OCR")
            return lines[:max_effects]

        for index in range(max_effects):
            y0 = int(image_height * index / max_effects)
            y1 = int(image_height * (index + 1) / max_effects)
            if y1 <= y0:
                continue
            cropped = image[y0:y1, :]
            band_text = self.extract_text(cropped, config_override=self.single_line_config)
            add_line(band_text)
            if len(lines) >= max_effects:
                break

        logger.info("Extract effect texts done (count=%s, lines=%s)", len(lines), lines[:max_effects])
        return lines[:max_effects]
