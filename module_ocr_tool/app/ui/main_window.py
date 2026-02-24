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
        on_apply_region: Callable[[int, bool, str, str, str, str], None],
        on_drag_select_region: Callable[[int], None],
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
        self.region_summary_var = tk.StringVar(value="範囲1:未設定 / 範囲2:未設定 / 範囲3:未設定")
        self.last_ocr_var = tk.StringVar(value="-")

        self.region_enabled_vars: list[tk.BooleanVar] = []
        self.region_left_vars: list[tk.StringVar] = []
        self.region_top_vars: list[tk.StringVar] = []
        self.region_width_vars: list[tk.StringVar] = []
        self.region_height_vars: list[tk.StringVar] = []

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
        ttk.Label(self, textvariable=self.log_path_var, wraplength=520).grid(row=6, column=1, sticky="w")

        region_frame = ttk.LabelFrame(self, text="OCR取得範囲 (3枠)")
        region_frame.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        headers = ["範囲", "left", "top", "width", "height", "選択", "適用"]
        for col, header in enumerate(headers):
            ttk.Label(region_frame, text=header).grid(row=0, column=col, sticky="w", padx=(0, 6))

        for index in range(3):
            enabled_var = tk.BooleanVar(value=False)
            left_var = tk.StringVar(value="0")
            top_var = tk.StringVar(value="0")
            width_var = tk.StringVar(value="240")
            height_var = tk.StringVar(value="40")

            self.region_enabled_vars.append(enabled_var)
            self.region_left_vars.append(left_var)
            self.region_top_vars.append(top_var)
            self.region_width_vars.append(width_var)
            self.region_height_vars.append(height_var)

            row = index + 1
            ttk.Checkbutton(region_frame, text=f"範囲{index + 1}", variable=enabled_var).grid(
                row=row, column=0, sticky="w", padx=(0, 6), pady=2
            )
            ttk.Entry(region_frame, textvariable=left_var, width=8).grid(row=row, column=1, sticky="w", padx=(0, 6), pady=2)
            ttk.Entry(region_frame, textvariable=top_var, width=8).grid(row=row, column=2, sticky="w", padx=(0, 6), pady=2)
            ttk.Entry(region_frame, textvariable=width_var, width=8).grid(row=row, column=3, sticky="w", padx=(0, 6), pady=2)
            ttk.Entry(region_frame, textvariable=height_var, width=8).grid(row=row, column=4, sticky="w", padx=(0, 6), pady=2)
            ttk.Button(region_frame, text="ドラッグ", command=lambda i=index: self._emit_drag_select(i)).grid(
                row=row, column=5, sticky="w", padx=(0, 6), pady=2
            )
            ttk.Button(region_frame, text="適用", command=lambda i=index: self._emit_apply_region(i)).grid(
                row=row, column=6, sticky="w", pady=2
            )

        ttk.Label(region_frame, textvariable=self.region_summary_var, wraplength=560).grid(
            row=4, column=0, columnspan=7, sticky="w", pady=(6, 0)
        )

        ttk.Label(self, text="直近OCR生テキスト:").grid(row=8, column=0, sticky="nw", pady=(8, 0))
        ttk.Label(self, textvariable=self.last_ocr_var, wraplength=520).grid(row=8, column=1, sticky="w", pady=(8, 0))

        for col in range(2):
            self.grid_columnconfigure(col, weight=1)

    def _emit_apply_region(self, index: int) -> None:
        self._on_apply_region(
            index,
            self.region_enabled_vars[index].get(),
            self.region_left_vars[index].get(),
            self.region_top_vars[index].get(),
            self.region_width_vars[index].get(),
            self.region_height_vars[index].get(),
        )

    def _emit_drag_select(self, index: int) -> None:
        self._on_drag_select_region(index)

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

    def set_region_inputs(
        self,
        index: int,
        *,
        enabled: bool,
        left: int,
        top: int,
        width: int,
        height: int,
    ) -> None:
        self.region_enabled_vars[index].set(enabled)
        self.region_left_vars[index].set(str(left))
        self.region_top_vars[index].set(str(top))
        self.region_width_vars[index].set(str(width))
        self.region_height_vars[index].set(str(height))

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

