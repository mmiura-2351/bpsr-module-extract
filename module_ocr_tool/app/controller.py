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

    WM_HOTKEY = 0x0312
    PM_REMOVE = 0x0001
    MOD_NOREPEAT = 0x4000
    HOTKEY_ID_F8 = 20001
    HOTKEY_ID_ESC = 20002

    def __init__(self, root: tk.Tk, *, log_path: str | None = None) -> None:
        self.root = root
        self.log_path = log_path
        self.state = AppState()
        self.capture = ScreenCapture()
        self.ocr_engine = TesseractOcrEngine()

        self._effect_regions: list[CaptureRegion | None] = [None, None, None]
        self._processing_token = 0

        self._user32 = self._load_user32()
        self._hotkey_backend = "none"
        self._keyboard_module: Any | None = None
        self._keyboard_hotkey_ids: list[Any] = []
        self._win_hotkeys_registered = False
        self._hotkey_loop_started = False
        self._last_f8_down = False
        self._last_esc_down = False

        self._region_selector: RegionSelectorOverlay | None = None
        self._region_selector_slot = -1

        self.main_window = MainWindow(
            root,
            on_start=self.start_capture_mode,
            on_manual_run=self.run_manual_capture,
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
        if self._win_hotkeys_registered and self._user32 is not None:
            self._user32.UnregisterHotKey(None, self.HOTKEY_ID_F8)
            self._user32.UnregisterHotKey(None, self.HOTKEY_ID_ESC)
            self._win_hotkeys_registered = False
            logger.info("Unregistered Win32 hotkeys")

        if self._keyboard_module is not None:
            for hotkey_id in self._keyboard_hotkey_ids:
                try:
                    self._keyboard_module.remove_hotkey(hotkey_id)
                except Exception:
                    logger.exception("Failed to remove keyboard hotkey id=%s", hotkey_id)
            self._keyboard_hotkey_ids.clear()

    def _load_user32(self) -> Any | None:
        if os.name != "nt":
            return None
        try:
            import ctypes
        except Exception:
            logger.exception("ctypes import failed; Win32 hotkeys disabled")
            return None
        windll = getattr(ctypes, "windll", None)
        if windll is None:
            logger.warning("ctypes.windll unavailable; Win32 hotkeys disabled")
            return None
        return windll.user32

    def run(self) -> None:
        logger.info("Controller run")
        self._register_global_hotkeys()
        self._sync_region_inputs_to_ui()
        self._update_view()

    def _register_global_hotkeys(self) -> None:
        if self._register_win_hotkeys():
            self._hotkey_backend = "register-hotkey"
            logger.info("Global hotkeys registered via Win32 RegisterHotKey")
            return

        if self._register_keyboard_hotkeys():
            self._hotkey_backend = "keyboard"
            logger.info("Global hotkeys registered via keyboard module")
            return

        if self._user32 is not None:
            self._hotkey_backend = "win32-polling"
            logger.warning("Falling back to Win32 polling for global hotkeys")
            self._start_hotkey_polling()
            return

        self._hotkey_backend = "window-only"
        logger.warning("Global hotkeys unavailable; only active when app window is focused")

    def _register_win_hotkeys(self) -> bool:
        if self._user32 is None:
            return False

        ok_f8 = bool(self._user32.RegisterHotKey(None, self.HOTKEY_ID_F8, self.MOD_NOREPEAT, self.VK_F8))
        ok_esc = bool(self._user32.RegisterHotKey(None, self.HOTKEY_ID_ESC, self.MOD_NOREPEAT, self.VK_ESCAPE))
        if ok_f8 and ok_esc:
            self._win_hotkeys_registered = True
            self._start_hotkey_polling()
            return True

        if ok_f8:
            self._user32.UnregisterHotKey(None, self.HOTKEY_ID_F8)
        if ok_esc:
            self._user32.UnregisterHotKey(None, self.HOTKEY_ID_ESC)
        self._win_hotkeys_registered = False
        logger.warning("Win32 RegisterHotKey failed for F8/ESC")
        return False

    def _register_keyboard_hotkeys(self) -> bool:
        try:
            import keyboard  # type: ignore[import-not-found]
        except Exception:
            logger.exception("keyboard import failed")
            return False

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
            return True
        except Exception:
            logger.exception("keyboard hotkey registration failed")
            return False

    def _start_hotkey_polling(self) -> None:
        if self._hotkey_loop_started:
            return
        self._hotkey_loop_started = True
        self.root.after(self.HOTKEY_POLL_INTERVAL_MS, self._poll_hotkeys)

    def _poll_hotkeys(self) -> None:
        try:
            if self._win_hotkeys_registered:
                self._poll_win_hotkey_messages()
            elif self._hotkey_backend == "win32-polling":
                self._poll_win_key_state()
        except Exception:
            logger.exception("Hotkey polling error")
        finally:
            try:
                if self.root.winfo_exists():
                    self.root.after(self.HOTKEY_POLL_INTERVAL_MS, self._poll_hotkeys)
            except tk.TclError:
                return

    def _poll_win_hotkey_messages(self) -> None:
        if self._user32 is None:
            return
        import ctypes
        from ctypes import wintypes

        class MSG(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM),
                ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD),
                ("pt", wintypes.POINT),
            ]

        msg = MSG()
        while self._user32.PeekMessageW(ctypes.byref(msg), None, self.WM_HOTKEY, self.WM_HOTKEY, self.PM_REMOVE):
            if int(msg.wParam) == self.HOTKEY_ID_F8:
                self.on_hotkey_f8(source="register-hotkey")
            elif int(msg.wParam) == self.HOTKEY_ID_ESC:
                self.stop_capture_mode(source="register-hotkey")

    def _poll_win_key_state(self) -> None:
        if self._user32 is None:
            return
        f8_down = self._is_vk_down(self.VK_F8)
        esc_down = self._is_vk_down(self.VK_ESCAPE)
        if f8_down and not self._last_f8_down:
            self.on_hotkey_f8(source="win32-polling")
        if esc_down and not self._last_esc_down:
            self.stop_capture_mode(source="win32-polling")
        self._last_f8_down = f8_down
        self._last_esc_down = esc_down

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
        segments: list[str] = []
        for index, region in enumerate(self._effect_regions, start=1):
            if region is None:
                segments.append(f"範囲{index}:未設定")
            else:
                segments.append(
                    f"範囲{index}:({region['left']},{region['top']},{region['width']},{region['height']})"
                )
        return " / ".join(segments)

    def _hotkey_note(self) -> str:
        if self._hotkey_backend == "register-hotkey":
            return "F8/ESC: グローバル有効（Win32 RegisterHotKey） / OCR実行ボタンでも可"
        if self._hotkey_backend == "keyboard":
            return "F8/ESC: グローバル有効（keyboard） / OCR実行ボタンでも可"
        if self._hotkey_backend == "win32-polling":
            return "F8/ESC: グローバル有効（Win32 polling） / OCR実行ボタンでも可"
        return "F8/ESC は本ウィンドウ選択中のみ有効 / OCR実行ボタン推奨"

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
        self.main_window.set_hotkey_note(self._hotkey_note())

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
        # Hotkey が使えない環境向けに、同一処理を手動ボタンで実行する。
        if self.state.status == "idle":
            self.start_capture_mode()
        if self.state.status == "waiting_capture":
            self.on_hotkey_f8(source="manual-button")
            return
        if self.state.status == "processing":
            self.main_window.show_error("OCR処理中です。完了まで待ってください。")
            return
        if self.state.status == "editing_result":
            self.main_window.show_error("OCR結果確認中です。確定またはキャンセルしてください。")
            return
        self.main_window.show_error("現在はOCR実行できない状態です。")

    def stop_capture_mode(self, _event: tk.Event | None = None, *, source: str = "ui") -> None:
        if self.state.status == "processing":
            self._processing_token += 1
            logger.info("Stop capture requested while processing (token=%s, source=%s)", self._processing_token, source)
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
