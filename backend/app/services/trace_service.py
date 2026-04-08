"""Trace / Observability layer (T-29/30/31 from Triple-Schema v2).

Lightweight per-request trace builder. Each step is timestamped and
serialised into DebugInfo so the frontend (and Studio session view)
can show the full layer pipeline.
"""

from __future__ import annotations

import time
from typing import Any

from app.models.schemas import TraceEntry


class Tracer:
    """Per-request trace recorder. Use as context manager around steps."""

    def __init__(self) -> None:
        self.entries: list[TraceEntry] = []
        self._t0 = time.monotonic()
        self._step_start: float | None = None
        self._cur_step = ""
        self._cur_label = ""

    def start(self, step: str, label: str = "") -> None:
        self._step_start = time.monotonic()
        self._cur_step = step
        self._cur_label = label or step

    def end(self, data: dict[str, Any] | None = None) -> None:
        if self._step_start is None:
            return
        dur = int((time.monotonic() - self._step_start) * 1000)
        self.entries.append(TraceEntry(
            step=self._cur_step,
            label=self._cur_label,
            duration_ms=dur,
            data=data or {},
        ))
        self._step_start = None

    def record(self, step: str, label: str, data: dict[str, Any] | None = None,
               duration_ms: int = 0) -> None:
        """Record an instant entry without start/end."""
        self.entries.append(TraceEntry(
            step=step, label=label, duration_ms=duration_ms, data=data or {},
        ))

    def total_ms(self) -> int:
        return int((time.monotonic() - self._t0) * 1000)
