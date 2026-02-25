from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from pathlib import Path
import threading
import time
import tkinter as tk

from module_ocr_tool.app.config_store import load_app_config, save_app_config
from module_ocr_tool.app.capture import CaptureRegion, ScreenCapture
from module_ocr_tool.app.exporter import (
    append_modules_to_existing_json,
    build_export_payload,
    is_duplicate_module,
    write_export_json,
)
from module_ocr_tool.app.models import EffectEntry, ModuleRecord
from module_ocr_tool.app.normalizer import (
    infer_expected_effect_count,
    ParsedCategoryCandidate,
    ParsedEffectCandidate,
    normalize_module_name_text,
    parse_category_text,
    parse_ocr_text,
)
from module_ocr_tool.app.ocr_engine import TesseractOcrEngine
from module_ocr_tool.app.position_cache import PositionCacheStore
from module_ocr_tool.app.state import AppState
from module_ocr_tool.app.ui.main_window import MainWindow
from module_ocr_tool.app.ui.region_selector import RegionSelectorOverlay
from module_ocr_tool.app.ui.result_dialog import ResultDialog

logger = logging.getLogger(__name__)


@dataclass
class _ProcessingCacheContext:
    module_name_key: str = ""
    module_name_raw: str = ""
    effect_regions: list[CaptureRegion | None] | None = None
    category_region: CaptureRegion | None = None


