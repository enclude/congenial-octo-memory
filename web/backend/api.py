"""Endpointy /api/* backendu WWW."""

from __future__ import annotations

import asyncio
import io
import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from piro_overlay import __version__, ffmpeg, pipeline, preview
from piro_overlay.api import ApiError
from piro_overlay.models import Lang, OverlayStyle

from . import filedb, workers
from .jobs import Job, JobState, JobStore
from .ratelimit import render_rate
from .sessions import ensure_sid, require_sid
from .settings import Settings

router = APIRouter(prefix="/api")

_REPO_URL = "https://github.com/enclude/congenial-octo-memory"


@router.get("/version")
def version() -> dict:
    """Wersja aplikacji + link do repo — stopka frontendu (jedno źródło prawdy: __init__.py)."""
    return {"version": __version__, "repo": _REPO_URL}

# Kontenery wideo przyjmowane na wejściu (rozszerzenie z nagłówka X-Filename;
# faktyczną zawartość i tak weryfikuje ffmpeg.probe po zapisie).
_EXT_WHITELIST = {".mp4", ".mov", ".mkv", ".avi"}
_STEM_SAFE_RE = re.compile(r"[^\w\- ]", re.UNICODE)


class _UploadTooBig(Exception):
    pass


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _store(request: Request) -> JobStore:
    return request.app.state.store


def _file_ids_db(settings: Settings, sid: str) -> Path:
    """Baza plik→ID dla tej sesji (per-sid — jak katalogi zadań, bez wycieku między userami)."""
    return settings.data_dir / sid / "file_ids.db"


def _get_job(request: Request, job_id: str, sid: str) -> Job:
    job = _store(request).get(job_id, sid)
    if job is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono zadania.")
    return job


@router.post("/jobs", status_code=201)
async def create_job(request: Request, sid: str = Depends(ensure_sid)) -> dict:
    """Upload wideo surowym strumieniem (body = plik, nazwa w X-Filename).

    Surowy strumień zamiast multipart: czysty licznik bajtów (413 w trakcie,
    nie po fakcie) i zero zależności python-multipart.
    """
    settings = _settings(request)
    store = _store(request)
    if store.count_active(sid) >= settings.max_jobs_per_session:
        raise HTTPException(
            status_code=429,
            detail=f"Limit {settings.max_jobs_per_session} aktywnych zadań — "
                   "usuń poprzednie lub poczekaj na ich wygaśnięcie.")

    filename = request.headers.get("x-filename") or "video.mp4"
    ext = Path(filename).suffix.lower() or ".mp4"
    if ext not in _EXT_WHITELIST:
        raise HTTPException(
            status_code=422,
            detail=f"Nieobsługiwane rozszerzenie {ext} — dozwolone: "
                   + ", ".join(sorted(_EXT_WHITELIST)))

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.max_upload_bytes:
        raise HTTPException(status_code=413,
                            detail=f"Plik przekracza limit {settings.max_upload_mb} MB.")

    job_id = uuid.uuid4().hex
    job_dir = settings.data_dir / sid / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    # Nazwa klienta NIGDY nie trafia do ścieżki — plik zawsze jako source.<ext>.
    dest = job_dir / f"source{ext}"
    received = 0
    try:
        with open(dest, "wb") as f:
            async for chunk in request.stream():
                received += len(chunk)
                if received > settings.max_upload_bytes:
                    raise _UploadTooBig
                await run_in_threadpool(f.write, chunk)
    except _UploadTooBig:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=413,
                            detail=f"Plik przekracza limit {settings.max_upload_mb} MB.")
    except Exception:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise

    if received == 0:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=422, detail="Puste body — prześlij plik wideo.")

    try:
        info = await run_in_threadpool(ffmpeg.probe, str(dest))
    except Exception:  # noqa: BLE001 — probe rzuca RuntimeError przy nie-wideo
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=422,
                            detail="Plik nie wygląda na czytelne wideo.")

    stem = _STEM_SAFE_RE.sub("_", Path(filename).stem).strip()[:80] or "video"
    job = Job(
        id=job_id, sid=sid, dir=job_dir, video_path=dest, orig_stem=stem,
        orig_filename=filename,
        duration=info.duration or None,
        video_size=(info.width, info.height) if info.width else None,
    )
    store.add(job)
    data = job.to_dict()
    data["suggested_id"] = filedb.lookup(_file_ids_db(settings, sid), filename)
    return data


@router.get("/jobs/{job_id}")
def get_job(request: Request, job_id: str, sid: str = Depends(require_sid)) -> dict:
    return _get_job(request, job_id, sid).to_dict()


async def _in_analyze_pool(request: Request, fn, *args):
    loop: asyncio.AbstractEventLoop = request.app.state.loop
    return await loop.run_in_executor(request.app.state.analyze_pool, fn, *args)


class SessionBody(BaseModel):
    source: Literal["id", "timeline"]
    id: int | None = None
    timeline: str | None = None


