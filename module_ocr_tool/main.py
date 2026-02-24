from __future__ import annotations

import logging
import tkinter as tk

from module_ocr_tool.app.controller import AppController
from module_ocr_tool.app.logging_config import setup_logging


def main() -> None:
    log_path = setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Application start")

    root = tk.Tk()
    root.title("Module OCR Tool")
    root.geometry("640x360")
    controller = AppController(root, log_path=str(log_path))
    controller.run()
    root.mainloop()


if __name__ == "__main__":
    main()
