"""Praca w tle: render zadania w puli wątków (poza pętlą asyncio).

Wątek renderu komunikuje się ze światem wyłącznie przez pola Joba i
`EventBroker.publish_threadsafe` — dokładnie te same haki, których używa GUI
(`progress_cb`, `cancel_check`, `on_process`, `on_encoder`).
"""

from __future__ import annotations

import asyncio
import time

from piro_overlay import render
from piro_overlay.models import AnchorMode, OverlayStyle

from .jobs import Job, JobState
from .settings import Settings

_FORMAT_EXT = {"mp4": ".mp4", "webm": ".webm", "gif": ".gif"}
_PROGRESS_INTERVAL_S = 0.25  # throttling zdarzeń SSE `progress` (~4/s)


def run_render(job: Job, settings: Settings, loop: asyncio.AbstractEventLoop,
               fmt: str, style: OverlayStyle, no_overlay: bool = False) -> None:
    """Body wątku renderu — wołane przez ThreadPoolExecutor.submit."""

    def publish(event: str, data: dict) -> None:
        job.broker.publish_threadsafe(loop, {"event": event, "data": data})

    if job.cancel.is_set():  # anulowano zanim zadanie doczekało się workera
        job.state = JobState.CANCELLED
        job.finished = time.time()
        publish("state", job.to_dict())
        return

    job.state = JobState.RENDERING
    publish("state", job.to_dict())

    out = job.dir / f"output{_FORMAT_EXT[fmt]}"
    last_emit = 0.0

    def on_progress(p: float) -> None:
        nonlocal last_emit
        job.progress = p
        now = time.monotonic()
        if now - last_emit >= _PROGRESS_INTERVAL_S:
            last_emit = now
            publish("progress", {"p": round(p, 4)})

    def on_encoder(name: str) -> None:
        job.encoder = name
        publish("encoder", {"name": name})

    def on_process(proc) -> None:
        job.proc = proc

    common = dict(progress_cb=on_progress, trim_start=job.trim_start,
                  trim_end=job.trim_end, cancel_check=job.cancel.is_set,
                  on_process=on_process)
    try:
        if no_overlay:
            render.trim_video(job.video_path, out, encoder=settings.encoder,
                              on_encoder=on_encoder, **common)
        elif fmt == "mp4":
            render.render_video(job.video_path, job.session, job.t0, style,
                                AnchorMode.START_SIGNAL, out,
                                encoder=settings.encoder, on_encoder=on_encoder,
                                **common)
        elif fmt == "webm":
            render.render_webm(job.video_path, job.session, job.t0, style,
                               AnchorMode.START_SIGNAL, out, **common)
        else:
            render.render_gif(job.video_path, job.session, job.t0, style,
                              AnchorMode.START_SIGNAL, out, **common)
        job.output_path = out
        job.output_ext = _FORMAT_EXT[fmt]
        job.progress = 1.0
        job.state = JobState.DONE
        job.finished = time.time()
        publish("done", {"url": f"/api/jobs/{job.id}/download"})
    except render.RenderCancelled:
        out.unlink(missing_ok=True)
        job.state = JobState.CANCELLED
        job.finished = time.time()
        publish("state", job.to_dict())
    except Exception as exc:  # noqa: BLE001 — błąd renderu nie może ubić puli
        out.unlink(missing_ok=True)
        msg = str(exc)
        if len(msg) > 800:
            # pierwsza linia niesie kod wyjścia i pozycję — nie może wypaść z ucięcia
            head, _, rest = msg.partition("\n")
            msg = head[:200] + "\n…\n" + rest[-600:]
        job.error = msg
        job.state = JobState.FAILED
        job.finished = time.time()
        publish("error", {"message": job.error})
    finally:
        job.proc = None
