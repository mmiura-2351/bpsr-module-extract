from __future__ import annotations

import logging
import os
import threading
import time
import tkinter as tk
from typing import Any

from module_ocr_tool.app.capture import CaptureRegion, ScreenCapture
from module_ocr_tool.app.exporter import build_export_payload, write_export_json
from module_ocr_tool.app.models import EffectEntry, ModuleRecord
from module_ocr_tool.app.normalizer import ParsedEffectCandidate, parse_ocr_text
from module_ocr_tool.app.ocr_engine import TesseractOcrEngine
from module_ocr_tool.app.state import AppState
from module_ocr_tool.app.ui.main_window import MainWindow
from module_ocr_tool.app.ui.region_selector import RegionSelectorOverlay
from module_ocr_tool.app.ui.result_dialog import ResultDialog

logger = logging.getLogger(__name__)


class AppController:
    HOTKEY_POLL_INTERVAL_MS = 50
    VK_F8 = 0x77
    VK_ESCAPE = 0x1B

    def __init__(self, root: tk.Tk, *, log_path: str | None = None) -> None:
        self.root = root
        self.log_path = log_path
        self.state = AppState()
        self.capture = ScreenCapture()
        self.ocr_engine = TesseractOcrEngine()

        self._processing_token = 0

        self._keyboard_module: Any | None = None
        self._keyboard_hotkey_ids: list[Any] = []
        self._hotkey_backend = "none"

        self._hotkey_polling_started = False
        self._last_f8_down = False
        self._last_esc_down = False
        self._user32 = self._load_user32()

        self._region_selector: RegionSelectorOverlay | None = None

        self.main_window = MainWindow(
            root,
            on_start=self.start_capture_mode,
            on_export=self._handle_export_click,
            on_apply_region=self.apply_capture_region_from_ui,
            on_drag_select_region=self.open_region_selector,
        )
        self.main_window.pack(fill="both", expand=True, padx=16, pady=16)

        self.root.bind("<F8>", self.on_hotkey_f8)
        self.root.bind("<Escape>", self.stop_capture_mode)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        logger.info("Controller initialized (platform=%s, log_path=%s)", os.name, self.log_path)

    def _on_close(self) -> None:
        logger.info("Application closing")
        self._cleanup_hotkeys()
        self.root.destroy()

    def _cleanup_hotkeys(self) -> None:
        if self._keyboard_module is None:
            return
        for hotkey_id in self._keyboard_hotkey_ids:
            try:
                self._keyboard_module.remove_hotkey(hotkey_id)
            except Exception:
                logger.exception("Failed to remove hotkey id=%s", hotkey_id)
        self._keyboard_hotkey_ids.clear()

    def _load_user32(self) -> Any | None:
        if os.name != "nt":
            return None
        try:
            import ctypes
        except Exception:
            logger.exception("ctypes import failed; win32 polling disabled")
            return None
        windll = getattr(ctypes, "windll", None)
        if windll is None:
            logger.warning("ctypes.windll unavailable; win32 polling disabled")
            return None
        return windll.user32

    def run(self) -> None:
        logger.info("Controller run")
        self._register_global_hotkeys()
        self._update_view()

    def _register_global_hotkeys(self) -> None:
        if self._keyboard_hotkey_ids:
            return

        try:
            import keyboard  # type: ignore[import-not-found]
        except Exception:
            logger.exception("keyboard import failed")
        else:
            try:
                f8_id = keyboard.add_hotkey(
                    "f8",
                    lambda: self.root.after(0, lambda: self.on_hotkey_f8(source="global-keyboard")),
                    suppress=False,
                    trigger_on_release=False,
                )
                esc_id = keyboard.add_hotkey(
                    "esc",
                    lambda: self.root.after(0, lambda: self.stop_capture_mode(source="global-keyboard")),
                    suppress=False,
                    trigger_on_release=False,
                )
                self._keyboard_module = keyboard
                self._keyboard_hotkey_ids = [f8_id, esc_id]
                self._hotkey_backend = "keyboard"
                logger.info("Global hotkeys registered via keyboard module")
                return
            except Exception:
                logger.exception("keyboard global hotkey registration failed")

        if self._user32 is not None:
            self._hotkey_backend = "win32-polling"
            logger.warning("Falling back to Win32 polling for global hotkeys")
            self._start_hotkey_polling()
            return

        self._hotkey_backend = "window-only"
        logger.warning("Global hotkeys unavailable; only active when app window is focused")

    def _start_hotkey_polling(self) -> None:
        if self._hotkey_polling_started:
            return
        self._hotkey_polling_started = True
        logger.info("Start win32 hotkey polling")
        self.root.after(self.HOTKEY_POLL_INTERVAL_MS, self._poll_global_hotkeys)

    def _poll_global_hotkeys(self) -> None:
        try:
            if self._user32 is not None:
                f8_down = self._is_vk_down(self.VK_F8)
                esc_down = self._is_vk_down(self.VK_ESCAPE)
                if f8_down and not self._last_f8_down:
                    self.on_hotkey_f8(source="win32-polling")
                if esc_down and not self._last_esc_down:
                    self.stop_capture_mode(source="win32-polling")
                self._last_f8_down = f8_down
                self._last_esc_down = esc_down
        finally:
            self.root.after(self.HOTKEY_POLL_INTERVAL_MS, self._poll_global_hotkeys)

    def _is_vk_down(self, virtual_key: int) -> bool:
        if self._user32 is None:
            return False
        state = self._user32.GetAsyncKeyState(virtual_key)
        return bool(state & 0x8000)

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
        if self.capture.region is None:
            return "全画面"
        return (
            f"left={self.capture.region['left']}, "
            f"top={self.capture.region['top']}, "
            f"width={self.capture.region['width']}, "
            f"height={self.capture.region['height']}"
        )

    def _hotkey_note(self) -> str:
        if self._hotkey_backend == "keyboard":
            return "F8/ESC: グローバル有効（別ウィンドウでも動作）"
        if self._hotkey_backend == "win32-polling":
            return "F8/ESC: グローバル有効（Win32 polling）"
        return "F8/ESC は本ウィンドウ選択中のみ有効"

    def _update_view(self) -> None:
        self.main_window.set_status(self._status_label())
        self.main_window.set_module_count(len(self.state.modules))
        self.main_window.set_last_ocr_text(self.state.last_raw_ocr_text)
        self.main_window.set_log_path(self.log_path or "-")
        self.main_window.set_region_summary(self._format_region_summary())
        self.main_window.set_hotkey_note(self._hotkey_note())

    def apply_capture_region_from_ui(
        self,
        use_custom_region: bool,
        left_text: str,
        top_text: str,
        width_text: str,
        height_text: str,
    ) -> None:
        logger.info(
            "Apply capture region requested (custom=%s, left=%s, top=%s, width=%s, height=%s)",
            use_custom_region,
            left_text,
            top_text,
            width_text,
            height_text,
        )
        if not use_custom_region:
            self.capture.region = None
            logger.info("Capture region set to full screen")
            self._update_view()
            return

        try:
            left = int(left_text.strip())
            top = int(top_text.strip())
            width = int(width_text.strip())
            height = int(height_text.strip())
        except ValueError:
            logger.warning("Invalid capture region input: non-integer value")
            self.main_window.show_error("OCR取得範囲は整数で入力してください。")
            return

        if width <= 0 or height <= 0:
            logger.warning("Invalid capture region input: width/height must be positive")
            self.main_window.show_error("width と height は 1 以上を指定してください。")
            return
        if left < 0 or top < 0:
            logger.warning("Invalid capture region input: left/top must be non-negative")
            self.main_window.show_error("left と top は 0 以上を指定してください。")
            return

        self._apply_capture_region(left=left, top=top, width=width, height=height, source="manual-input")

    def _apply_capture_region(self, *, left: int, top: int, width: int, height: int, source: str) -> None:
        region: CaptureRegion = {
            "left": left,
            "top": top,
            "width": width,
            "height": height,
        }
        self.capture.region = region
        self.main_window.set_region_inputs(use_custom=True, left=left, top=top, width=width, height=height)
        logger.info("Capture region applied via %s: %s", source, region)
        self._update_view()

    def open_region_selector(self) -> None:
        if self.state.status == "processing":
            self.main_window.show_error("OCR処理中は範囲選択できません。")
            return

        if self._region_selector is not None and self._region_selector.winfo_exists():
            logger.info("Region selector already open")
            return

        logger.info("Open drag region selector")
        self._region_selector = RegionSelectorOverlay(
            self.root,
            on_selected=self._on_region_selected_by_drag,
            on_cancel=self._on_region_select_canceled,
        )

    def _on_region_selected_by_drag(self, left: int, top: int, width: int, height: int) -> None:
        self._region_selector = None
        self._apply_capture_region(left=left, top=top, width=width, height=height, source="drag-select")

    def _on_region_select_canceled(self) -> None:
        self._region_selector = None
        logger.info("Region selector canceled")

    def start_capture_mode(self) -> None:
        self._set_status("waiting_capture", reason="start capture mode")
        self.state.last_error_message = None
        self._update_view()

    def stop_capture_mode(self, _event: tk.Event | None = None, *, source: str = "ui") -> None:
        if self.state.status == "processing":
            self._processing_token += 1
            logger.info(
                "Stop capture mode requested while processing; token incremented to %s (source=%s)",
                self._processing_token,
                source,
            )
        self._set_status("idle", reason=f"stop capture mode ({source})")
        self._update_view()

    def on_hotkey_f8(self, _event: tk.Event | None = None, *, source: str = "ui") -> None:
        if self.state.status != "waiting_capture":
            logger.debug("F8 ignored in status=%s source=%s", self.state.status, source)
            return

        self._set_status("processing", reason=f"F8 pressed ({source})")
        self._update_view()

        self._processing_token += 1
        token = self._processing_token
        timeout_ms = max(int(self.ocr_engine.timeout_sec * 1000) + 3000, 8000)
        logger.info(
            "Processing started (token=%s, timeout_ms=%s, region=%s, source=%s)",
            token,
            timeout_ms,
            self.capture.region,
            source,
        )
        self.root.after(timeout_ms, lambda: self._handle_processing_timeout(token))

        worker = threading.Thread(target=self._process_capture_background, args=(token,), daemon=True)
        worker.start()

    def _process_capture_background(self, token: int) -> None:
        started = time.monotonic()
        try:
            logger.info("Capture thread start (token=%s)", token)
            image = self.capture.capture()
            logger.info("Capture complete (token=%s, shape=%s)", token, getattr(image, "shape", None))
            extracted_lines = self.ocr_engine.extract_effect_texts(image, max_effects=3)
            raw_text = "\n".join(extracted_lines)
            candidates = parse_ocr_text(raw_text, max_effects=3)
            elapsed = time.monotonic() - started
            logger.info(
                "Processing success (token=%s, elapsed_sec=%.3f, raw_len=%s, extracted_lines=%s, candidates=%s)",
                token,
                elapsed,
                len(raw_text),
                len(extracted_lines),
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
        self.state.modules.append(module)
        logger.info("Module confirmed (effects=%s, modules_total=%s)", len(module.effects), len(self.state.modules))
        self._set_status("waiting_capture", reason="module confirmed")
        self._update_view()

    def _handle_export_click(self) -> None:
        output_path = self.main_window.ask_export_path()
        if not output_path:
            logger.info("Export canceled by user")
            return

        try:
            self.export_json(output_path)
        except Exception as exc:
            self._handle_error(f"JSON出力に失敗しました: {exc}")
            return

        self.main_window.show_info(f"JSONを出力しました:\n{output_path}")
        logger.info("Export completed: %s", output_path)

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
