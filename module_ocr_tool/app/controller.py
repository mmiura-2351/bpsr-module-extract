from __future__ import annotations

import threading
import tkinter as tk

from module_ocr_tool.app.capture import ScreenCapture
from module_ocr_tool.app.exporter import build_export_payload, write_export_json
from module_ocr_tool.app.models import EffectEntry, ModuleRecord
from module_ocr_tool.app.normalizer import ParsedEffectCandidate, parse_ocr_text
from module_ocr_tool.app.ocr_engine import TesseractOcrEngine
from module_ocr_tool.app.state import AppState
from module_ocr_tool.app.ui.main_window import MainWindow
from module_ocr_tool.app.ui.result_dialog import ResultDialog


class AppController:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.state = AppState()
        self.capture = ScreenCapture()
        self.ocr_engine = TesseractOcrEngine()
        self._global_hotkeys_registered = False

        self.main_window = MainWindow(root, on_start=self.start_capture_mode, on_export=self._handle_export_click)
        self.main_window.pack(fill="both", expand=True, padx=16, pady=16)

        self.root.bind("<F8>", self.on_hotkey_f8)
        self.root.bind("<Escape>", self.stop_capture_mode)

    def run(self) -> None:
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

    def _update_view(self) -> None:
        self.main_window.set_status(self._status_label())
        self.main_window.set_module_count(len(self.state.modules))
        self.main_window.set_last_ocr_text(self.state.last_raw_ocr_text)

    def _register_global_hotkeys(self) -> None:
        if self._global_hotkeys_registered:
            return

        try:
            import keyboard
        except ImportError:
            self.main_window.set_hotkey_note("keyboard 未導入: ウィンドウを選択した状態で F8/ESC を押してください")
            return

        try:
            keyboard.add_hotkey("f8", lambda: self.on_hotkey_f8(None))
            keyboard.add_hotkey("esc", lambda: self.stop_capture_mode(None))
            self._global_hotkeys_registered = True
        except Exception:
            self.main_window.set_hotkey_note("グローバルホットキー登録に失敗: ウィンドウ選択時に F8/ESC を使用してください")

    def start_capture_mode(self) -> None:
        self.state.status = "waiting_capture"
        self.state.last_error_message = None
        self._register_global_hotkeys()
        self._update_view()

    def stop_capture_mode(self, _event: tk.Event | None) -> None:
        self.state.status = "idle"
        self._update_view()

    def on_hotkey_f8(self, _event: tk.Event | None) -> None:
        if self.state.status != "waiting_capture":
            return

        self.state.status = "processing"
        self._update_view()
        worker = threading.Thread(target=self._process_capture_background, daemon=True)
        worker.start()

    def _process_capture_background(self) -> None:
        try:
            image = self.capture.capture()
            raw_text = self.ocr_engine.extract_text(image)
            candidates = parse_ocr_text(raw_text, max_effects=3)
            self.root.after(0, lambda: self._show_result_dialog(candidates, raw_text))
        except Exception as exc:
            self.root.after(0, lambda: self._handle_error(f"OCR処理に失敗しました: {exc}"))

    def _show_result_dialog(self, candidates: list[ParsedEffectCandidate], raw_text: str) -> None:
        self.state.status = "editing_result"
        self.state.last_raw_ocr_text = raw_text
        self._update_view()
        ResultDialog(
            self.root,
            candidates,
            on_confirm=self.confirm_module,
            on_cancel=self._cancel_result_edit,
        )

    def _cancel_result_edit(self) -> None:
        self.state.status = "waiting_capture"
        self._update_view()

    def confirm_module(self, effects: list[EffectEntry]) -> None:
        module = ModuleRecord(module_category="general", effects=effects[:3])
        self.state.modules.append(module)
        self.state.status = "waiting_capture"
        self._update_view()

    def _handle_export_click(self) -> None:
        output_path = self.main_window.ask_export_path()
        if not output_path:
            return

        try:
            self.export_json(output_path)
        except Exception as exc:
            self._handle_error(f"JSON出力に失敗しました: {exc}")
            return

        self.main_window.show_info(f"JSONを出力しました:\n{output_path}")

    def export_json(self, output_path: str) -> None:
        payload = build_export_payload(self.state.modules)
        write_export_json(payload, output_path)

    def _handle_error(self, message: str) -> None:
        self.state.status = "error"
        self.state.last_error_message = message
        self.main_window.show_error(message)
        self.state.status = "waiting_capture"
        self._update_view()
