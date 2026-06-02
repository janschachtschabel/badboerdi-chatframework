"""Trace / Observability layer (T-29/30/31 from Triple-Schema v2).

Lightweight per-request trace builder. Each step is timestamped and
serialised into DebugInfo so the frontend (and Studio session view)
can show the full layer pipeline.

Streaming-Phase-1 — der Tracer kann zusätzlich einen synchronen
Callback aufrufen, sobald ein Step ``start``/``end`` läuft. Der SSE-
Endpoint registriert dort einen Listener, der pro Event eine
``phase``-Nachricht raus schiebt. Bestehende Aufrufer ohne Listener
sind unbeeinflusst — der Callback ist None und wird nur aufgerufen
wenn gesetzt.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from app.models.schemas import TraceEntry


# Type alias for the live-streaming callback.
# Argument: ``("start"|"end"|"record", step, label, data_dict)``
TraceListener = Callable[[str, str, str, dict[str, Any]], None]


class Tracer:
    """Per-request trace recorder. Use as context manager around steps."""

    def __init__(self, listener: TraceListener | None = None) -> None:
        self.entries: list[TraceEntry] = []
        self._t0 = time.monotonic()
        self._step_start: float | None = None
        self._cur_step = ""
        self._cur_label = ""
        self._listener: TraceListener | None = listener

    def set_listener(self, listener: TraceListener | None) -> None:
        """Attach (or detach) a live-event callback. Existing entries are
        unaffected; only future start/end/record calls fire the callback."""
        self._listener = listener

    def _emit(self, kind: str, step: str, label: str, data: dict[str, Any]) -> None:
        """Fire the listener if attached, swallow listener exceptions so a
        broken downstream consumer cannot break the request pipeline."""
        if self._listener is None:
            return
        try:
            self._listener(kind, step, label, data)
        except Exception:
            pass

    def start(self, step: str, label: str = "") -> None:
        self._step_start = time.monotonic()
        self._cur_step = step
        self._cur_label = label or step
        self._emit("start", self._cur_step, self._cur_label, {})

    def end(self, data: dict[str, Any] | None = None) -> None:
        if self._step_start is None:
            return
        dur = int((time.monotonic() - self._step_start) * 1000)
        d = data or {}
        self.entries.append(TraceEntry(
            step=self._cur_step,
            label=self._cur_label,
            duration_ms=dur,
            data=d,
        ))
        self._emit("end", self._cur_step, self._cur_label, {**d, "duration_ms": dur})
        self._step_start = None

    def record(self, step: str, label: str, data: dict[str, Any] | None = None,
               duration_ms: int = 0) -> None:
        """Record an instant entry without start/end."""
        d = data or {}
        self.entries.append(TraceEntry(
            step=step, label=label, duration_ms=duration_ms, data=d,
        ))
        self._emit("record", step, label, {**d, "duration_ms": duration_ms})

    def total_ms(self) -> int:
        return int((time.monotonic() - self._t0) * 1000)

    # ── Welle E (2026-05-23) — Parallel-Gruppen ──────────────────────
    # Wenn mehrere Tasks via asyncio.gather parallel laufen (z.B. Safety +
    # Classify + Memory-Fetch), wollen wir im Studio nicht einen einzigen
    # "parallel"-Step sehen, sondern eine Gruppe mit den individuellen
    # Laufzeiten pro Task — damit man sieht, welcher Task die Phase
    # verlängert. Verwendung:
    #
    #   group = tracer.parallel_group("safety_classify", "Safety+Classify+Memory")
    #   t1 = group.task_start("safety", "OpenAI Moderation")
    #   ...
    #   group.task_end(t1, {"escalated": False})
    #   ... weitere parallel ...
    #   group.finish()  # schreibt Gruppen-Header + alle Tasks als entries
    def parallel_group(self, step: str, label: str = "") -> "ParallelGroup":
        return ParallelGroup(self, step, label or step)


class ParallelGroup:
    """Misst mehrere parallel laufende Tasks innerhalb eines asyncio.gather
    und schreibt sie als Gruppe in den Tracer. Jeder Task hat seinen eigenen
    Start/End-Timestamp (Walltime ist nicht-blocking gemessen — wall clock
    relativ zum gather-Start).

    Sicher gegen nicht-aufgerufenes ``finish()``: bei Garbage-Collection
    bleiben die akkumulierten Tasks im Tracer-Log, der parent_step wird
    aber nur dann eingefügt wenn ``finish()`` explizit gerufen wird.
    """

    def __init__(self, parent: "Tracer", step: str, label: str) -> None:
        self._parent = parent
        self._step = step
        self._label = label
        self._t0 = time.monotonic()
        self._tasks: list[dict[str, Any]] = []

    def task_start(self, name: str, label: str = "") -> dict[str, Any]:
        h = {
            "name": name,
            "label": label or name,
            "started_at_ms": int((time.monotonic() - self._t0) * 1000),
            "duration_ms": 0,
            "data": {},
        }
        return h

    def task_end(self, handle: dict[str, Any], data: dict[str, Any] | None = None) -> None:
        handle["duration_ms"] = (
            int((time.monotonic() - self._t0) * 1000) - handle["started_at_ms"]
        )
        if data:
            handle["data"] = data
        self._tasks.append(handle)

    def finish(self, data: dict[str, Any] | None = None) -> None:
        """Group-Wrapper als TraceEntry schreiben — enthält ``tasks`` mit den
        pro-Task-Zeiten. Studio rendert das als horizontalen Stack mit
        individuellen Bars."""
        total = int((time.monotonic() - self._t0) * 1000)
        wrap = {
            **(data or {}),
            "parallel": True,
            "task_count": len(self._tasks),
            "tasks": list(self._tasks),
            "duration_ms": total,
        }
        self._parent.entries.append(TraceEntry(
            step=self._step, label=self._label,
            duration_ms=total, data=wrap,
        ))
        self._parent._emit("end", self._step, self._label, wrap)
