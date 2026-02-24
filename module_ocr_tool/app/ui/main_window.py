from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable


class MainWindow(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        on_start: Callable[[], None],
        on_export: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self._on_start = on_start
        self._on_export = on_export

        self.status_var = tk.StringVar(value="待機中")
        self.module_count_var = tk.StringVar(value="0")
        self.hotkey_note_var = tk.StringVar(value="F8: スクリーンショット取得 / ESC: 終了")
        self.last_ocr_var = tk.StringVar(value="-")

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

        ttk.Label(self, text="直近OCR生テキスト:").grid(row=6, column=0, sticky="nw")
        ttk.Label(self, textvariable=self.last_ocr_var, wraplength=420).grid(row=6, column=1, sticky="w")

        for col in range(2):
            self.grid_columnconfigure(col, weight=1)

    def set_status(self, status: str) -> None:
        self.status_var.set(status)

    def set_module_count(self, count: int) -> None:
        self.module_count_var.set(str(count))

    def set_hotkey_note(self, note: str) -> None:
        self.hotkey_note_var.set(note)

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
        messagebox.showinfo("Module OCR Tool", message)

    def show_error(self, message: str) -> None:
        messagebox.showerror("Module OCR Tool", message)

