"""Złożenie finalnego wideo z wypaloną nakładką (jeden przebieg FFmpeg).

Budujemy listę zdarzeń (plansza START, panele strzałów, panel podsumowania), każde
z rozłącznym oknem czasowym, renderujemy je do PNG (Pillow) i nakładamy łańcuchem
filtrów `overlay=...:enable='between(t,a,b)'`. Audio i obraz źródłowy są zachowane.
"""

from __future__ import annotations

import functools
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import ffmpeg, overlay
from .models import AnchorMode, OverlayStyle, Session

ProgressCb = Callable[[float], None]  # postęp 0.0–1.0

_LAST_SHOT_HOLD = 2.0  # ile sekund trzymać panel ostatniego strzału przed podsumowaniem


@dataclass
class _Event:
    image: "overlay.Image.Image"
    start: float
    end: float
    centered: bool = False


def build_events(session: Session, t0: float, style: OverlayStyle, mode: AnchorMode,
                 video_size: tuple[int, int], duration: float) -> list[_Event]:
    """Tworzy listę zdarzeń nakładki z rozłącznymi oknami czasowymi."""
    shots = session.shots
    events: list[_Event] = []
    if not shots:
        return events

    first_t = t0 + shots[0].czas

    # Plansza START — tylko gdy znamy moment sygnału (kotwica = sygnał startu).
    # Plansza START pojawia się zawsze gdy T0 >= 0 (buzzer mieści się w nagraniu),
    # niezależnie od trybu kotwicy — FIRST_SHOT też oblicza T0 z przesunięcia.
    if style.start_banner_duration > 0:
        banner_start = max(t0, 0.0)
        banner_end = min(t0 + style.start_banner_duration, first_t)
        if banner_end > banner_start:
            events.append(_Event(
                overlay.render_start_banner(style, video_size),
                start=banner_start, end=banner_end, centered=True,
            ))

    # Panele strzałów.
    n = len(shots)
    for i in range(n):
        start = t0 + shots[i].czas
        if i < n - 1:
            end = t0 + shots[i + 1].czas
        else:
            end = min(start + _LAST_SHOT_HOLD, duration)
        events.append(_Event(
            overlay.render_shot_panel(session, i, style, video_size),
            start=start, end=end,
        ))

    # Panel podsumowania — od końca ostatniego panelu strzału do końca filmu.
    summary_start = events[-1].end
    if duration > summary_start:
        events.append(_Event(
            overlay.render_summary_panel(session, style, video_size),
            start=summary_start, end=duration,
        ))

    return events


def _overlay_xy(ev: _Event, style: OverlayStyle, video_size: tuple[int, int]) -> tuple[int, int]:
    if ev.centered:
        vw, vh = video_size
        pw, ph = ev.image.size
        return (vw - pw) // 2, (vh - ph) // 2
    return overlay.panel_origin(ev.image.size, video_size, style)


AUTO_TRIM_LEAD_IN = 5.0  # ile sekund przed T0 (beep) zostawić w wyniku


def auto_trim_window(t0: float, last_shot_time: float, tail: float = 5.0,
                     lead_in: float = AUTO_TRIM_LEAD_IN,
                     duration: float | None = None) -> tuple[float, float]:
    """Wylicza fragment do automatycznego przycięcia wyniku.

    Zwraca (start, end): od `T0 - lead_in` (nie mniej niż 0) do
    `T0 + last_shot_time + tail`, ograniczone długością źródła (jeśli podana).
    """
    start = max(0.0, t0 - lead_in)
    end = t0 + last_shot_time + tail
    if duration is not None:
        end = min(end, duration)
    return start, end


# Warianty argumentów NVENC (od preferowanego). Różne buildy/sterowniki FFmpeg
# akceptują różne kombinacje — wybieramy pierwszy, który realnie zakoduje klatkę.
_NVENC_VARIANTS = [
    ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "23", "-b:v", "0", "-pix_fmt", "yuv420p"],
    ["-c:v", "h264_nvenc", "-preset", "medium", "-cq", "23", "-pix_fmt", "yuv420p"],
    ["-c:v", "h264_nvenc", "-rc", "constqp", "-qp", "23", "-pix_fmt", "yuv420p"],
    ["-c:v", "h264_nvenc", "-b:v", "12M", "-pix_fmt", "yuv420p"],
]

_nvenc_error: str | None = None       # skrócony powód (do tooltipa)
_nvenc_error_full: str = ""            # pełny stderr ostatniej nieudanej próby


