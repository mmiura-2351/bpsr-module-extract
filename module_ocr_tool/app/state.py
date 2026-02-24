from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from module_ocr_tool.app.models import ModuleRecord

AppStatus = Literal["idle", "waiting_capture", "processing", "editing_result", "error"]


@dataclass
class AppState:
    status: AppStatus = "idle"
    modules: list[ModuleRecord] = field(default_factory=list)
    last_raw_ocr_text: str | None = None
    last_error_message: str | None = None
