from __future__ import annotations

import tkinter as tk
from typing import Callable


class RegionSelectorOverlay(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        *,
        on_selected: Callable[[int, int, int, int], None],
        on_cancel: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self._on_selected = on_selected
        self._on_cancel = on_cancel

        self._start_x: int | None = None
        self._start_y: int | None = None
        self._rect_id: int | None = None
        self._screen_left, self._screen_top, width, height = self._virtual_screen_geometry()

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.25)
        self.configure(bg="black")

        self.geometry(f"{width}x{height}+{self._screen_left}+{self._screen_top}")

        self.canvas = tk.Canvas(self, bg="black", highlightthickness=0, cursor="cross")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_text(
            20,
            20,
            anchor="nw",
            text="ドラッグしてOCR範囲を選択 / ESCでキャンセル",
            fill="white",
            font=("", 14, "bold"),
        )

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Escape>", self._cancel)
        self.bind("<Button-3>", self._cancel)

        self.grab_set()
        self.focus_force()

    def _virtual_screen_geometry(self) -> tuple[int, int, int, int]:
        try:
            import ctypes

            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
            left = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
            top = user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
            width = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
            height = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
            if width > 0 and height > 0:
                return int(left), int(top), int(width), int(height)
        except Exception:
            pass
        return 0, 0, int(self.winfo_screenwidth()), int(self.winfo_screenheight())

    def _on_press(self, event: tk.Event) -> None:
        self._start_x = int(event.x_root)
        self._start_y = int(event.y_root)
        if self._rect_id is not None:
            self.canvas.delete(self._rect_id)
            self._rect_id = None

    def _on_drag(self, event: tk.Event) -> None:
        if self._start_x is None or self._start_y is None:
            return

        x1 = self._start_x
        y1 = self._start_y
        x2 = int(event.x_root)
        y2 = int(event.y_root)
        if self._rect_id is not None:
            self.canvas.delete(self._rect_id)
        self._rect_id = self.canvas.create_rectangle(
            x1 - self._screen_left,
            y1 - self._screen_top,
            x2 - self._screen_left,
            y2 - self._screen_top,
            outline="#00ff88",
            width=2,
            dash=(6, 4),
        )

    def _on_release(self, event: tk.Event) -> None:
        if self._start_x is None or self._start_y is None:
            self._cancel()
            return

        x2 = int(event.x_root)
        y2 = int(event.y_root)

        left = min(self._start_x, x2)
        top = min(self._start_y, y2)
        width = abs(x2 - self._start_x)
        height = abs(y2 - self._start_y)

        if width < 4 or height < 4:
            self._cancel()
            return

        self._on_selected(left, top, width, height)
        self.destroy()

    def _cancel(self, _event: tk.Event | None = None) -> None:
        self._on_cancel()
        self.destroy()