@functools.lru_cache(maxsize=1)
def working_nvenc_args() -> tuple[str, ...] | None:
    """Zwraca pierwszy zestaw argumentów NVENC, który REALNIE koduje (lub None).

    Próbujemy zakodować 1 klatkę każdym wariantem — dzięki temu adaptujemy się do
    konkretnego FFmpeg/sterownika. Powód niepowodzenia zapisujemy w `_nvenc_error*`.
    """
    global _nvenc_error, _nvenc_error_full
    if not ffmpeg.has_nvenc():
        _nvenc_error = "Brak enkodera h264_nvenc w FFmpeg (zainstaluj pełny FFmpeg)."
        _nvenc_error_full = _nvenc_error
        return None
    last = ""
    for variant in _NVENC_VARIANTS:
        cmd = [ffmpeg.ffmpeg_exe(), "-hide_banner", "-f", "lavfi",
               "-i", "testsrc=duration=0.1:size=256x256:rate=5",
               *variant, "-frames:v", "1", "-f", "null", "-"]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True,
                                 creationflags=ffmpeg.CREATE_NO_WINDOW)
            if res.returncode == 0:
                _nvenc_error = None
                _nvenc_error_full = ""
                return tuple(variant)
            last = res.stderr
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
    _nvenc_error_full = last or "Test NVENC nie powiódł się."
    _nvenc_error = _short_err(Exception(last)) if last else "Test NVENC nie powiódł się."
    return None


def nvenc_works() -> bool:
    return working_nvenc_args() is not None


def nvenc_diagnostic(full: bool = False) -> str | None:
    """Powód, dla którego NVENC nie działa (None gdy działa).

    full=True zwraca pełny stderr FFmpeg z ostatniej nieudanej próby.
    """
    working_nvenc_args()
    if full:
        return _nvenc_error_full or _nvenc_error
    return _nvenc_error


def _video_encoder_args(name: str) -> list[str]:
    """Argumenty kodowania wideo dla wybranego enkodera."""
    if name == "h264_nvenc":
        args = working_nvenc_args()
        return list(args) if args else list(_NVENC_VARIANTS[0])
    return ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium"]


def _resolve_encoder(encoder: str) -> str:
    """Mapuje 'auto'/'gpu'/'cpu' na konkretny enkoder ffmpeg."""
    if encoder in ("h264_nvenc", "libx264"):
        return encoder
    if encoder == "cpu":
        return "libx264"
    # 'gpu' i 'auto' — tylko gdy NVENC realnie działa.
    return "h264_nvenc" if nvenc_works() else "libx264"


def render_video(video_path: str | Path, session: Session, t0: float,
                 style: OverlayStyle, mode: AnchorMode, out_path: str | Path,
                 progress_cb: ProgressCb | None = None,
                 trim_start: float | None = None,
                 trim_end: float | None = None,
                 encoder: str = "auto",
                 on_encoder: Callable[[str], None] | None = None,
                 on_warn: Callable[[str], None] | None = None) -> Path:
    """Renderuje wideo wynikowe z nakładką. Zwraca ścieżkę do pliku wyjściowego.

    trim_start / trim_end — opcjonalny fragment źródła (s) do wycięcia. Eksportowany
    jest tylko ten zakres; oś czasu wyjścia startuje od 0, więc okna nakładki są
    przesuwane o `trim_start`.

    encoder — 'auto' (NVENC jeśli dostępny, inaczej x264), 'gpu', 'cpu' lub nazwa
    enkodera. Przy NVENC stosujemy automatyczny fallback na x264, gdy kodowanie
    sprzętowe zawiedzie (np. brak działającego GPU mimo obecności enkodera).
    """
    video_path, out_path = str(video_path), Path(out_path)
    info = ffmpeg.probe(video_path)
    video_size = (info.width, info.height)

    src_start = max(trim_start, 0.0) if trim_start is not None else 0.0
    src_end = trim_end if trim_end is not None else info.duration
    if src_end <= src_start:
        raise ValueError("Koniec przycięcia musi być późniejszy niż początek.")
    out_duration = src_end - src_start

    # Zdarzenia liczone w czasie źródła; podsumowanie domykamy do końca fragmentu.
    events = build_events(session, t0, style, mode, video_size, src_end)
    if not events:
        raise ValueError("Brak zdarzeń do nałożenia (pusta oś czasu?).")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        seek = ["-ss", f"{src_start:.3f}"] if src_start > 0 else []
        inputs: list[str] = [*seek, "-i", video_path]
        filter_parts: list[str] = []
        cur = "0:v"

        used = 0
        for ev in events:
            # Przytnij okno zdarzenia do fragmentu i przesuń na oś wyjścia (start 0).
            ev_start = max(ev.start, src_start)
            ev_end = min(ev.end, src_end)
            if ev_end <= ev_start:
                continue  # zdarzenie poza wycinanym fragmentem
            out_start = ev_start - src_start
            out_end = ev_end - src_start

            png = tmp_dir / f"ev_{used:03d}.png"
            ev.image.save(png)
            inputs += ["-i", str(png)]
            x, y = _overlay_xy(ev, style, video_size)
            in_label = used + 1  # 0 to wideo
            out_label = f"v{used}"
            filter_parts.append(
                f"[{cur}][{in_label}:v]overlay={x}:{y}:"
                f"enable='between(t,{out_start:.3f},{out_end:.3f})'[{out_label}]"
            )
            cur = out_label
            used += 1

        if used == 0:
            raise ValueError("Wybrany fragment nie zawiera żadnego strzału.")

        filtergraph = ";".join(filter_parts)

        def build_cmd(enc: str) -> list[str]:
            hw = ["-hwaccel", "cuda"] if enc == "h264_nvenc" else []
            return [
                ffmpeg.ffmpeg_exe(), "-y", *hw, *inputs,
                "-t", f"{out_duration:.3f}",
                "-filter_complex", filtergraph,
                "-map", f"[{cur}]", "-map", "0:a?",
                *_video_encoder_args(enc),
                "-c:a", "aac", "-movflags", "+faststart",
                str(out_path),
            ]

        chosen = _resolve_encoder(encoder)
        try:
            _run_with_progress(build_cmd(chosen), out_duration, progress_cb)
            if on_encoder:
                on_encoder(chosen)
        except RuntimeError as exc:
            if chosen == "libx264":
                raise
            # Fallback: kodowanie sprzętowe zawiodło → spróbuj programowo (x264).
            if on_warn:
                on_warn(f"Enkoder {chosen} zawiódł, używam CPU (x264).\n\n"
                        f"Powód (z FFmpeg):\n{_short_err(exc)}")
            _run_with_progress(build_cmd("libx264"), out_duration, progress_cb)
            if on_encoder:
                on_encoder("libx264")

    return out_path


