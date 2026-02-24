from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict


class CaptureRegion(TypedDict):
    left: int
    top: int
    width: int
    height: int


@dataclass
class ScreenCapture:
    monitor_index: int = 1
    region: CaptureRegion | None = None

    def capture(self):
        try:
            import mss
            import numpy as np
        except ImportError as exc:
            raise RuntimeError("mss と numpy が必要です。`pip install mss numpy` を実行してください。") from exc

        with mss.mss() as sct:
            target = self.region if self.region is not None else sct.monitors[self.monitor_index]
            screenshot = sct.grab(target)
            image = np.array(screenshot)
            if image.shape[-1] == 4:
                image = image[:, :, :3]
            return image

