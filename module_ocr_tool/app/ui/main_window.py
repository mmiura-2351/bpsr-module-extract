from __future__ import annotations

import logging
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable

logger = logging.getLogger(__name__)


class MainWindow(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        on_start: Callable[[], None],
        on_export: Callable[[], None],
        on_apply_region: Callable[[bool, str, str, str, str], None],
        on_drag_select_region: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self._on_start = on_start
        self._on_export = on_export
        self._on_apply_region = on_apply_region
        self._on_drag_select_region = on_drag_select_region

        self.status_var = tk.StringVar(value="待機中")
        self.module_count_var = tk.StringVar(value="0")
        self.hotkey_note_var = tk.StringVar(value="F8: スクリーンショット取得 / ESC: 終了")
        self.log_path_var = tk.StringVar(value="-")
        self.region_summary_var = tk.StringVar(value="全画面")
        self.last_ocr_var = tk.StringVar(value="-")
        self.use_custom_region_var = tk.BooleanVar(value=False)
        self.region_left_var = tk.StringVar(value="0")
        self.region_top_var = tk.StringVar(value="0")
        self.region_width_var = tk.StringVar(value="1280")
        self.region_height_var = tk.StringVar(value="720")

        self._build()

    def _build(self) -> None:
        title = ttk.Label(self, text="Module OCR Tool", font=("", 16, "bold"))
        title.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

        start_button = ttk.Button(self, text="処理開始", command=self._on_start)
        start_button.grid(row=1, column=0, sticky="w")

        export_button = ttk.Button(self, text="JSON出力", command=self._on_export)
        export_button.grid(row=1, column=1, sticky="e")

        ttk.Separator(self).grid(row=2, column=0, columnspan=2, sticky="ew", pady=12)

        ttk.Label(self, text="状態:").grid(row=3, column=0, sticky="w")
        ttk.Label(self, textvariable=self.status_var).grid(row=3, column=1, sticky="w")

        ttk.Label(self, text="取得モジュール数:").grid(row=4, column=0, sticky="w")
        ttk.Label(self, textvariable=self.module_count_var).grid(row=4, column=1, sticky="w")

        ttk.Label(self, text="操作:").grid(row=5, column=0, sticky="w")
        ttk.Label(self, textvariable=self.hotkey_note_var).grid(row=5, column=1, sticky="w")

        ttk.Label(self, text="ログファイル:").grid(row=6, column=0, sticky="w")
        ttk.Label(self, textvariable=self.log_path_var, wraplength=420).grid(row=6, column=1, sticky="w")

        region_frame = ttk.LabelFrame(self, text="OCR取得範囲 (px)")
        region_frame.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        region_frame.grid_columnconfigure(1, weight=1)
        region_frame.grid_columnconfigure(3, weight=1)

        ttk.Checkbutton(region_frame, text="カスタム範囲を使用", variable=self.use_custom_region_var).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 4)
        )

        ttk.Label(region_frame, text="left").grid(row=1, column=0, sticky="w")
        ttk.Entry(region_frame, textvariable=self.region_left_var, width=10).grid(row=1, column=1, sticky="w", padx=(0, 8))
        ttk.Label(region_frame, text="top").grid(row=1, column=2, sticky="w")
        ttk.Entry(region_frame, textvariable=self.region_top_var, width=10).grid(row=1, column=3, sticky="w")

        ttk.Label(region_frame, text="width").grid(row=2, column=0, sticky="w")
        ttk.Entry(region_frame, textvariable=self.region_width_var, width=10).grid(row=2, column=1, sticky="w", padx=(0, 8))
        ttk.Label(region_frame, text="height").grid(row=2, column=2, sticky="w")
        ttk.Entry(region_frame, textvariable=self.region_height_var, width=10).grid(row=2, column=3, sticky="w")

        ttk.Button(region_frame, text="範囲を適用", command=self._emit_apply_region).grid(
            row=3, column=3, sticky="e", pady=(6, 2)
        )
        ttk.Button(region_frame, text="ドラッグ選択", command=self._on_drag_select_region).grid(
            row=3, column=2, sticky="e", pady=(6, 2), padx=(0, 6)
        )
        ttk.Label(region_frame, textvariable=self.region_summary_var).grid(row=3, column=0, columnspan=3, sticky="w")

        ttk.Label(self, text="直近OCR生テキスト:").grid(row=8, column=0, sticky="nw", pady=(8, 0))
        ttk.Label(self, textvariable=self.last_ocr_var, wraplength=420).grid(row=8, column=1, sticky="w", pady=(8, 0))

        for col in range(2):
            self.grid_columnconfigure(col, weight=1)

    def _emit_apply_region(self) -> None:
        self._on_apply_region(
            self.use_custom_region_var.get(),
            self.region_left_var.get(),
            self.region_top_var.get(),
            self.region_width_var.get(),
            self.region_height_var.get(),
        )

    def set_status(self, status: str) -> None:
        self.status_var.set(status)

    def set_module_count(self, count: int) -> None:
        self.module_count_var.set(str(count))

    def set_hotkey_note(self, note: str) -> None:
        self.hotkey_note_var.set(note)

    def set_log_path(self, path: str) -> None:
        self.log_path_var.set(path)

    def set_region_summary(self, summary: str) -> None:
        self.region_summary_var.set(summary)

    def set_region_inputs(self, *, use_custom: bool, left: int, top: int, width: int, height: int) -> None:
        self.use_custom_region_var.set(use_custom)
        self.region_left_var.set(str(left))
        self.region_top_var.set(str(top))
        self.region_width_var.set(str(width))
        self.region_height_var.set(str(height))

    def set_last_ocr_text(self, text: str | None) -> None:
        display = text.strip() if text else "-"
        self.last_ocr_var.set(display)

    def ask_export_path(self) -> str:
        return filedialog.asksaveasfilename(
            title="JSON出力先を選択",
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )

    def show_info(self, message: str) -> None:
        logger.info("Show info dialog: %s", message.replace("\n", " "))
        messagebox.showinfo("Module OCR Tool", message)

    def show_error(self, message: str) -> None:
        logger.error("Show error dialog: %s", message.replace("\n", " "))
        messagebox.showerror("Module OCR Tool", message)