def trim_video(video_path: str | Path, out_path: str | Path,
               trim_start: float | None = None,
               trim_end: float | None = None,
               encoder: str = "auto",
               progress_cb: ProgressCb | None = None,
               on_encoder: Callable[[str], None] | None = None,
               on_warn: Callable[[str], None] | None = None) -> Path:
    """Przycina wideo bez nakładki. Zachowuje audio, re-enkoduje wideo.

    Parametry trim_start / trim_end i encoder działają tak samo jak w render_video.
    """
    video_path, out_path = str(video_path), Path(out_path)
    info = ffmpeg.probe(video_path)
    src_start = max(trim_start, 0.0) if trim_start is not None else 0.0
    src_end = trim_end if trim_end is not None else info.duration
    if src_end <= src_start:
        raise ValueError("Koniec przycięcia musi być późniejszy niż początek.")
    out_duration = src_end - src_start

    seek = ["-ss", f"{src_start:.3f}"] if src_start > 0 else []

    def build_cmd(enc: str) -> list[str]:
        hw = ["-hwaccel", "cuda"] if enc == "h264_nvenc" else []
        return [
            ffmpeg.ffmpeg_exe(), "-y", *hw, *seek, "-i", video_path,
            "-t", f"{out_duration:.3f}",
            "-map", "0:v", "-map", "0:a?",
            *_video_encoder_args(enc),
            "-c:a", "aac", "-movflags", "+faststart",
            str(out_path),
        ]

    chosen = _resolve_encoder(encoder)
    try:
        _run_with_progress(build_cmd(chosen), out_duration, progress_cb)
        if on_encoder:
            on_encoder(chosen)
    except RuntimeError as exc:
        if chosen == "libx264":
            raise
        if on_warn:
            on_warn(f"Enkoder {chosen} zawiódł, używam CPU (x264).\n\n"
                    f"Powód (z FFmpeg):\n{_short_err(exc)}")
        _run_with_progress(build_cmd("libx264"), out_duration, progress_cb)
        if on_encoder:
            on_encoder("libx264")

    return out_path


def _short_err(exc: Exception) -> str:
    """Skraca komunikat błędu FFmpeg do najistotniejszych linii (NVENC)."""
    text = str(exc)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    key = [ln for ln in lines if any(w in ln.lower() for w in
           ("nvenc", "cuda", "gpu", "driver", "error", "cannot", "failed", "no capable",
            "unrecognized", "unknown", "unsupported", "invalid", "session", "device"))]
    picked = key[-6:] if key else lines[-6:]
    return "\n".join(picked)


_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")


def _run_with_progress(cmd: list[str], duration: float, progress_cb: ProgressCb | None) -> None:
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            text=True, creationflags=ffmpeg.CREATE_NO_WINDOW)
    tail: list[str] = []
    assert proc.stderr is not None
    for line in proc.stderr:
        tail.append(line)
        if len(tail) > 50:
            tail.pop(0)
        if progress_cb and duration > 0:
            m = _TIME_RE.search(line)
            if m:
                h, mm, s = m.groups()
                t = int(h) * 3600 + int(mm) * 60 + float(s)
                progress_cb(min(t / duration, 1.0))
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("FFmpeg zakończył się błędem:\n" + "".join(tail))
    if progress_cb:
        progress_cb(1.0)
