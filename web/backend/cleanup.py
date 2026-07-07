"""Sprzątanie zadań i plików: TTL po zakończeniu, twardy limit wieku,
osierocone katalogi po restarcie procesu (magazyn jest in-memory).
"""

from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path

from .jobs import JobStore
from .ratelimit import TokenBucket
from .settings import Settings

_INTERVAL_S = 600.0  # co 10 minut


def sweep(store: JobStore, settings: Settings, now: float | None = None) -> int:
    """Jeden przebieg sprzątania. Zwraca liczbę usuniętych zadań (testowalne)."""
    now = time.time() if now is None else now
    ttl_s = settings.job_ttl_min * 60
    max_age_s = settings.max_job_age_min * 60
    removed = 0
    known_dirs: set[Path] = set()
    for job in store.all():
        known_dirs.add(job.dir.resolve())
        expired = (not job.active and job.finished is not None
                   and now - job.finished > ttl_s)
        too_old = now - job.created > max_age_s
        if not (expired or too_old):
            continue
        job.cancel.set()
        proc = job.proc
        if proc is not None:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
        store.remove(job.id)
        shutil.rmtree(job.dir, ignore_errors=True)
        known_dirs.discard(job.dir.resolve())
        removed += 1
    # Katalogi na dysku bez wpisu w magazynie (np. po restarcie procesu).
    if settings.data_dir.is_dir():
        for sid_dir in settings.data_dir.iterdir():
            if not sid_dir.is_dir():
                continue
            for job_dir in sid_dir.iterdir():
                if job_dir.is_dir() and job_dir.resolve() not in known_dirs:
                    shutil.rmtree(job_dir, ignore_errors=True)
            if not any(sid_dir.iterdir()):
                sid_dir.rmdir()
    return removed


async def cleanup_loop(store: JobStore, settings: Settings,
                       buckets: list[TokenBucket]) -> None:
    """Pętla w tle: sweep + przycinanie martwych wiader rate-limitu."""
    while True:
        try:
            sweep(store, settings)
            for bucket in buckets:
                bucket.prune()
        except Exception:  # noqa: BLE001 — sprzątanie nie może ubić aplikacji
            pass
        await asyncio.sleep(_INTERVAL_S)