@router.post("/jobs/{job_id}/session")
async def set_session(request: Request, job_id: str, body: SessionBody,
                      sid: str = Depends(require_sid)) -> dict:
    """Oś czasu strzałów: z API kalkulatora (ID) albo z wklejonego tekstu."""
    job = _get_job(request, job_id, sid)
    if body.source == "id" and body.id is None:
        raise HTTPException(status_code=422, detail="Podaj ID wyniku.")
    if body.source == "timeline" and not (body.timeline or "").strip():
        raise HTTPException(status_code=422, detail="Wklej oś czasu strzałów.")
    timeline = body.timeline if body.source == "timeline" else None
    result_id = body.id if body.source == "id" else None
    try:
        session = await _in_analyze_pool(
            request, pipeline.build_session, timeline, result_id)
    except ApiError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Błędna oś czasu: {exc}")
    if session is None or not session.shots:
        raise HTTPException(status_code=422,
                            detail="Nie rozpoznano żadnego strzału w osi czasu.")
    job.session = session
    job.preview_cache = None
    # Zapamiętane dopiero przy renderze (start_render) — same przymiarki się nie liczą.
    job.session_source_id = result_id
    return job.to_dict()


@router.post("/jobs/{job_id}/analyze")
async def analyze(request: Request, job_id: str,
                  sid: str = Depends(require_sid)) -> dict:
    """Auto-detekcja T0 (bzyczek shot-timera) + auto-przycięcie.

    Brak bzyczka to nie błąd — zwracamy t0=null, frontend prosi o ręczne T0.
    """
    job = _get_job(request, job_id, sid)
    if job.state in (JobState.QUEUED, JobState.RENDERING):
        raise HTTPException(status_code=409, detail="Zadanie jest w trakcie renderu.")
    prev_state = job.state
    job.state = JobState.ANALYZING
    try:
        t0 = await _in_analyze_pool(
            request, pipeline.detect_start_signal, job.video_path)
    except Exception as exc:  # noqa: BLE001 — analiza audio nie może ubić zadania
        job.state = prev_state
        raise HTTPException(status_code=500, detail=f"Analiza audio nie powiodła się: {exc}")
    if t0 is None:
        job.state = prev_state
        return {"t0": None, "trim_start": None, "trim_end": None}
    trim_start, trim_end = pipeline.compute_trim(
        t0, job.session, job.duration, auto=True)
    job.t0 = t0
    job.trim_start, job.trim_end = trim_start, trim_end
    job.state = JobState.READY
    return {"t0": t0, "trim_start": trim_start, "trim_end": trim_end}


@router.post("/jobs/{job_id}/detect-id")
async def detect_id(request: Request, job_id: str,
                    sid: str = Depends(require_sid)) -> dict:
    """Dekoduje ID sesji z sygnału tonowego (timer po zapisie w bazie).

    Brak sygnału to nie błąd — zwracamy id=null, frontend prosi o ręczne ID.
    """
    job = _get_job(request, job_id, sid)
    if job.state in (JobState.QUEUED, JobState.RENDERING):
        raise HTTPException(status_code=409, detail="Zadanie jest w trakcie renderu.")
    try:
        detected = await _in_analyze_pool(request, pipeline.detect_id_tone, job.video_path)
    except Exception as exc:  # noqa: BLE001 — analiza audio nie może ubić zadania
        raise HTTPException(status_code=500, detail=f"Analiza audio nie powiodła się: {exc}")
    return {"id": detected}


def _extract_preview_frame(job: Job, t: float, h: int):
    """Klatka RGBA dla czasu t (wątek analizy) — z cache per zadanie."""
    key = (round(t, 2), h)
    if job.preview_cache and job.preview_cache[0] == key:
        return job.preview_cache[1]
    from PIL import Image
    png = job.dir / "preview.png"
    ffmpeg.extract_frame(job.video_path, t, png, scale_height=h)
    frame = Image.open(png).convert("RGBA")
    frame.load()
    job.preview_cache = (key, frame)
    return frame


@router.get("/jobs/{job_id}/preview")
async def preview_frame(request: Request, job_id: str, t: float = 0.0,
                        t0: float | None = None, lang: str = "pl",
                        clock: bool = False, h: int = 480,
                        sid: str = Depends(require_sid)) -> Response:
    """PNG klatki z czasu t z nakładką aktywną dla tego czasu (WYSIWYG)."""
    job = _get_job(request, job_id, sid)
    duration = job.duration or 0.0
    if not 0.0 <= t <= max(duration, 0.0):
        raise HTTPException(status_code=422, detail="Czas poza zakresem wideo.")
    if not 120 <= h <= 720:
        raise HTTPException(status_code=422, detail="Wysokość podglądu 120–720 px.")
    try:
        style_lang = Lang(lang)
    except ValueError:
        raise HTTPException(status_code=422, detail="Nieznany język.")
    frame = await _in_analyze_pool(request, _extract_preview_frame, job, t, h)
    style = OverlayStyle(lang=style_lang, show_running_clock=clock)
    eff_t0 = t0 if t0 is not None else (job.t0 or 0.0)
    video_h = job.video_size[1] if job.video_size else None
    composite = preview.compose_preview(
        frame, job.session, t, eff_t0, style, duration or t + 10.0,
        video_h=video_h)
    buf = io.BytesIO()
    composite.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "no-store"})