class AppController:
    def __init__(self, root: tk.Tk, *, log_path: str | None = None) -> None:
        self.root = root
        self.log_path = log_path
        self._config, self._config_path = load_app_config()
        self._position_cache = PositionCacheStore(config_path=self._config_path)
        self._position_cache.load()
        self.state = AppState()
        self.capture = ScreenCapture()
        self.ocr_engine = TesseractOcrEngine()

        loaded_regions = list(self._config.effect_regions)
        self._effect_regions: list[CaptureRegion | None] = (loaded_regions + [None, None, None, None, None])[:5]
        self._processing_token = 0
        self._processing_debug_flags: dict[int, bool] = {}
        self._last_processing_cache_context = _ProcessingCacheContext()

        self._region_selector: RegionSelectorOverlay | None = None
        self._region_selector_slot = -1

        self.main_window = MainWindow(
            root,
            on_start=self.start_capture_mode,
            on_manual_run=self.run_manual_capture,
            on_debug_run=self.run_debug_capture,
            on_export=self._handle_export_click,
            on_update_export=self._handle_update_export_click,
            on_apply_region=self.apply_capture_region_from_ui,
            on_drag_select_region=self.open_region_selector,
        )
        self.main_window.pack(fill="both", expand=True, padx=16, pady=16)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        logger.info(
            "Controller initialized (log_path=%s, config_path=%s, cache_path=%s)",
            self.log_path,
            self._config_path,
            self._position_cache.path,
        )

    def _on_close(self) -> None:
        logger.info("Application closing")
        self._save_config()
        try:
            self._position_cache.save()
        except Exception:
            logger.exception("Failed to save position cache: %s", self._position_cache.path)
        self.root.destroy()

    def _save_config(self) -> None:
        try:
            self._config.effect_regions = [
                (
                    {
                        "left": region["left"],
                        "top": region["top"],
                        "width": region["width"],
                        "height": region["height"],
                    }
                    if region is not None
                    else None
                )
                for region in self._effect_regions
            ]
            save_app_config(self._config, self._config_path)
        except Exception:
            logger.exception("Failed to save config: %s", self._config_path)

    def run(self) -> None:
        logger.info("Controller run")
        self._sync_region_inputs_to_ui()
        self._update_view()

    def _status_label(self) -> str:
        labels = {
            "idle": "待機中",
            "waiting_capture": "キャプチャ待機中",
            "processing": "OCR処理中",
            "editing_result": "OCR結果確認中",
            "error": "エラー",
        }
        return labels.get(self.state.status, self.state.status)

    def _set_status(self, status: str, *, reason: str) -> None:
        previous = self.state.status
        self.state.status = status
        if previous != status:
            logger.info("Status: %s -> %s (%s)", previous, status, reason)

    def _format_region_summary(self) -> str:
        ordered_slots = [
            (4, "モジュール名"),
            (3, "カテゴリ名"),
            (0, "効果1"),
            (1, "効果2"),
            (2, "効果3"),
        ]
        segments: list[str] = []
        for slot_index, label in ordered_slots:
            region = self._effect_regions[slot_index] if slot_index < len(self._effect_regions) else None
            if region is None:
                segments.append(f"{label}:未設定")
            else:
                segments.append(
                    f"{label}:({region['left']},{region['top']},{region['width']},{region['height']})"
                )
        return " / ".join(segments)

    def _operation_note(self) -> str:
        return "OCR実行ボタンを使用してください。"

    def _sync_region_inputs_to_ui(self) -> None:
        for index, region in enumerate(self._effect_regions):
            if region is None:
                self.main_window.set_region_inputs(index, enabled=False, left=0, top=0, width=240, height=40)
            else:
                self.main_window.set_region_inputs(
                    index,
                    enabled=True,
                    left=region["left"],
                    top=region["top"],
                    width=region["width"],
                    height=region["height"],
                )

    def _update_view(self) -> None:
        self.main_window.set_status(self._status_label())
        self.main_window.set_module_count(len(self.state.modules))
        self.main_window.set_last_ocr_text(self.state.last_raw_ocr_text)
        self.main_window.set_log_path(self.log_path or "-")
        self.main_window.set_region_summary(self._format_region_summary())
        self.main_window.set_hotkey_note(self._operation_note())

    def apply_capture_region_from_ui(
        self,
        slot_index: int,
        use_custom_region: bool,
        left_text: str,
        top_text: str,
        width_text: str,
        height_text: str,
    ) -> None:
        if slot_index < 0 or slot_index >= len(self._effect_regions):
            return

        logger.info(
            "Apply capture region requested (slot=%s, custom=%s, left=%s, top=%s, width=%s, height=%s)",
            slot_index + 1,
            use_custom_region,
            left_text,
            top_text,
            width_text,
            height_text,
        )
        if not use_custom_region:
            self._effect_regions[slot_index] = None
            self.main_window.set_region_inputs(slot_index, enabled=False, left=0, top=0, width=240, height=40)
            self._save_config()
            self._update_view()
            return

        try:
            left = int(left_text.strip())
            top = int(top_text.strip())
            width = int(width_text.strip())
            height = int(height_text.strip())
        except ValueError:
            self.main_window.show_error("OCR取得範囲は整数で入力してください。")
            return

        if width <= 0 or height <= 0:
            self.main_window.show_error("width と height は 1 以上を指定してください。")
            return
        if left < 0 or top < 0:
            self.main_window.show_error("left と top は 0 以上を指定してください。")
            return

        self._apply_capture_region(slot_index, left=left, top=top, width=width, height=height, source="manual-input")

    def _apply_capture_region(
        self,
        slot_index: int,
        *,
        left: int,
        top: int,
        width: int,
        height: int,
        source: str,
    ) -> None:
        region: CaptureRegion = {
            "left": left,
            "top": top,
            "width": width,
            "height": height,
        }
        self._effect_regions[slot_index] = region
        self.main_window.set_region_inputs(
            slot_index,
            enabled=True,
            left=left,
            top=top,
            width=width,
            height=height,
        )
        logger.info("Capture region applied via %s (slot=%s): %s", source, slot_index + 1, region)
        self._save_config()
        self._update_view()

    def open_region_selector(self, slot_index: int) -> None:
        if self.state.status == "processing":
            self.main_window.show_error("OCR処理中は範囲選択できません。")
            return
        if slot_index < 0 or slot_index >= len(self._effect_regions):
            return

        if self._region_selector is not None and self._region_selector.winfo_exists():
            logger.info("Region selector already open")
            return

        self._region_selector_slot = slot_index
        logger.info("Open drag region selector (slot=%s)", slot_index + 1)
        self._region_selector = RegionSelectorOverlay(
            self.root,
            on_selected=self._on_region_selected_by_drag,
            on_cancel=self._on_region_select_canceled,
        )

    def _on_region_selected_by_drag(self, left: int, top: int, width: int, height: int) -> None:
        slot_index = self._region_selector_slot
        self._region_selector = None
        self._region_selector_slot = -1
        if slot_index < 0 or slot_index >= len(self._effect_regions):
            return
        self._apply_capture_region(slot_index, left=left, top=top, width=width, height=height, source="drag-select")

    def _on_region_select_canceled(self) -> None:
        self._region_selector = None
        self._region_selector_slot = -1
        logger.info("Region selector canceled")

    def start_capture_mode(self) -> None:
        self._set_status("waiting_capture", reason="start capture mode")
        self.state.last_error_message = None
        self._update_view()

    def run_manual_capture(self) -> None:
        if self.state.status == "idle":
            self.start_capture_mode()
        if self.state.status == "waiting_capture":
            self._start_processing(source="manual-button", debug_capture=False)
            return
        if self.state.status == "processing":
            self.main_window.show_error("OCR処理中です。完了まで待ってください。")
            return
        if self.state.status == "editing_result":
            self.main_window.show_error("OCR結果確認中です。確定またはキャンセルしてください。")
            return
        self.main_window.show_error("現在はOCR実行できない状態です。")

    def run_debug_capture(self) -> None:
        if self.state.status == "idle":
            self.start_capture_mode()
        if self.state.status == "waiting_capture":
            self._start_processing(source="debug-button", debug_capture=True)
            return
        if self.state.status == "processing":
            self.main_window.show_error("OCR処理中です。完了まで待ってください。")
            return
        if self.state.status == "editing_result":
            self.main_window.show_error("OCR結果確認中です。確定またはキャンセルしてください。")
            return
        self.main_window.show_error("現在はOCR実行できない状態です。")

    def _start_processing(self, *, source: str, debug_capture: bool) -> None:
        if self.state.status != "waiting_capture":
            return

        self._set_status("processing", reason=f"OCR run ({source})")
        self._update_view()

        self._processing_token += 1
        token = self._processing_token
        self._processing_debug_flags[token] = debug_capture
        timeout_ms = self._compute_processing_timeout_ms()
        logger.info(
            "Processing started (token=%s, timeout_ms=%s, source=%s, debug_capture=%s)",
            token,
            timeout_ms,
            source,
            debug_capture,
        )
        self.root.after(timeout_ms, lambda: self._handle_processing_timeout(token))

        worker = threading.Thread(target=self._process_capture_background, args=(token,), daemon=True)
        worker.start()

    def _compute_processing_timeout_ms(self) -> int:
        configured_regions = [region for region in self._effect_regions[:3] if region is not None]
        category_region = self._effect_regions[3] if len(self._effect_regions) >= 4 else None
        module_name_region = self._effect_regions[4] if len(self._effect_regions) >= 5 else None
        if configured_regions:
            per_region_sec = max(self.ocr_engine.timeout_sec, 8.0)
            # 初回OCR + アンカーY探索フォールバック分の余裕を見込む。
            estimated_sec = 8.0 + (per_region_sec * len(configured_regions))
        else:
            estimated_sec = max((self.ocr_engine.timeout_sec * 2.0) + 6.0, 20.0)
        if category_region is not None:
            estimated_sec += max(self.ocr_engine.timeout_sec, 8.0)
        if module_name_region is not None:
            estimated_sec += max(self.ocr_engine.timeout_sec, 8.0)

        timeout_ms = int(estimated_sec * 1000)
        timeout_ms = max(timeout_ms, 15000)
        timeout_ms = min(timeout_ms, 120000)
        logger.info(
            "Computed processing timeout (ms=%s, configured_regions=%s, engine_timeout_sec=%.1f)",
            timeout_ms,
            len(configured_regions),
            self.ocr_engine.timeout_sec,
        )
        return timeout_ms

    def _extract_single_effect_line(self, image) -> str:
        line = self.ocr_engine.extract_effect_line(image)
        if line:
            return line
        fallback = self.ocr_engine.extract_effect_texts(image, max_effects=1)
        return fallback[0] if fallback else ""

    def _log_base_dir(self) -> Path:
        return Path(self.log_path).resolve().parent if self.log_path else Path.cwd() / "logs"

    def _create_debug_output_dir(self, token: int) -> Path:
        root = self._log_base_dir() / "ocr_debug_runs"
        root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        debug_dir = root / f"token{token}_{timestamp}"
        debug_dir.mkdir(parents=True, exist_ok=False)
        return debug_dir

    def _save_debug_slot_output(
        self,
        debug_dir: Path,
        *,
        slot_index: int,
        image,
        line: str,
    ) -> None:
        try:
            import cv2
        except ImportError:
            logger.warning("Skip debug slot output save (cv2 unavailable)")
            return

        image_path = debug_dir / f"slot{slot_index}_capture.png"
        text_path = debug_dir / f"slot{slot_index}_ocr_text.txt"
        cv2.imwrite(str(image_path), image)
        text_path.write_text(line, encoding="utf-8")

    def _write_debug_summary(
        self,
        debug_dir: Path,
        *,
        token: int,
        lines: list[str],
        raw_text: str,
        expected_effect_count: int = 3,
        anchor_shift_y: int = 0,
        category_line: str = "",
        module_name_line: str = "",
        module_cache_key: str = "",
    ) -> None:
        summary_path = debug_dir / "ocr_debug_summary.txt"
        content = [
            f"token={token}",
            f"line_count={len(lines)}",
            f"expected_effect_count={expected_effect_count}",
            f"anchor_shift_y={anchor_shift_y}",
            f"category_line={category_line}",
            f"module_name_line={module_name_line}",
            f"module_cache_key={module_cache_key}",
            "",
            "[lines]",
        ]
        content.extend(lines)
        content.extend(["", "[raw_text]", raw_text])
        summary_path.write_text("\n".join(content), encoding="utf-8")

    def _evaluate_line_quality(self, line: str) -> tuple[int, bool]:
        cleaned = line.strip()
        if not cleaned:
            return 0, False

        parsed = parse_ocr_text(cleaned, max_effects=1)
        if not parsed:
            return 0, False

        candidate = parsed[0]
        score = 0
        if candidate.resolved_effect_id is not None:
            score += 120
        elif candidate.jp_label_candidates:
            score += 30

        if candidate.parsed_value is not None:
            score += 60

        if candidate.resolved_effect_id is not None and candidate.parsed_value is not None:
            score += 120
            return score, True
        return score, False

    def _evaluate_slot_lines_quality(
        self,
        slot_order: list[int],
        slot_lines: dict[int, str],
    ) -> tuple[int, int]:
        complete_count = 0
        total_score = 0
        for slot_index in slot_order:
            line = slot_lines.get(slot_index, "")
            score, complete = self._evaluate_line_quality(line)
            total_score += score
            if complete:
                complete_count += 1
        return complete_count, total_score

    def _screen_profile(self) -> str:
        try:
            width = int(self.root.winfo_screenwidth())
            height = int(self.root.winfo_screenheight())
            return f"{width}x{height}"
        except Exception:
            return "unknown-screen"

    def _build_module_cache_key(self, module_name_raw: str) -> str:
        normalized_name = normalize_module_name_text(module_name_raw)
        if not normalized_name:
            return ""
        return f"{normalized_name}|{self._screen_profile()}"

    def _slot_regions_to_effect_list(
        self,
        slot_regions: list[tuple[int, CaptureRegion]],
    ) -> list[CaptureRegion | None]:
        regions: list[CaptureRegion | None] = [None, None, None]
        for slot_index, region in slot_regions:
            if slot_index < 1 or slot_index > 3:
                continue
            regions[slot_index - 1] = {
                "left": region["left"],
                "top": region["top"],
                "width": region["width"],
                "height": region["height"],
            }
        return regions

    def _capture_and_extract_slot_lines(
        self,
        regions: list[tuple[int, CaptureRegion]],
    ) -> tuple[dict[int, object], dict[int, str]]:
        slot_images: dict[int, object] = {}
        for slot_index, region in regions:
            slot_images[slot_index] = self.capture.capture(region_override=region)

        slot_lines: dict[int, str] = {}
        worker_count = min(len(slot_images), 3)
        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="ocr-slot") as executor:
            future_to_slot = {
                executor.submit(self._extract_single_effect_line, image): slot_index
                for slot_index, image in slot_images.items()
            }
            for future in as_completed(future_to_slot):
                slot_index = future_to_slot[future]
                slot_lines[slot_index] = future.result()
        return slot_images, slot_lines

    def _shift_region_y(self, region: CaptureRegion, shift_y: int) -> CaptureRegion:
        return {
            "left": region["left"],
            "top": max(region["top"] + shift_y, 0),
            "width": region["width"],
            "height": region["height"],
        }

    def _build_shift_candidates(self, *, max_abs_shift: int, step: int) -> list[int]:
        candidates = [0]
        current = step
        while current <= max_abs_shift:
            candidates.append(-current)
            candidates.append(current)
            current += step
        return candidates

    def _search_best_anchor_shifted_lines(
        self,
        configured: list[tuple[int, CaptureRegion]],
        *,
        initial_images: dict[int, object],
        initial_lines: dict[int, str],
    ) -> tuple[dict[int, object], dict[int, str], int]:
        slot_order = [slot_index for slot_index, _ in configured]
        best_images = dict(initial_images)
        best_lines = dict(initial_lines)
        best_shift = 0
        best_quality = self._evaluate_slot_lines_quality(slot_order, best_lines)

        anchor_slot = configured[0][0]
        shift_candidates = self._build_shift_candidates(max_abs_shift=72, step=12)
        logger.info(
            "Anchor shift search start (anchor_slot=%s, candidates=%s, initial_complete=%s)",
            anchor_slot,
            len(shift_candidates),
            best_quality[0],
        )

        for shift_y in shift_candidates:
            if shift_y == 0:
                continue
            shifted_regions = [
                (slot_index, self._shift_region_y(region, shift_y))
                for slot_index, region in configured
            ]
            slot_images, slot_lines = self._capture_and_extract_slot_lines(shifted_regions)
            quality = self._evaluate_slot_lines_quality(slot_order, slot_lines)
            if quality > best_quality:
                best_quality = quality
                best_shift = shift_y
                best_images = slot_images
                best_lines = slot_lines

            if best_quality[0] >= len(slot_order):
                logger.info(
                    "Anchor shift search early stop (shift_y=%s, complete=%s, score=%s)",
                    best_shift,
                    best_quality[0],
                    best_quality[1],
                )
                break

        logger.info(
            "Anchor shift search done (best_shift_y=%s, complete=%s, score=%s)",
            best_shift,
            best_quality[0],
            best_quality[1],
        )
        return best_images, best_lines, best_shift

    def _save_failed_ocr_sample(self, image, *, token: int, slot_index: int, reason: str, line: str) -> None:
        if image is None:
            return
        try:
            try:
                import cv2
            except ImportError:
                logger.warning("Skip OCR debug sample save (cv2 unavailable)")
                return

            base_dir = self._log_base_dir()
            sample_dir = base_dir / "ocr_failed_samples"
            sample_dir.mkdir(parents=True, exist_ok=True)

            safe_reason = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in reason)[:32] or "unknown"
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            image_path = sample_dir / f"token{token}_slot{slot_index}_{safe_reason}_{timestamp}.png"
            meta_path = sample_dir / f"token{token}_slot{slot_index}_{safe_reason}_{timestamp}.txt"

            cv2.imwrite(str(image_path), image)
            meta_path.write_text(
                "\n".join(
                    [
                        f"token={token}",
                        f"slot={slot_index}",
                        f"reason={reason}",
                        f"line={line}",
                    ]
                ),
                encoding="utf-8",
            )
            logger.info("Saved OCR debug sample (reason=%s, image=%s)", reason, image_path)
        except Exception:
            logger.exception("Failed to save OCR debug sample")

    def _process_capture_background(self, token: int) -> None:
        started = time.monotonic()
        debug_capture = self._processing_debug_flags.get(token, False)
        debug_dir: Path | None = None
        try:
            if debug_capture:
                debug_dir = self._create_debug_output_dir(token)
                logger.info("Debug capture enabled (token=%s, dir=%s)", token, debug_dir)
            logger.info("Capture thread start (token=%s)", token)

            lines: list[str] = []
            category_line = ""
            module_name_line = ""
            module_cache_key = ""
            expected_effect_count = 3
            required_slots: list[int] = [1, 2, 3]
            selected_shift_y = 0
            used_effect_regions: list[CaptureRegion | None] = [None, None, None]
            used_category_region: CaptureRegion | None = None

            module_name_region = self._effect_regions[4] if len(self._effect_regions) >= 5 else None
            if module_name_region is not None:
                module_name_image = self.capture.capture(region_override=module_name_region)
                module_name_line = self.ocr_engine.extract_module_name_line(module_name_image)
                module_cache_key = self._build_module_cache_key(module_name_line)
                if debug_dir is not None:
                    self._save_debug_slot_output(
                        debug_dir,
                        slot_index=5,
                        image=module_name_image,
                        line=module_name_line,
                    )
                logger.info(
                    "Module-name OCR done (line=%s, cache_key=%s)",
                    module_name_line or "<empty>",
                    module_cache_key or "<empty>",
                )
            expected_effect_count = infer_expected_effect_count(module_name_line)
            required_slots = list(range(1, expected_effect_count + 1))
            logger.info(
                "Expected effect count inferred (module=%s, expected=%s)",
                module_name_line or "<empty>",
                expected_effect_count,
            )

            configured = [
                (index, region)
                for index, region in enumerate(self._effect_regions[:3], start=1)
                if region is not None and index in required_slots
            ]

            cache_entry = self._position_cache.lookup(module_cache_key) if module_cache_key else None
            if module_cache_key and cache_entry is None:
                logger.info("OCR position cache miss (key=%s)", module_cache_key)
            elif cache_entry is not None:
                logger.info("OCR position cache hit (key=%s)", module_cache_key)

            cache_effect_regions = (
                [
                    (idx, region)
                    for idx, region in enumerate(cache_entry.effect_regions, start=1)
                    if region is not None and idx in required_slots
                ]
                if cache_entry is not None
                else []
            )
            cache_effect_applied = False
            if cache_effect_regions:
                slot_order = [idx for idx, _ in cache_effect_regions]
                if len(slot_order) < expected_effect_count:
                    logger.info(
                        "OCR position cache fallback (key=%s, reason=insufficient-slots, actual=%s, expected=%s)",
                        module_cache_key,
                        len(slot_order),
                        expected_effect_count,
                    )
                    self._position_cache.mark_failure(module_cache_key)
                else:
                    slot_images, slot_lines = self._capture_and_extract_slot_lines(cache_effect_regions)
                    complete_count, _score = self._evaluate_slot_lines_quality(slot_order, slot_lines)
                    if complete_count >= expected_effect_count:
                        for index in slot_order:
                            image = slot_images[index]
                            line = slot_lines.get(index, "")
                            if debug_dir is not None:
                                self._save_debug_slot_output(debug_dir, slot_index=index, image=image, line=line)
                            if line:
                                lines.append(line)
                            logger.info("Region OCR done (slot=%s, source=cache, line=%s)", index, line or "<empty>")
                        used_effect_regions = self._slot_regions_to_effect_list(cache_effect_regions)
                        cache_effect_applied = True
                    else:
                        logger.info(
                            "OCR position cache fallback (key=%s, complete=%s, expected=%s)",
                            module_cache_key,
                            complete_count,
                            expected_effect_count,
                        )
                        self._position_cache.mark_failure(module_cache_key)

            if not cache_effect_applied and configured:
                logger.info(
                    "Using configured effect regions (count=%s, expected=%s)",
                    len(configured),
                    expected_effect_count,
                )
                configured_for_ocr = configured[:expected_effect_count]
                slot_order = [index for index, _region in configured_for_ocr]
                slot_images, slot_lines = self._capture_and_extract_slot_lines(configured_for_ocr)
                complete_count, _score = self._evaluate_slot_lines_quality(slot_order, slot_lines)
                if complete_count < len(slot_order):
                    slot_images, slot_lines, selected_shift_y = self._search_best_anchor_shifted_lines(
                        configured_for_ocr,
                        initial_images=slot_images,
                        initial_lines=slot_lines,
                    )
                effective_regions = (
                    configured_for_ocr
                    if selected_shift_y == 0
                    else [(slot_index, self._shift_region_y(region, selected_shift_y)) for slot_index, region in configured_for_ocr]
                )
                used_effect_regions = self._slot_regions_to_effect_list(effective_regions)

                for index in slot_order:
                    image = slot_images[index]
                    line = slot_lines.get(index, "")
                    if debug_dir is not None:
                        self._save_debug_slot_output(debug_dir, slot_index=index, image=image, line=line)
                    if line:
                        lines.append(line)
                        candidate = parse_ocr_text(line, max_effects=1)
                        if not candidate or candidate[0].resolved_effect_id is None or candidate[0].parsed_value is None:
                            self._save_failed_ocr_sample(
                                image,
                                token=token,
                                slot_index=index,
                                reason="unresolved_or_missing_value",
                                line=line,
                            )
                    else:
                        self._save_failed_ocr_sample(
                            image,
                            token=token,
                            slot_index=index,
                            reason="empty_result",
                            line="",
                        )
                    logger.info("Region OCR done (slot=%s, line=%s)", index, line or "<empty>")
            elif not cache_effect_applied:
                image = self.capture.capture()
                lines = self.ocr_engine.extract_effect_texts(image, max_effects=expected_effect_count)
                if debug_dir is not None:
                    self._save_debug_slot_output(
                        debug_dir,
                        slot_index=0,
                        image=image,
                        line="\n".join(lines),
                    )
                logger.info("Whole-area OCR done (lines=%s)", len(lines))

            configured_category_region = self._effect_regions[3] if len(self._effect_regions) >= 4 else None
            category_region_for_ocr = cache_entry.category_region if cache_entry is not None else None
            category_source = "cache" if category_region_for_ocr is not None else "configured"
            if category_region_for_ocr is None:
                category_region_for_ocr = configured_category_region
            if category_region_for_ocr is not None:
                category_image = self.capture.capture(region_override=category_region_for_ocr)
                category_line = self.ocr_engine.extract_category_line(category_image)
                if debug_dir is not None:
                    self._save_debug_slot_output(
                        debug_dir,
                        slot_index=4,
                        image=category_image,
                        line=category_line,
                    )
                logger.info(
                    "Category OCR done (source=%s, line=%s)",
                    category_source,
                    category_line or "<empty>",
                )
                if not category_line and category_source == "cache" and configured_category_region is not None:
                    fallback_image = self.capture.capture(region_override=configured_category_region)
                    fallback_line = self.ocr_engine.extract_category_line(fallback_image)
                    if fallback_line:
                        category_line = fallback_line
                        category_region_for_ocr = configured_category_region
                        logger.info("Category OCR fallback success (source=configured)")
                used_category_region = category_region_for_ocr

            raw_text = "\n".join(lines)
            category_candidate = parse_category_text(category_line)
            cache_context = _ProcessingCacheContext(
                module_name_key=module_cache_key,
                module_name_raw=module_name_line,
                effect_regions=used_effect_regions,
                category_region=used_category_region,
            )
            if debug_dir is not None:
                self._write_debug_summary(
                    debug_dir,
                    token=token,
                    lines=lines,
                    raw_text=raw_text,
                    expected_effect_count=expected_effect_count,
                    anchor_shift_y=selected_shift_y,
                    category_line=category_line,
                    module_name_line=module_name_line,
                    module_cache_key=module_cache_key,
                )
            candidates = parse_ocr_text(raw_text, max_effects=expected_effect_count)
            elapsed = time.monotonic() - started
            logger.info(
                "Processing success (token=%s, elapsed_sec=%.3f, raw_len=%s, lines=%s, candidates=%s)",
                token,
                elapsed,
                len(raw_text),
                len(lines),
                len(candidates),
            )
            self.root.after(
                0,
                lambda: self._handle_processing_success(
                    token,
                    candidates,
                    category_candidate,
                    raw_text,
                    debug_dir,
                    cache_context,
                ),
            )
        except Exception as exc:
            elapsed = time.monotonic() - started
            logger.exception("Processing failed (token=%s, elapsed_sec=%.3f)", token, elapsed)
            self.root.after(0, lambda: self._handle_processing_error(token, f"OCR処理に失敗しました: {exc}"))

    def _handle_processing_timeout(self, token: int) -> None:
        if token != self._processing_token or self.state.status != "processing":
            return
        self._processing_debug_flags.pop(token, None)
        self._processing_token += 1
        logger.error("Processing timeout (token=%s)", token)
        self._handle_error("OCR処理がタイムアウトしました。OCR取得範囲を狭めて再実行してください。")

    def _handle_processing_success(
        self,
        token: int,
        candidates: list[ParsedEffectCandidate],
        category_candidate: ParsedCategoryCandidate,
        raw_text: str,
        debug_dir: Path | None,
        cache_context: _ProcessingCacheContext,
    ) -> None:
        if token != self._processing_token or self.state.status != "processing":
            logger.info("Ignore stale success callback (token=%s, current=%s)", token, self._processing_token)
            return
        debug_enabled = self._processing_debug_flags.pop(token, False)
        if debug_enabled and debug_dir is not None:
            logger.info("Debug OCR output saved: %s", debug_dir)
            self.main_window.show_info(f"デバッグ出力を保存しました:\n{debug_dir}")
        self._last_processing_cache_context = cache_context
        self._show_result_dialog(candidates, category_candidate, raw_text)

    def _handle_processing_error(self, token: int, message: str) -> None:
        if token != self._processing_token or self.state.status != "processing":
            logger.info("Ignore stale error callback (token=%s, current=%s)", token, self._processing_token)
            return
        self._processing_debug_flags.pop(token, None)
        self._handle_error(message)

    def _show_result_dialog(
        self,
        candidates: list[ParsedEffectCandidate],
        category_candidate: ParsedCategoryCandidate,
        raw_text: str,
    ) -> None:
        self._set_status("editing_result", reason="processing success")
        self.state.last_raw_ocr_text = raw_text
        self._update_view()
        ResultDialog(
            self.root,
            candidates,
            category_candidate,
            on_confirm=self.confirm_module,
            on_cancel=self._cancel_result_edit,
        )

    def _cancel_result_edit(self) -> None:
        self._last_processing_cache_context = _ProcessingCacheContext()
        self._set_status("waiting_capture", reason="result edit canceled")
        self._update_view()

    def _update_position_cache_from_last_context(self) -> None:
        context = self._last_processing_cache_context
        effect_regions = context.effect_regions or [None, None, None]
        if not context.module_name_key or not any(region is not None for region in effect_regions):
            return
        self._position_cache.update_success(
            module_name_key=context.module_name_key,
            module_name_raw=context.module_name_raw,
            effect_regions=effect_regions,
            category_region=context.category_region,
        )
        logger.info("OCR position cache updated (key=%s)", context.module_name_key)

    def confirm_module(self, module_category: str, effects: list[EffectEntry]) -> None:
        self._update_position_cache_from_last_context()
        self._last_processing_cache_context = _ProcessingCacheContext()
        module = ModuleRecord(module_category=module_category, effects=effects[:3])
        if is_duplicate_module(module, self.state.modules):
            logger.info("Duplicate module detected. Skip append.")
            self.main_window.show_info("既存モジュールと重複しているため追加をスキップしました。")
            self._set_status("waiting_capture", reason="duplicate module skipped")
            self._update_view()
            return
        self.state.modules.append(module)
        logger.info("Module confirmed (effects=%s, modules_total=%s)", len(module.effects), len(self.state.modules))
        self._set_status("waiting_capture", reason="module confirmed")
        self._update_view()

    def _handle_export_click(self) -> None:
        output_path = self.main_window.ask_export_path(initial_path=self._config.last_export_path)
        if not output_path:
            logger.info("Export canceled by user")
            return

        try:
            self.export_json(output_path)
        except Exception as exc:
            self._handle_error(f"JSON出力に失敗しました: {exc}")
            return

        self._config.last_export_path = output_path
        self._save_config()
        self.main_window.show_info(f"JSONを出力しました:\n{output_path}")
        logger.info("Export completed: %s", output_path)

    def _handle_update_export_click(self) -> None:
        existing_path = self.main_window.ask_existing_json_path(initial_path=self._config.last_update_json_path)
        if not existing_path:
            logger.info("Update export canceled by user")
            return

        try:
            added, skipped, total = append_modules_to_existing_json(existing_path, self.state.modules)
        except Exception as exc:
            self._handle_error(f"既存JSON更新に失敗しました: {exc}")
            return

        self._config.last_update_json_path = existing_path
        self._save_config()
        self.main_window.show_info(
            "既存JSONを更新しました:\n"
            f"{existing_path}\n"
            f"追加: {added} / 重複・空: {skipped} / 合計: {total}"
        )
        logger.info(
            "Existing JSON updated (path=%s, added=%s, skipped=%s, total=%s)",
            existing_path,
            added,
            skipped,
            total,
        )

    def export_json(self, output_path: str) -> None:
        payload = build_export_payload(self.state.modules)
        logger.info("Export start (modules=%s, output=%s)", len(self.state.modules), output_path)
        write_export_json(payload, output_path)

    def _handle_error(self, message: str) -> None:
        self._last_processing_cache_context = _ProcessingCacheContext()
        self._set_status("error", reason="error raised")
        self.state.last_error_message = message
        logger.error("Error: %s", message)
        self.main_window.show_error(message)
        self._set_status("waiting_capture", reason="error dialog closed")
        self._update_view()
