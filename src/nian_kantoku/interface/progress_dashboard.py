from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, TextIO


_STAGE_LABELS = {
    "cli": "CLI startup",
    "run": "Pipeline",
    "runtime_check": "Runtime checks",
    "layout": "Output layout",
    "character_extraction": "Character extraction",
    "character_design": "Character design",
    "storyboard": "Storyboard",
    "storyboard_model": "Storyboard model",
    "storyboard_validation": "Storyboard validation",
    "storyboard_regeneration": "Storyboard regeneration",
    "background_design": "Background design",
    "style_consistency": "Style anchors",
    "shot": "Shot processing",
    "image_generate": "Keyframe generation",
    "keyframe_download": "Keyframe download",
    "video_task_create": "Video task create",
    "video_task_poll": "Video task poll",
    "clip_download": "Clip download",
    "merge": "Final merge",
}

_EVENT_SHOT_STATUS = {
    "shot_started": "Running",
    "image_generation_started": "Keyframe generating",
    "video_task_created": "Video generating",
    "shot_succeeded": "Done",
    "shot_failed": "Failed",
}


@dataclass
class _ShotProgress:
    shot_id: str
    shot_index: int = 0
    status: str = "Pending"


class _DashboardHandler(logging.Handler):
    def __init__(self, dashboard: "RunProgressDashboard") -> None:
        super().__init__(level=logging.INFO)
        self._dashboard = dashboard

    def emit(self, record: logging.LogRecord) -> None:
        self._dashboard.consume(record)


