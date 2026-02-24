from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import TypedDict

logger = logging.getLogger(__name__)


class CaptureRegion(TypedDict):
    left: int
    top: int
    width: int
    height: int


@dataclass
class ScreenCapture:
    monitor_index: int = 1
    region: CaptureRegion | None = None

    def capture(self, *, region_override: CaptureRegion | None = None):
        target_region = region_override if region_override is not None else self.region
        logger.debug("Capture requested (monitor_index=%s, custom_region=%s)", self.monitor_index, target_region)
        try:
            import mss
            import numpy as np
        except ImportError as exc:
            raise RuntimeError("mss と numpy が必要です。`pip install mss numpy` を実行してください。") from exc

        with mss.mss() as sct:
            target = target_region if target_region is not None else sct.monitors[self.monitor_index]
            logger.debug("Capture target resolved: %s", target)
            screenshot = sct.grab(target)
            image = np.array(screenshot)
            if image.shape[-1] == 4:
                image = image[:, :, :3]
            logger.debug("Capture finished (shape=%s)", image.shape)
            return image
