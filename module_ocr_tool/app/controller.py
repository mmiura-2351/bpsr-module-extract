from __future__ import annotations

import logging
import threading
import time
import tkinter as tk

from module_ocr_tool.app.config_store import load_app_config, save_app_config
from module_ocr_tool.app.capture import CaptureRegion, ScreenCapture
from module_ocr_tool.app.exporter import (
    append_modules_to_existing_json,
    build_export_payload,
    is_duplicate_module,
    write_export_json,
)
from module_ocr_tool.app.models import EffectEntry, ModuleRecord
from module_ocr_tool.app.normalizer import ParsedEffectCandidate, parse_ocr_text
from module_ocr_tool.app.ocr_engine import TesseractOcrEngine
from module_ocr_tool.app.state import AppState
from module_ocr_tool.app.ui.main_window import MainWindow
from module_ocr_tool.app.ui.region_selector import RegionSelectorOverlay
from module_ocr_tool.app.ui.result_dialog import ResultDialog

logger = logging.getLogger(__name__)


class AppController:
    def __init__(self, root: tk.Tk, *, log_path: str | None = None) -> None:
        self.root = root
        self.log_path = log_path
        self._config, self._config_path = load_app_config()
        self.state = AppState()
        self.capture = ScreenCapture()
        self.ocr_engine = TesseractOcrEngine()

        loaded_regions = list(self._config.effect_regions)
        self._effect_regions: list[CaptureRegion | None] = (loaded_regions + [None, None, None])[:3]
        self._processing_token = 0

        self._region_selector: RegionSelectorOverlay | None = None
        self._region_selector_slot = -1

        self.main_window = MainWindow(
            root,
            on_start=self.start_capture_mode,
            on_manual_run=self.run_manual_capture,
            on_export=self._handle_export_click,
            on_update_export=self._handle_update_export_click,
            on_apply_region=self.apply_capture_region_from_ui,
            on_drag_select_region=self.open_region_selector,
        )
        self.main_window.pack(fill="both", expand=True, padx=16, pady=16)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        logger.info("Controller initialized (log_path=%s, config_path=%s)", self.log_path, self._config_path)

    def _on_close(self) -> None:
        logger.info("Application closing")
        self._save_config()
        self.root.destroy()

    def _save_config(self) -> None:
        try:
            self._config.effect_regions = [
                (
                    {
                        "left": region["left"],
                        "top": region["top"],
                        "width": region["width"],
                        "height": region["height"],
                    }
                    if region is not None
                    else None
                )
                for region in self._effect_regions
            ]
            save_app_config(self._config, self._config_path)
        except Exception:
            logger.exception("Failed to save config: %s", self._config_path)

    def run(self) -> None:
        logger.info("Controller run")
        self._sync_region_inputs_to_ui()
        self._update_view()

    def _status_label(self) -> str:
        labels = {
            "idle": "待機中",
            "waiting_capture": "キャプチャ待機中",
            "processing": "OCR処理中",
            "editing_result": "OCR結果確認中",
            "error": "エラー",
        }
        return labels.get(self.state.status, self.state.status)

    def _set_status(self, status: str, *, reason: str) -> None:
        previous = self.state.status
        self.state.status = status
        if previous != status:
            logger.info("Status: %s -> %s (%s)", previous, status, reason)

    def _format_region_summary(self) -> str:
        segments: list[str] = []
        for index, region in enumerate(self._effect_regions, start=1):
            if region is None:
                segments.append(f"範囲{index}:未設定")
            else:
                segments.append(
                    f"範囲{index}:({region['left']},{region['top']},{region['width']},{region['height']})"
                )
        return " / ".join(segments)

    def _operation_note(self) -> str:
        return "OCR実行ボタンを使用してください。"

    def _sync_region_inputs_to_ui(self) -> None:
        for index, region in enumerate(self._effect_regions):
            if region is None:
                self.main_window.set_region_inputs(index, enabled=False, left=0, top=0, width=240, height=40)
            else:
                self.main_window.set_region_inputs(
                    index,
                    enabled=True,
                    left=region["left"],
                    top=region["top"],
                    width=region["width"],
                    height=region["height"],
                )

    def _update_view(self) -> None:
        self.main_window.set_status(self._status_label())
        self.main_window.set_module_count(len(self.state.modules))
        self.main_window.set_last_ocr_text(self.state.last_raw_ocr_text)
        self.main_window.set_log_path(self.log_path or "-")
        self.main_window.set_region_summary(self._format_region_summary())
        self.main_window.set_hotkey_note(self._operation_note())

    def apply_capture_region_from_ui(
        self,
        slot_index: int,
        use_custom_region: bool,
        left_text: str,
        top_text: str,
        width_text: str,
        height_text: str,
    ) -> None:
        if slot_index < 0 or slot_index >= len(self._effect_regions):
            return

        logger.info(
            "Apply capture region requested (slot=%s, custom=%s, left=%s, top=%s, width=%s, height=%s)",
            slot_index + 1,
            use_custom_region,
            left_text,
            top_text,
            width_text,
            height_text,
        )
        if not use_custom_region:
            self._effect_regions[slot_index] = None
            self.main_window.set_region_inputs(slot_index, enabled=False, left=0, top=0, width=240, height=40)
            self._save_config()
            self._update_view()
            return

        try:
            left = int(left_text.strip())
            top = int(top_text.strip())
            width = int(width_text.strip())
            height = int(height_text.strip())
        except ValueError:
            self.main_window.show_error("OCR取得範囲は整数で入力してください。")
            return

        if width <= 0 or height <= 0:
            self.main_window.show_error("width と height は 1 以上を指定してください。")
            return
        if left < 0 or top < 0:
            self.main_window.show_error("left と top は 0 以上を指定してください。")
            return

        self._apply_capture_region(slot_index, left=left, top=top, width=width, height=height, source="manual-input")

    def _apply_capture_region(
        self,
        slot_index: int,
        *,
        left: int,
        top: int,
        width: int,
        height: int,
        source: str,
    ) -> None:
        region: CaptureRegion = {
            "left": left,
            "top": top,
            "width": width,
            "height": height,
        }
        self._effect_regions[slot_index] = region
        self.main_window.set_region_inputs(
            slot_index,
            enabled=True,
            left=left,
            top=top,
            width=width,
            height=height,
        )
        logger.info("Capture region applied via %s (slot=%s): %s", source, slot_index + 1, region)
        self._save_config()
        self._update_view()

    def open_region_selector(self, slot_index: int) -> None:
        if self.state.status == "processing":
            self.main_window.show_error("OCR処理中は範囲選択できません。")
            return
        if slot_index < 0 or slot_index >= len(self._effect_regions):
            return

        if self._region_selector is not None and self._region_selector.winfo_exists():
            logger.info("Region selector already open")
            return

        self._region_selector_slot = slot_index
        logger.info("Open drag region selector (slot=%s)", slot_index + 1)
        self._region_selector = RegionSelectorOverlay(
            self.root,
            on_selected=self._on_region_selected_by_drag,
            on_cancel=self._on_region_select_canceled,
        )

    def _on_region_selected_by_drag(self, left: int, top: int, width: int, height: int) -> None:
        slot_index = self._region_selector_slot
        self._region_selector = None
        self._region_selector_slot = -1
        if slot_index < 0 or slot_index >= len(self._effect_regions):
            return
        self._apply_capture_region(slot_index, left=left, top=top, width=width, height=height, source="drag-select")

    def _on_region_select_canceled(self) -> None:
        self._region_selector = None
        self._region_selector_slot = -1
        logger.info("Region selector canceled")

    def start_capture_mode(self) -> None:
        self._set_status("waiting_capture", reason="start capture mode")
        self.state.last_error_message = None
        self._update_view()

    def run_manual_capture(self) -> None:
        if self.state.status == "idle":
            self.start_capture_mode()
        if self.state.status == "waiting_capture":
            self._start_processing(source="manual-button")
            return
        if self.state.status == "processing":
            self.main_window.show_error("OCR処理中です。完了まで待ってください。")
            return
        if self.state.status == "editing_result":
            self.main_window.show_error("OCR結果確認中です。確定またはキャンセルしてください。")
            return
        self.main_window.show_error("現在はOCR実行できない状態です。")

    def _start_processing(self, *, source: str) -> None:
        if self.state.status != "waiting_capture":
            return

        self._set_status("processing", reason=f"OCR run ({source})")
        self._update_view()

        self._processing_token += 1
        token = self._processing_token
        timeout_ms = max(int(self.ocr_engine.timeout_sec * 1000) + 3000, 8000)
        logger.info("Processing started (token=%s, timeout_ms=%s, source=%s)", token, timeout_ms, source)
        self.root.after(timeout_ms, lambda: self._handle_processing_timeout(token))

        worker = threading.Thread(target=self._process_capture_background, args=(token,), daemon=True)
        worker.start()

    def _extract_single_effect_line(self, image) -> str:
        text = self.ocr_engine.extract_text(image, config_override=self.ocr_engine.single_line_config)
        for line in text.splitlines():
            cleaned = line.strip()
            if cleaned:
                return cleaned
        fallback = self.ocr_engine.extract_effect_texts(image, max_effects=1)
        return fallback[0] if fallback else ""

    def _process_capture_background(self, token: int) -> None:
        started = time.monotonic()
        try:
            logger.info("Capture thread start (token=%s)", token)

            lines: list[str] = []
            configured = [(index, region) for index, region in enumerate(self._effect_regions, start=1) if region is not None]

            if configured:
                logger.info("Using configured effect regions (count=%s)", len(configured))
                for index, region in configured[:3]:
                    image = self.capture.capture(region_override=region)
                    line = self._extract_single_effect_line(image)
                    if line:
                        lines.append(line)
                    logger.info("Region OCR done (slot=%s, line=%s)", index, line or "<empty>")
            else:
                image = self.capture.capture()
                lines = self.ocr_engine.extract_effect_texts(image, max_effects=3)
                logger.info("Whole-area OCR done (lines=%s)", len(lines))

            raw_text = "\n".join(lines)
            candidates = parse_ocr_text(raw_text, max_effects=3)
            elapsed = time.monotonic() - started
            logger.info(
                "Processing success (token=%s, elapsed_sec=%.3f, raw_len=%s, lines=%s, candidates=%s)",
                token,
                elapsed,
                len(raw_text),
                len(lines),
                len(candidates),
            )
            self.root.after(0, lambda: self._handle_processing_success(token, candidates, raw_text))
        except Exception as exc:
            elapsed = time.monotonic() - started
            logger.exception("Processing failed (token=%s, elapsed_sec=%.3f)", token, elapsed)
            self.root.after(0, lambda: self._handle_processing_error(token, f"OCR処理に失敗しました: {exc}"))

    def _handle_processing_timeout(self, token: int) -> None:
        if token != self._processing_token or self.state.status != "processing":
            return
        self._processing_token += 1
        logger.error("Processing timeout (token=%s)", token)
        self._handle_error("OCR処理がタイムアウトしました。OCR取得範囲を狭めて再実行してください。")

    def _handle_processing_success(
        self,
        token: int,
        candidates: list[ParsedEffectCandidate],
        raw_text: str,
    ) -> None:
        if token != self._processing_token or self.state.status != "processing":
            logger.info("Ignore stale success callback (token=%s, current=%s)", token, self._processing_token)
            return
        self._show_result_dialog(candidates, raw_text)

    def _handle_processing_error(self, token: int, message: str) -> None:
        if token != self._processing_token or self.state.status != "processing":
            logger.info("Ignore stale error callback (token=%s, current=%s)", token, self._processing_token)
            return
        self._handle_error(message)

    def _show_result_dialog(self, candidates: list[ParsedEffectCandidate], raw_text: str) -> None:
        self._set_status("editing_result", reason="processing success")
        self.state.last_raw_ocr_text = raw_text
        self._update_view()
        ResultDialog(
            self.root,
            candidates,
            on_confirm=self.confirm_module,
            on_cancel=self._cancel_result_edit,
        )

    def _cancel_result_edit(self) -> None:
        self._set_status("waiting_capture", reason="result edit canceled")
        self._update_view()

    def confirm_module(self, effects: list[EffectEntry]) -> None:
        module = ModuleRecord(module_category="general", effects=effects[:3])
        if is_duplicate_module(module, self.state.modules):
            logger.info("Duplicate module detected. Skip append.")
            self.main_window.show_info("既存モジュールと重複しているため追加をスキップしました。")
            self._set_status("waiting_capture", reason="duplicate module skipped")
            self._update_view()
            return
        self.state.modules.append(module)
        logger.info("Module confirmed (effects=%s, modules_total=%s)", len(module.effects), len(self.state.modules))
        self._set_status("waiting_capture", reason="module confirmed")
        self._update_view()

    def _handle_export_click(self) -> None:
        output_path = self.main_window.ask_export_path(initial_path=self._config.last_export_path)
        if not output_path:
            logger.info("Export canceled by user")
            return

        try:
            self.export_json(output_path)
        except Exception as exc:
            self._handle_error(f"JSON出力に失敗しました: {exc}")
            return

        self._config.last_export_path = output_path
        self._save_config()
        self.main_window.show_info(f"JSONを出力しました:\n{output_path}")
        logger.info("Export completed: %s", output_path)

    def _handle_update_export_click(self) -> None:
        existing_path = self.main_window.ask_existing_json_path(initial_path=self._config.last_update_json_path)
        if not existing_path:
            logger.info("Update export canceled by user")
            return

        try:
            added, skipped, total = append_modules_to_existing_json(existing_path, self.state.modules)
        except Exception as exc:
            self._handle_error(f"既存JSON更新に失敗しました: {exc}")
            return

        self._config.last_update_json_path = existing_path
        self._save_config()
        self.main_window.show_info(
            "既存JSONを更新しました:\n"
            f"{existing_path}\n"
            f"追加: {added} / 重複・空: {skipped} / 合計: {total}"
        )
        logger.info(
            "Existing JSON updated (path=%s, added=%s, skipped=%s, total=%s)",
            existing_path,
            added,
            skipped,
            total,
        )

    def export_json(self, output_path: str) -> None:
        payload = build_export_payload(self.state.modules)
        logger.info("Export start (modules=%s, output=%s)", len(self.state.modules), output_path)
        write_export_json(payload, output_path)

    def _handle_error(self, message: str) -> None:
        self._set_status("error", reason="error raised")
        self.state.last_error_message = message
        logger.error("Error: %s", message)
        self.main_window.show_error(message)
        self._set_status("waiting_capture", reason="error dialog closed")
        self._update_view()
