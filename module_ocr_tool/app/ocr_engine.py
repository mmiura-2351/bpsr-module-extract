from __future__ import annotations

from dataclasses import dataclass
import logging
import re

from module_ocr_tool.app.tesseract_runtime import configure_pytesseract

logger = logging.getLogger(__name__)


@dataclass
class TesseractOcrEngine:
    lang: str = "jpn"
    config: str = "--oem 3 --psm 6"
    single_line_config: str = "--oem 3 --psm 7"
    resize_scale: float = 1.5
    timeout_sec: float = 12.0

    def _load_dependencies(self):
        try:
            import cv2
            import pytesseract
        except ImportError as exc:
            raise RuntimeError(
                "OpenCV と pytesseract が必要です。`pip install opencv-python pytesseract` を実行してください。"
            ) from exc
        tesseract_cmd = configure_pytesseract(pytesseract)
        logger.debug("OCR dependencies loaded (tesseract_cmd=%s)", tesseract_cmd)
        return cv2, pytesseract

    def preprocess(self, image):
        logger.debug("OCR preprocess start (shape=%s)", getattr(image, "shape", None))
        cv2, _ = self._load_dependencies()
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        denoised = cv2.medianBlur(binary, 3)

        if self.resize_scale and self.resize_scale != 1.0:
            denoised = cv2.resize(denoised, None, fx=self.resize_scale, fy=self.resize_scale, interpolation=cv2.INTER_CUBIC)
        logger.debug("OCR preprocess done (shape=%s)", getattr(denoised, "shape", None))
        return denoised

    def extract_text(self, image, *, config_override: str | None = None) -> str:
        logger.info("OCR extract start")
        _, pytesseract = self._load_dependencies()
        preprocessed = self.preprocess(image)
        config = config_override or self.config
        try:
            text = pytesseract.image_to_string(
                preprocessed,
                lang=self.lang,
                config=config,
                timeout=self.timeout_sec,
            )
        except RuntimeError as exc:
            logger.exception("OCR extract timeout or runtime error")
            raise RuntimeError(f"Tesseract OCR timeout ({self.timeout_sec}秒)") from exc
        result = text.strip()
        logger.info("OCR extract done (chars=%s)", len(result))
        return result

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

        # 1) Whole-area OCR first.
        whole_text = self.extract_text(image)
        add_line(whole_text)
        if len(lines) >= max_effects:
            logger.info("Extract effect texts done via whole-area OCR only (count=%s)", len(lines))
            return lines[:max_effects]

        # 2) Split into N horizontal bands and OCR each band as single-line.
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
