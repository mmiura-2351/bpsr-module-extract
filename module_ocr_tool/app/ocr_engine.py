from __future__ import annotations

from dataclasses import dataclass

from module_ocr_tool.app.tesseract_runtime import configure_pytesseract


@dataclass
class TesseractOcrEngine:
    lang: str = "jpn"
    config: str = "--oem 3 --psm 6"
    resize_scale: float = 1.5

    def _load_dependencies(self):
        try:
            import cv2
            import pytesseract
        except ImportError as exc:
            raise RuntimeError(
                "OpenCV と pytesseract が必要です。`pip install opencv-python pytesseract` を実行してください。"
            ) from exc
        configure_pytesseract(pytesseract)
        return cv2, pytesseract

    def preprocess(self, image):
        cv2, _ = self._load_dependencies()
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        denoised = cv2.medianBlur(binary, 3)

        if self.resize_scale and self.resize_scale != 1.0:
            denoised = cv2.resize(denoised, None, fx=self.resize_scale, fy=self.resize_scale, interpolation=cv2.INTER_CUBIC)
        return denoised

    def extract_text(self, image) -> str:
        _, pytesseract = self._load_dependencies()
        preprocessed = self.preprocess(image)
        text = pytesseract.image_to_string(preprocessed, lang=self.lang, config=self.config)
        return text.strip()
