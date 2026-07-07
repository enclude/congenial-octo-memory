"""Model zadań backendu WWW: stany, magazyn in-memory i rozgłaszanie zdarzeń.

Magazyn jest świadomie in-memory (dict + lock): pliki zadań i tak są ulotne
(TTL ~2 h), a restart procesu = czysty start (cleanup usuwa osierocone
katalogi z dysku). Konsekwencja: DOKŁADNIE JEDEN proces uvicorn
(`--workers 1`); równoległość dają pule wątków.
"""

from __future__ import annotations

import asyncio
import subprocess
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from piro_overlay.models import Session

# Stany terminalne — zadanie nie zajmuje już miejsca w limicie sesji.
_TERMINAL = None  # ustawiane niżej (po definicji JobState)


class JobState(str, Enum):
    UPLOADED = "uploaded"
    ANALYZING = "analyzing"
    READY = "ready"
    QUEUED = "queued"
    RENDERING = "rendering"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


_TERMINAL = {JobState.DONE, JobState.FAILED, JobState.CANCELLED}


class EventBroker:
    """Rozgłasza zdarzenia SSE jednego zadania do subskrybentów (asyncio).

    Wątek roboczy publikuje przez `publish_threadsafe(loop, event)`;
    nowy subskrybent najpierw dostaje snapshot stanu (refresh strony działa).
    """

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue] = []
        self._lock = threading.Lock()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def publish_threadsafe(self, loop: asyncio.AbstractEventLoop, event: dict) -> None:
        with self._lock:
            targets = list(self._subscribers)
        for q in targets:
            loop.call_soon_threadsafe(q.put_nowait, event)


@dataclass
class Job:
    id: str
    sid: str
    dir: Path
    video_path: Path
    orig_stem: str
    orig_filename: str
    duration: float | None = None
    video_size: tuple[int, int] | None = None
    session: Session | None = None
    # ID API użyte w /session (source="id") — do zapamiętania dopasowania plik→ID
    # w filedb, dopiero po kliknięciu „Renderuj" (patrz api.start_render).
    session_source_id: int | None = None
    t0: float | None = None
    trim_start: float | None = None
    trim_end: float | None = None
    state: JobState = JobState.UPLOADED
    progress: float = 0.0
    encoder: str | None = None
    error: str | None = None
    output_path: Path | None = None
    output_ext: str | None = None
    created: float = field(default_factory=time.time)
    finished: float | None = None
    cancel: threading.Event = field(default_factory=threading.Event)
    proc: subprocess.Popen | None = None
    broker: EventBroker = field(default_factory=EventBroker)
    # Cache podglądu: (klucz ekstrakcji (t, h), klatka RGBA) — ta sama klatka
    # przy zmianie stylu/T0 nie kosztuje kolejnego przebiegu FFmpeg.
    preview_cache: tuple[tuple, object] | None = None

    @property
    def active(self) -> bool:
        return self.state not in _TERMINAL

    def to_dict(self) -> dict:
        shots = None
        if self.session is not None:
            shots = [{"numer": s.numer, "czas": s.czas, "split": s.split}
                     for s in self.session.shots]
        return {
            "id": self.id,
            "state": self.state.value,
            "progress": round(self.progress, 4),
            "duration": self.duration,
            "width": self.video_size[0] if self.video_size else None,
            "height": self.video_size[1] if self.video_size else None,
            "t0": self.t0,
            "trim_start": self.trim_start,
            "trim_end": self.trim_end,
            "encoder": self.encoder,
            "error": self.error,
            "output_ready": self.output_path is not None,
            "shots": shots,
            "session_meta": {
                "nazwa_toru": self.session.nazwa_toru,
                "uczestnik": self.session.uczestnik,
                "start_delay": self.session.start_delay,
            } if self.session is not None else None,
        }

    def snapshot_event(self) -> dict:
        """Zdarzenie SSE opisujące bieżący stan (dla świeżego subskrybenta)."""
        return {"event": "state", "data": self.to_dict()}


class JobStore:
    """Magazyn zadań in-memory. Wszystkie metody bezpieczne wątkowo."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def add(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.id] = job

    def get(self, job_id: str, sid: str) -> Job | None:
        """Zadanie o danym id, ale tylko właściciela — cudze jak nieistniejące."""
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None or job.sid != sid:
            return None
        return job

    def remove(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.pop(job_id, None)

    def all(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    def count_active(self, sid: str) -> int:
        with self._lock:
            return sum(1 for j in self._jobs.values()
                       if j.sid == sid and j.active)
