"""Lightweight in-process API and workflow operational telemetry."""
from __future__ import annotations

import threading
from typing import Any
from pydantic import BaseModel, Field


class ApiTelemetry(BaseModel):
    total_requests: int = 0
    status_counts: dict[str, int] = Field(default_factory=dict)
    total_request_duration_ms: float = 0.0
    workflows_started: int = 0
    workflows_completed: int = 0
    workflows_interrupted: int = 0
    workflows_failed: int = 0


class TelemetryTracker:
    """Thread-safe lightweight telemetry collector."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data = ApiTelemetry()

    def record_request(self, status_code: int, duration_ms: float) -> None:
        with self._lock:
            self._data.total_requests += 1
            key = str(status_code)
            self._data.status_counts[key] = self._data.status_counts.get(key, 0) + 1
            self._data.total_request_duration_ms += duration_ms

    def record_workflow(self, outcome: str) -> None:
        with self._lock:
            self._data.workflows_started += 1
            if outcome == "interrupted":
                self._data.workflows_interrupted += 1
            elif outcome in ("failed", "blocked"):
                self._data.workflows_failed += 1
            else:
                self._data.workflows_completed += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            avg_ms = (
                round(self._data.total_request_duration_ms / self._data.total_requests, 2)
                if self._data.total_requests > 0
                else 0.0
            )
            return {
                "total_requests": self._data.total_requests,
                "status_counts": dict(self._data.status_counts),
                "avg_request_duration_ms": avg_ms,
                "workflows_started": self._data.workflows_started,
                "workflows_completed": self._data.workflows_completed,
                "workflows_interrupted": self._data.workflows_interrupted,
                "workflows_failed": self._data.workflows_failed,
            }