class RenderBody(BaseModel):
    format: Literal["mp4", "webm", "gif"] = "mp4"
    lang: str = "pl"
    clock: bool = False
    t0: float | None = None
    trim_start: float | None = None
    trim_end: float | None = None
    no_overlay: bool = False


@router.post("/jobs/{job_id}/render", status_code=202,
             dependencies=[Depends(render_rate)])
async def start_render(request: Request, job_id: str, body: RenderBody,
                       sid: str = Depends(require_sid)) -> dict:
    job = _get_job(request, job_id, sid)
    if job.state in (JobState.QUEUED, JobState.RENDERING):
        raise HTTPException(status_code=409, detail="Render już trwa.")
    if not body.no_overlay and (job.session is None or not job.session.shots):
        raise HTTPException(status_code=422,
                            detail="Najpierw ustaw oś czasu strzałów (ID lub tekst) "
                                   "albo włącz „tylko przytnij”.")
    if body.no_overlay and body.format != "mp4":
        raise HTTPException(status_code=422,
                            detail="Tryb „tylko przytnij” renderuje wyłącznie MP4.")
    t0 = body.t0 if body.t0 is not None else job.t0
    if not body.no_overlay and t0 is None:
        raise HTTPException(status_code=422,
                            detail="Brak T0 — użyj auto-detekcji lub podaj ręcznie.")
    try:
        lang = Lang(body.lang)
    except ValueError:
        raise HTTPException(status_code=422, detail="Nieznany język.")
    duration = job.duration
    ts, te = body.trim_start, body.trim_end
    if ts is not None and ts < 0:
        raise HTTPException(status_code=422, detail="trim_start < 0.")
    if ts is not None and te is not None and te <= ts:
        raise HTTPException(status_code=422, detail="trim_end ≤ trim_start.")
    if duration and te is not None and te > duration + 1.0:
        raise HTTPException(status_code=422, detail="trim_end poza końcem wideo.")

    job.t0 = t0
    job.trim_start, job.trim_end = ts, te
    job.cancel.clear()
    job.progress = 0.0
    job.error = None
    job.encoder = None
    job.output_path = None
    job.finished = None
    job.state = JobState.QUEUED
    if job.session_source_id is not None:
        try:
            filedb.remember(_file_ids_db(_settings(request), sid),
                            job.orig_filename, job.session_source_id)
        except Exception:  # noqa: BLE001 — zapamiętanie ID nie może zablokować renderu
            pass
    style = OverlayStyle(lang=lang, show_running_clock=body.clock)
    request.app.state.render_pool.submit(
        workers.run_render, job, _settings(request), request.app.state.loop,
        body.format, style, body.no_overlay)
    return job.to_dict()


def _sse(event: dict) -> str:
    return f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"


@router.get("/jobs/{job_id}/events")
async def job_events(request: Request, job_id: str,
                     sid: str = Depends(require_sid)) -> StreamingResponse:
    """SSE ze stanem zadania: state / progress / encoder / done / error."""
    job = _get_job(request, job_id, sid)

    async def gen():
        q = job.broker.subscribe()
        try:
            # Snapshot na wejście — refresh strony od razu widzi bieżący stan.
            yield _sse(job.snapshot_event())
            if not job.active:
                return
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        return  # klient zamknął EventSource — nie żyj wiecznie
                    yield ": ping\n\n"  # heartbeat — proxy nie zamyka połączenia
                    continue
                yield _sse(event)
                if event["event"] in ("done", "error") or (
                        event["event"] == "state" and not job.active):
                    return
        finally:
            job.broker.unsubscribe(q)

    # X-Accel-Buffering wyłącza buforowanie w nginx/NPM — SSE musi płynąć.
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@router.post("/jobs/{job_id}/cancel")
def cancel_job(request: Request, job_id: str,
               sid: str = Depends(require_sid)) -> dict:
    """Przerywa render: flaga + kill procesu FFmpeg (odblokowuje czytanie stderr)."""
    job = _get_job(request, job_id, sid)
    job.cancel.set()
    proc = job.proc
    if proc is not None:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001 — proces mógł właśnie się zakończyć
            pass
    return job.to_dict()


@router.get("/jobs/{job_id}/download")
def download(request: Request, job_id: str,
             sid: str = Depends(require_sid)) -> FileResponse:
    job = _get_job(request, job_id, sid)
    if job.output_path is None or not job.output_path.exists():
        raise HTTPException(status_code=404, detail="Wynik nie jest gotowy.")
    return FileResponse(job.output_path,
                        filename=f"{job.orig_stem}_PiRoOverlay{job.output_ext}")


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job(request: Request, job_id: str,
               sid: str = Depends(require_sid)) -> Response:
    job = _get_job(request, job_id, sid)
    job.cancel.set()
    proc = job.proc
    if proc is not None:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
    _store(request).remove(job_id)
    shutil.rmtree(job.dir, ignore_errors=True)
    return Response(status_code=204)
