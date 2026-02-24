from __future__ import annotations

from dataclasses import dataclass
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from module_ocr_tool.app.mappings import EFFECT_ID_TO_JP, JP_TO_EFFECT_ID
from module_ocr_tool.app.models import EffectEntry
from module_ocr_tool.app.normalizer import ParsedEffectCandidate


@dataclass
class _RowModel:
    jp_var: tk.StringVar
    effect_var: tk.StringVar
    value_var: tk.StringVar
    blank_value_var: tk.BooleanVar


class ResultDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        candidates: list[ParsedEffectCandidate],
        *,
        on_confirm: Callable[[list[EffectEntry]], None],
        on_cancel: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self.title("OCR結果")
        self.transient(master)
        self.grab_set()
        self.resizable(False, False)

        self._on_confirm_callback = on_confirm
        self._on_cancel_callback = on_cancel
        self._rows: list[_RowModel] = []

        self._build(candidates)
        self.protocol("WM_DELETE_WINDOW", self._cancel)

    def _build(self, candidates: list[ParsedEffectCandidate]) -> None:
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="OCR結果", font=("", 13, "bold")).grid(row=0, column=0, columnspan=5, sticky="w", pady=(0, 10))

        ttk.Label(frame, text="No").grid(row=1, column=0, padx=(0, 4))
        ttk.Label(frame, text="日本語候補").grid(row=1, column=1, padx=(0, 4))
        ttk.Label(frame, text="effect_id").grid(row=1, column=2, padx=(0, 4))
        ttk.Label(frame, text="value").grid(row=1, column=3)
        ttk.Label(frame, text="値空欄").grid(row=1, column=4)

        prepared_rows = self._prepare_rows(candidates)
        for index, row_data in enumerate(prepared_rows):
            self._create_row(frame, index + 2, index, row_data)

        button_row = len(prepared_rows) + 2
        ttk.Button(frame, text="確定", command=self._confirm).grid(row=button_row, column=3, sticky="e", pady=(12, 0), padx=(0, 4))
        ttk.Button(frame, text="キャンセル", command=self._cancel).grid(row=button_row, column=4, sticky="e", pady=(12, 0))

    def _prepare_rows(self, candidates: list[ParsedEffectCandidate]) -> list[dict[str, str | list[str]]]:
        rows: list[dict[str, str | list[str]]] = []
        for candidate in candidates[:3]:
            initial_jp = ""
            if candidate.resolved_effect_id and candidate.resolved_effect_id in EFFECT_ID_TO_JP:
                initial_jp = EFFECT_ID_TO_JP[candidate.resolved_effect_id]
            elif candidate.jp_label_candidates:
                initial_jp = candidate.jp_label_candidates[0]

            initial_effect_id = candidate.resolved_effect_id or JP_TO_EFFECT_ID.get(initial_jp, "")
            initial_value = "" if candidate.parsed_value is None else str(candidate.parsed_value)
            label_candidates = candidate.jp_label_candidates or list(JP_TO_EFFECT_ID.keys())

            rows.append(
                {
                    "jp": initial_jp,
                    "effect_id": initial_effect_id,
                    "value": initial_value,
                    "candidates": list(dict.fromkeys(label_candidates + list(JP_TO_EFFECT_ID.keys()))),
                }
            )

        while len(rows) < 3:
            rows.append(
                {
                    "jp": "",
                    "effect_id": "",
                    "value": "",
                    "candidates": list(JP_TO_EFFECT_ID.keys()),
                }
            )

        return rows[:3]

    def _create_row(self, frame: ttk.Frame, row: int, index: int, row_data: dict[str, str | list[str]]) -> None:
        ttk.Label(frame, text=str(index + 1)).grid(row=row, column=0, sticky="w", padx=(0, 4), pady=2)

        jp_var = tk.StringVar(value=str(row_data["jp"]))
        effect_var = tk.StringVar(value=str(row_data["effect_id"]))
        value_var = tk.StringVar(value=str(row_data["value"]))
        blank_value_var = tk.BooleanVar(value=False)

        label_selector = ttk.Combobox(frame, textvariable=jp_var, values=row_data["candidates"], width=24)
        label_selector.grid(row=row, column=1, sticky="ew", padx=(0, 4), pady=2)

        effect_entry = ttk.Entry(frame, textvariable=effect_var, width=26)
        effect_entry.grid(row=row, column=2, sticky="ew", padx=(0, 4), pady=2)

        value_entry = ttk.Entry(frame, textvariable=value_var, width=8)
        value_entry.grid(row=row, column=3, sticky="ew", pady=2)

        blank_check = ttk.Checkbutton(frame, variable=blank_value_var)
        blank_check.grid(row=row, column=4, sticky="w", padx=(4, 0), pady=2)

        def on_blank_toggle(*_args) -> None:
            if blank_value_var.get():
                value_var.set("")
                value_entry.state(["disabled"])
            else:
                value_entry.state(["!disabled"])

        blank_value_var.trace_add("write", on_blank_toggle)

        jp_var.trace_add("write", lambda *_: self._sync_effect_id(jp_var, effect_var))

        self._rows.append(_RowModel(jp_var=jp_var, effect_var=effect_var, value_var=value_var, blank_value_var=blank_value_var))

    def _sync_effect_id(self, jp_var: tk.StringVar, effect_var: tk.StringVar) -> None:
        jp_label = jp_var.get().strip()
        effect_id = JP_TO_EFFECT_ID.get(jp_label)
        if effect_id:
            effect_var.set(effect_id)

    def _confirm(self) -> None:
        effects: list[EffectEntry] = []
        for row in self._rows:
            jp_label = row.jp_var.get().strip()
            effect_id = row.effect_var.get().strip()
            value_text = row.value_var.get().strip()
            blank_value = row.blank_value_var.get()

            if not jp_label and not effect_id and not value_text:
                continue

            if blank_value or value_text == "":
                # 空欄値は「この行を出力しない」扱いにする。
                continue

            if not effect_id and jp_label:
                effect_id = JP_TO_EFFECT_ID.get(jp_label, "")
            if not effect_id:
                messagebox.showerror("入力エラー", "effect_id を入力してください。")
                return

            try:
                value = int(value_text)
            except ValueError:
                messagebox.showerror("入力エラー", "value は整数で入力してください。")
                return

            effects.append(EffectEntry(effect_id=effect_id, value=value))

        if len(effects) > 3:
            messagebox.showerror("入力エラー", "effects は最大3件です。")
            return

        self._on_confirm_callback(effects)
        self.destroy()

    def _cancel(self) -> None:
        self._on_cancel_callback()
        self.destroy()
