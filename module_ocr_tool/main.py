from __future__ import annotations

import tkinter as tk

from module_ocr_tool.app.controller import AppController


def main() -> None:
    root = tk.Tk()
    root.title("Module OCR Tool")
    root.geometry("640x360")
    controller = AppController(root)
    controller.run()
    root.mainloop()


if __name__ == "__main__":
    main()
