from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


RUN_LOGGER_NAME = "nian_kantoku.run"
RUN_LOG_FILE = "run.log"
EVENT_LOG_FILE = "events.jsonl"


class _BaseEventFormatter(logging.Formatter):
    @classmethod
    def _build_payload(cls, record: logging.LogRecord) -> dict[str, Any]:
        timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        payload = {
            "timestamp": timestamp,
            "level": record.levelname,
            "event": getattr(record, "event", "log"),
            "stage": getattr(record, "stage", "runtime"),
            "message": record.getMessage(),
            "shot_id": getattr(record, "shot_id", None),
            "shot_index": getattr(record, "shot_index", None),
            "total_shots": getattr(record, "total_shots", 0),
            "completed_shots": getattr(record, "completed_shots", 0),
            "failed_shots": getattr(record, "failed_shots", 0),
            "error": getattr(record, "error", None),
            "details": getattr(record, "details", None),
        }
        if record.exc_info and not payload["error"]:
            payload["error"] = cls._safe_exception_text(record)
        return payload

    @staticmethod
    def _safe_exception_text(record: logging.LogRecord) -> Optional[str]:
        if not record.exc_info:
            return None
        exc_type, exc_value, _ = record.exc_info
        if exc_type is None or exc_value is None:
            return None
        return f"{exc_type.__name__}: {exc_value}"


class _TextEventFormatter(_BaseEventFormatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = self._build_payload(record)
        details_text = ""
        if payload["details"] is not None:
            details_text = f" | details={json.dumps(payload['details'], ensure_ascii=False, sort_keys=True)}"
        return (
            f"{payload['timestamp']} | {payload['level']} | {payload['event']} | "
            f"{payload['stage']} | shot={payload['shot_id']} idx={payload['shot_index']} | "
            f"progress={payload['completed_shots']}/{payload['total_shots']} failed={payload['failed_shots']} | "
            f"{payload['message']}"
            + (f" | error={payload['error']}" if payload["error"] else "")
            + details_text
        )


class _JsonlEventFormatter(_BaseEventFormatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = self._build_payload(record)
        return json.dumps(payload, ensure_ascii=False)


def _reset_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:  # noqa: BLE001
            pass


def configure_run_logging(output_dir: Path) -> logging.Logger:
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(RUN_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    _reset_handlers(logger)

    text_formatter = _TextEventFormatter()
    json_formatter = _JsonlEventFormatter()
    run_log_handler = logging.FileHandler(
        output_dir / RUN_LOG_FILE,
        mode="w",
        encoding="utf-8",
    )
    run_log_handler.setLevel(logging.INFO)
    run_log_handler.setFormatter(text_formatter)

    events_log_handler = logging.FileHandler(
        output_dir / EVENT_LOG_FILE,
        mode="w",
        encoding="utf-8",
    )
    events_log_handler.setLevel(logging.INFO)
    events_log_handler.setFormatter(json_formatter)

    logger.addHandler(run_log_handler)
    logger.addHandler(events_log_handler)
    return logger


def log_run_event(
    *,
    logger: logging.Logger,
    event: str,
    stage: str,
    message: str,
    level: int = logging.INFO,
    shot_id: Optional[str] = None,
    shot_index: Optional[int] = None,
    total_shots: int = 0,
    completed_shots: int = 0,
    failed_shots: int = 0,
    error: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
    exc_info: bool = False,
) -> None:
    logger.log(
        level,
        message,
        extra={
            "event": event,
            "stage": stage,
            "shot_id": shot_id,
            "shot_index": shot_index,
            "total_shots": total_shots,
            "completed_shots": completed_shots,
            "failed_shots": failed_shots,
            "error": error,
            "details": details,
        },
        exc_info=exc_info,
    )
