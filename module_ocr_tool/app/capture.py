from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any
from typing import TypedDict

logger = logging.getLogger(__name__)


class CaptureRegion(TypedDict):
    left: int
    top: int
    width: int
    height: int


@dataclass
class CapturedFrame:
    image: Any
    left: int
    top: int
    width: int
    height: int


@dataclass
class ScreenCapture:
    monitor_index: int = 1
    region: CaptureRegion | None = None

    def _load_dependencies(self):
        try:
            import mss
            import numpy as np
        except ImportError as exc:
            raise RuntimeError("mss と numpy が必要です。`pip install mss numpy` を実行してください。") from exc
        return mss, np

    def capture_full(self) -> CapturedFrame:
        logger.debug("Capture full frame requested (monitor_index=%s)", self.monitor_index)
        mss, np = self._load_dependencies()
        with mss.mss() as sct:
            monitor = sct.monitors[self.monitor_index]
            logger.debug("Capture full target resolved: %s", monitor)
            screenshot = sct.grab(monitor)
            image = np.array(screenshot)
            if image.shape[-1] == 4:
                image = image[:, :, :3]
            frame = CapturedFrame(
                image=image,
                left=int(monitor.get("left", 0)),
                top=int(monitor.get("top", 0)),
                width=int(monitor.get("width", int(image.shape[1]))),
                height=int(monitor.get("height", int(image.shape[0]))),
            )
            logger.debug(
                "Capture full finished (shape=%s, origin=(%s,%s))",
                image.shape,
                frame.left,
                frame.top,
            )
            return frame

    def crop_from_frame(self, frame: CapturedFrame, *, region: CaptureRegion):
        x0 = int(region["left"]) - frame.left
        y0 = int(region["top"]) - frame.top
        x1 = x0 + int(region["width"])
        y1 = y0 + int(region["height"])

        x0 = max(0, min(x0, frame.width))
        y0 = max(0, min(y0, frame.height))
        x1 = max(0, min(x1, frame.width))
        y1 = max(0, min(y1, frame.height))

        if x1 <= x0 or y1 <= y0:
            raise RuntimeError(
                f"指定範囲がキャプチャ画像の外です。region={region}, frame_origin=({frame.left},{frame.top}), "
                f"frame_size=({frame.width},{frame.height})"
            )
        return frame.image[y0:y1, x0:x1]

    def capture(self, *, region_override: CaptureRegion | None = None):
        target_region = region_override if region_override is not None else self.region
        logger.debug("Capture requested (monitor_index=%s, custom_region=%s)", self.monitor_index, target_region)
        frame = self.capture_full()
        if target_region is None:
            return frame.image
        image = self.crop_from_frame(frame, region=target_region)
        logger.debug("Capture finished via full-frame crop (shape=%s)", getattr(image, "shape", None))
        return image