class RunProgressDashboard:
    def __init__(
        self,
        *,
        enabled: bool,
        stream: Optional[TextIO] = None,
    ) -> None:
        self._stream = stream or sys.stdout
        is_tty = getattr(self._stream, "isatty", None)
        self._is_tty = bool(callable(is_tty) and is_tty())
        self._enabled = bool(enabled)
        self._start_time = time.monotonic()
        self._status = "Running"
        self._stage = "Waiting to start"
        self._activity = "Waiting for first event"
        self._total_shots = 0
        self._completed_shots = 0
        self._failed_shots = 0
        self._current_shot = "-"
        self._shots: Dict[str, _ShotProgress] = {}
        self._warnings: List[str] = []
        self._handler = _DashboardHandler(self)
        self._started = False
        self._live = None
        self._console = None
        self._rich = False
        self._last_plain_snapshot = ""
        if self._enabled and self._is_tty:
            try:
                from rich.console import Console

                self._console = Console(file=self._stream)
                self._rich = True
            except Exception:  # noqa: BLE001
                self._rich = False

    def start(self, logger: logging.Logger) -> None:
        if not self._enabled or self._started:
            return
        logger.addHandler(self._handler)
        self._started = True
        if self._rich:
            from rich.live import Live

            self._live = Live(
                self._render_rich(),
                console=self._console,
                refresh_per_second=8,
                transient=False,
            )
            self._live.start()
        else:
            self._render_plain()

    def stop(self, logger: logging.Logger) -> None:
        if not self._started:
            return
        logger.removeHandler(self._handler)
        if self._live is not None:
            self._live.stop()
        self._started = False

    def consume(self, record: logging.LogRecord) -> None:
        if not self._started:
            return

        event = str(getattr(record, "event", "log"))
        stage = str(getattr(record, "stage", "runtime"))
        message = record.getMessage()
        shot_id = getattr(record, "shot_id", None)
        shot_index = getattr(record, "shot_index", None)
        total_shots = int(getattr(record, "total_shots", 0) or 0)
        completed_shots = int(getattr(record, "completed_shots", 0) or 0)
        failed_shots = int(getattr(record, "failed_shots", 0) or 0)

        self._stage = _STAGE_LABELS.get(stage, stage)
        self._activity = message

        if total_shots > 0:
            self._total_shots = max(self._total_shots, total_shots)
        self._completed_shots = max(self._completed_shots, completed_shots)
        self._failed_shots = max(self._failed_shots, failed_shots)

        if shot_id:
            progress = self._shots.get(shot_id)
            if progress is None:
                progress = _ShotProgress(shot_id=shot_id, shot_index=int(shot_index or 0))
                self._shots[shot_id] = progress
            if shot_index and int(shot_index) > 0:
                progress.shot_index = int(shot_index)
            if event in _EVENT_SHOT_STATUS:
                progress.status = _EVENT_SHOT_STATUS[event]
            self._current_shot = shot_id

        if event == "run_completed":
            self._status = "Partial failed" if self._failed_shots else "Succeeded"
            self._activity = "Run finished, preparing final output"
        elif event == "cli_failed":
            self._status = "Failed"

        if record.levelno >= logging.WARNING:
            error = getattr(record, "error", None)
            warning_text = f"{self._stage}: {error or message}"
            self._warnings.append(warning_text)
            self._warnings = self._warnings[-3:]

        if self._rich and self._live is not None:
            self._live.update(self._render_rich(), refresh=True)
            return
        self._render_plain()

    def _render_rich(self):
        from rich import box
        from rich.console import Group
        from rich.panel import Panel
        from rich.table import Table

        elapsed = int(time.monotonic() - self._start_time)
        progress_text = "-"
        if self._total_shots > 0:
            progress_text = (
                f"{self._completed_shots}/{self._total_shots} "
                f"(failed {self._failed_shots}) {self._progress_bar()}"
            )

        summary = Table(show_header=False, box=box.SIMPLE)
        summary.add_row("Status", self._status)
        summary.add_row("Stage", self._stage)
        summary.add_row("Current Shot", self._current_shot)
        summary.add_row("Shot Progress", progress_text)
        summary.add_row("Elapsed", f"{elapsed}s")
        summary.add_row("Activity", self._activity)

        shots_table = Table(box=box.MINIMAL_DOUBLE_HEAD, expand=True)
        shots_table.add_column("Shot")
        shots_table.add_column("Status")
        if self._shots:
            for shot in self._ordered_shots():
                shots_table.add_row(self._shot_label(shot), shot.status)
        else:
            shots_table.add_row("-", "Waiting for storyboard")

        warning_text = "\n".join(self._warnings) if self._warnings else "None"
        return Group(
            Panel(summary, title="Nian Kantoku Progress", border_style="cyan"),
            Panel(shots_table, title="Shot Status", border_style="green"),
            Panel(warning_text, title="Recent Warnings", border_style="yellow"),
        )

    def _render_plain(self) -> None:
        elapsed = int(time.monotonic() - self._start_time)
        progress_text = "-"
        if self._total_shots > 0:
            progress_text = (
                f"{self._completed_shots}/{self._total_shots} "
                f"(failed {self._failed_shots})"
            )
        snapshot = (
            f"[progress] status={self._status} stage={self._stage} "
            f"shot={self._current_shot} shots={progress_text} elapsed={elapsed}s"
        )
        if snapshot == self._last_plain_snapshot:
            return
        self._stream.write(snapshot + "\n")
        self._stream.flush()
        self._last_plain_snapshot = snapshot

    def _ordered_shots(self) -> List[_ShotProgress]:
        return sorted(
            self._shots.values(),
            key=lambda item: (item.shot_index if item.shot_index > 0 else 10_000, item.shot_id),
        )

    @staticmethod
    def _shot_label(item: _ShotProgress) -> str:
        if item.shot_index > 0:
            return f"{item.shot_index:02d} | {item.shot_id}"
        return item.shot_id

    def _progress_bar(self) -> str:
        width = 16
        if self._total_shots <= 0:
            return "-" * width
        ratio = min(1.0, self._completed_shots / self._total_shots)
        filled = int(ratio * width)
        return "#" * filled + "-" * (width - filled)
