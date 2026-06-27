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
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from . import ffmpeg, overlay
from .models import AnchorMode, OverlayStyle, Session

ProgressCb = Callable[[float], None]  # postęp 0.0–1.0
CancelCheck = Callable[[], bool]      # zwraca True gdy render ma zostać przerwany

_LAST_SHOT_HOLD = 2.0  # ile sekund trzymać panel ostatniego strzału przed podsumowaniem


class RenderCancelled(Exception):
    """Render przerwany na żądanie użytkownika (nie błąd FFmpeg)."""


@dataclass
class _Event:
    image: "overlay.Image.Image"
    start: float
    end: float
    centered: bool = False
    xy: tuple[int, int] | None = None  # wymusza pozycję (np. zegar nad panelem)


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
    if ev.xy is not None:
        return ev.xy
    if ev.centered:
        vw, vh = video_size
        pw, ph = ev.image.size
        return (vw - pw) // 2, (vh - ph) // 2
    return overlay.panel_origin(ev.image.size, video_size, style)


def _ff_color(rgba: tuple[int, int, int, int]) -> str:
    """Krotka RGBA (0–255) → kolor drawtext FFmpeg „0xRRGGBB@alpha"."""
    r, g, b, a = rgba
    return f"0x{r:02X}{g:02X}{b:02X}@{a / 255:.3f}"


def _max_panel_h(events: list[_Event]) -> int:
    """Najwyższy panel strzału/podsumowania — nad nim umieszczamy zegar."""
    hs = [ev.image.height for ev in events if not ev.centered and ev.xy is None]
    return max(hs) if hs else 0


def _clock_gap(video_size: tuple[int, int], style: OverlayStyle) -> int:
    return max(2, int(overlay._base_font_size(video_size[1], style) * 0.3))


def _clock_drawtext_seg(cur: str, style: OverlayStyle, video_size: tuple[int, int],
                        events: list[_Event], t0: float, src_start: float) -> tuple[str, str]:
    """Segment drawtext z płynącym zegarem od T0 (nad nakładką) + nowy label.

    Zegar tyka per-klatkę (wyrażenie czasu), więc daje gładkie dziesiąte sekundy.
    Wymaga filtra `drawtext` (libfreetype) — gdy go brak, używamy fallbacku PNG.
    """
    vh = video_size[1]
    base = overlay._base_font_size(vh, style)
    fontsize = max(12, int(base * 1.2))
    gap = _clock_gap(video_size, style)
    boxborderw = max(1, int(base * 0.25))
    max_panel_h = _max_panel_h(events)
    clock_out = t0 - src_start  # moment STARTU na osi wyjścia (po przycięciu)

    if style.clock_position != "auto":
        # Pozycja niezależna: róg + własny offset (jak panel, ale dla zegara).
        vert, _, horiz = style.clock_position.partition("-")
        ox, oy = style.clock_offset_x, style.clock_offset_y
        if horiz == "left":
            x_expr = f"{ox}"
        elif horiz == "right":
            x_expr = f"w-text_w-{ox}"
        else:
            x_expr = "(w-text_w)/2"
        y_expr = f"{oy}" if vert == "top" else f"max(0,h-text_h-{oy})"
    else:
        # "auto" — nad nakładką ze strzałami, zgodnie z rogiem kotwicy panelu.
        vert, _, horiz = style.position.partition("-")
        if horiz == "left":
            x_expr = f"{style.offset_x}"
        elif horiz == "right":
            x_expr = f"w-text_w-{style.offset_x}"
        else:
            x_expr = "(w-text_w)/2"
        if vert == "top":
            y_expr = f"max(0,{style.offset_y}-text_h-{gap})"
        else:  # bottom — zegar nad najwyższym panelem strzału
            y_expr = f"max(0,h-{style.offset_y}-{max_panel_h}-text_h-{gap})"

    font = str(overlay.font_path(bold=True)).replace("\\", "/")
    c = f"{clock_out:.3f}"
    # T+SS.s — część całkowita i dziesiąte sekundy (eif obsługuje tylko int).
    # Dwukropki wewnątrz %{...} trzeba eskejpować (\:) — inaczej parser drawtext
    # potraktuje je jak separator opcji filtra.
    text = (f"T+%{{eif\\:trunc(t-{c})\\:d}}."
            f"%{{eif\\:trunc(mod((t-{c})*10,10))\\:d}}s")
    seg = (
        f"[{cur}]drawtext=fontfile='{font}':text='{text}':"
        f"x='{x_expr}':y='{y_expr}':fontsize={fontsize}:"
        f"fontcolor={_ff_color(style.accent_color)}:"
        f"box=1:boxcolor={_ff_color(style.bg_color)}:boxborderw={boxborderw}:"
        f"enable='gte(t,{c})'[vclock]"
    )
    return seg, "vclock"


_CLOCK_SEQ_FPS = 10.0          # klatek/s sekwencji PNG zegara → dziesiąte sekundy
_CLOCK_SEQ_MAX_FRAMES = 1800   # górny limit klatek (bardzo długie okno → niższy fps)


def _clock_xy(style: OverlayStyle, video_size: tuple[int, int],
              clock_size: tuple[int, int], max_panel_h: int, gap: int) -> tuple[int, int]:
    """Pozycja panelu zegara (px). „auto" = nad panelem strzału wg rogu kotwicy;
    inaczej niezależny róg + własny offset zegara."""
    if style.clock_position != "auto":
        cs = replace(style, position=style.clock_position,
                     offset_x=style.clock_offset_x, offset_y=style.clock_offset_y)
        return overlay.panel_origin(clock_size, video_size, cs)
    x, y = overlay.panel_origin(clock_size, video_size, style)
    if style.position.partition("-")[0] == "top":
        y = y - clock_size[1] - gap
    else:
        y = y - max_panel_h - gap
    return x, max(0, y)


@dataclass
class _ClockSeq:
    """Sekwencja PNG zegara do nałożenia JEDNYM wejściem image2 (fallback bez drawtext)."""
    pattern: str                 # wzorzec image2, np. .../clk_%05d.png
    fps: float                   # klatek/s sekwencji
    xy: tuple[int, int]          # pozycja nałożenia (stała — patrz płótno)
    nframes: int


def _clock_align(style: OverlayStyle) -> str:
    """Poziome wyrównanie zegara (left/center/right) wg rogu kotwicy."""
    pos = style.position if style.clock_position == "auto" else style.clock_position
    return pos.partition("-")[2]


def _write_clock_sequence(tmp_dir: Path, style: OverlayStyle,
                          video_size: tuple[int, int], events: list[_Event],
                          t0: float, src_start: float,
                          src_end: float) -> _ClockSeq | None:
    """Zapisuje sekwencję PNG zegara (10 fps) na całe okno wyjścia.

    Daje płynne DZIESIĄTE sekundy na KAŻDEJ binarce FFmpeg (image2 jest zawsze),
    bez rozdmuchania linii poleceń: jedno wejście `-i clk_%05d.png` + jeden
    `overlay`, zamiast setek wejść PNG. Klatki przed STARTEM (t < T0) są
    przezroczyste; wszystkie panele wklejane na płótno o stałym rozmiarze
    (najszerszy panel), wyrównane wg rogu kotwicy, aby przy zmianie liczby cyfr
    (9.9 → 10.0) anchorowana krawędź nie drgała. None gdy zegar nie wejdzie w okno.
    """
    out_duration = src_end - src_start
    if src_end <= max(t0, src_start) or out_duration <= 0:
        return None
    fps = _CLOCK_SEQ_FPS
    nframes = int(round(out_duration * fps)) + 1
    if nframes > _CLOCK_SEQ_MAX_FRAMES:
        fps = _CLOCK_SEQ_MAX_FRAMES / out_duration
        nframes = _CLOCK_SEQ_MAX_FRAMES
    # Płótno = najszerszy panel (maksymalny elapsed = koniec okna).
    sample = overlay.render_clock_panel(style, video_size, max(0.0, src_end - t0))
    canvas_w, canvas_h = sample.size
    gap = _clock_gap(video_size, style)
    xy = _clock_xy(style, video_size, (canvas_w, canvas_h), _max_panel_h(events), gap)
    align = _clock_align(style)

    clk_dir = tmp_dir / "clock"
    clk_dir.mkdir(exist_ok=True)
    blank = overlay.Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    for i in range(nframes):
        path = clk_dir / f"clk_{i:05d}.png"
        elapsed = (src_start + i / fps) - t0
        if elapsed < 0:
            blank.save(path)
            continue
        panel = overlay.render_clock_panel(style, video_size, elapsed)
        canvas = blank.copy()
        if align == "left":
            px = 0
        elif align == "right":
            px = canvas_w - panel.size[0]
        else:
            px = (canvas_w - panel.size[0]) // 2
        canvas.alpha_composite(panel, (max(0, px), 0))
        canvas.save(path)
    return _ClockSeq(str(clk_dir / "clk_%05d.png"), fps, xy, nframes)


@functools.lru_cache(maxsize=1)
def _drawtext_usable() -> bool:
    """Czy drawtext realnie koduje klatkę z naszym wyrażeniem zegara.

    Sama obecność filtra nie wystarcza — różne buildy/eskejpowanie bywają
    kapryśne. Testujemy 1 klatkę z reprezentatywnym `drawtext`; gdy zawiedzie,
    używamy pewnego fallbacku PNG. Wynik jest cache'owany.
    """
    if not ffmpeg.has_filter("drawtext"):
        return False
    font = str(overlay.font_path(bold=True)).replace("\\", "/")
    text = r"T+%{eif\:trunc(t-0.000)\:d}.%{eif\:trunc(mod((t-0.000)*10,10))\:d}s"
    seg = (f"drawtext=fontfile='{font}':text='{text}':x='10':y='10':"
           f"fontsize=20:fontcolor=0xFFFFFF@1.000:box=1:boxcolor=0x000000@0.500:"
           f"boxborderw=3:enable='gte(t,0.000)'")
    cmd = [ffmpeg.ffmpeg_exe(), "-hide_banner", "-f", "lavfi",
           "-i", "testsrc=duration=0.2:size=128x128:rate=5",
           "-vf", seg, "-frames:v", "1", "-f", "null", "-"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True,
                             creationflags=ffmpeg.CREATE_NO_WINDOW)
        return res.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def prepare_clock(style: OverlayStyle) -> bool:
    """Czy zegar renderować przez `drawtext` (True) — gdy filtr realnie działa.

    False → fallback sekwencji PNG (10 fps, `_write_clock_sequence`), też z
    dziesiątymi sekundy. Zwraca False również gdy zegar wyłączony (brak nakładki).
    """
    return bool(style.show_running_clock) and _drawtext_usable()


def _append_clock(style: OverlayStyle, video_size: tuple[int, int],
                  events: list[_Event], t0: float, src_start: float, src_end: float,
                  tmp_dir: Path, inputs: list[str], filter_parts: list[str],
                  cur: str, next_idx: int, use_drawtext: bool) -> str:
    """Dopina zegar do filtergraphu (drawtext albo sekwencja PNG).

    Mutuje `inputs`/`filter_parts`; zwraca nową etykietę strumienia wideo (`cur`).
    `next_idx` to indeks kolejnego wejścia FFmpeg (0=wideo, 1..N=panele zdarzeń)."""
    if not style.show_running_clock:
        return cur
    if use_drawtext:
        seg, cur = _clock_drawtext_seg(cur, style, video_size, events, t0, src_start)
        filter_parts.append(seg)
        return cur
    seq = _write_clock_sequence(tmp_dir, style, video_size, events, t0, src_start, src_end)
    if seq is None:
        return cur
    inputs += ["-framerate", f"{seq.fps:g}", "-f", "image2", "-i", seq.pattern]
    filter_parts.append(
        f"[{cur}][{next_idx}:v]overlay={seq.xy[0]}:{seq.xy[1]}:eof_action=pass[vclk]")
    return "vclk"


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
                 on_warn: Callable[[str], None] | None = None,
                 cancel_check: CancelCheck | None = None) -> Path:
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
    use_drawtext = prepare_clock(style)

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

        cur = _append_clock(style, video_size, events, t0, src_start, src_end,
                             tmp_dir, inputs, filter_parts, cur, used + 1, use_drawtext)
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
            _run_with_progress(build_cmd(chosen), out_duration, progress_cb, cancel_check)
            if on_encoder:
                on_encoder(chosen)
        except RuntimeError as exc:
            if chosen == "libx264":
                raise
            # Fallback: kodowanie sprzętowe zawiodło → spróbuj programowo (x264).
            if on_warn:
                on_warn(f"Enkoder {chosen} zawiódł, używam CPU (x264).\n\n"
                        f"Powód (z FFmpeg):\n{_short_err(exc)}")
            _run_with_progress(build_cmd("libx264"), out_duration, progress_cb, cancel_check)
            if on_encoder:
                on_encoder("libx264")

    return out_path


def render_webm(video_path: str | Path, session: Session, t0: float,
                style: OverlayStyle, mode: AnchorMode, out_path: str | Path,
                progress_cb: ProgressCb | None = None,
                trim_start: float | None = None,
                trim_end: float | None = None,
                cancel_check: CancelCheck | None = None) -> Path:
    """Renderuje WebM (VP9 + Opus) z wypalona nakładką.

    Nie wspiera NVENC — VP9 jest zawsze programowy (libvpx-vp9). Dobry do
    krótkich klipów na potrzeby Instagrama/Discord (mniejszy niż GIF, dobra jakość).
    """
    video_path, out_path = str(video_path), Path(out_path)
    info = ffmpeg.probe(video_path)
    video_size = (info.width, info.height)

    src_start = max(trim_start, 0.0) if trim_start is not None else 0.0
    src_end = trim_end if trim_end is not None else info.duration
    if src_end <= src_start:
        raise ValueError("Koniec przycięcia musi być późniejszy niż początek.")
    out_duration = src_end - src_start

    events = build_events(session, t0, style, mode, video_size, src_end)
    if not events:
        raise ValueError("Brak zdarzeń do nałożenia (pusta oś czasu?).")
    use_drawtext = prepare_clock(style)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        seek = ["-ss", f"{src_start:.3f}"] if src_start > 0 else []
        inputs: list[str] = [*seek, "-i", video_path]
        filter_parts: list[str] = []
        cur = "0:v"

        used = 0
        for ev in events:
            ev_start = max(ev.start, src_start)
            ev_end = min(ev.end, src_end)
            if ev_end <= ev_start:
                continue
            out_start = ev_start - src_start
            out_end = ev_end - src_start

            png = tmp_dir / f"ev_{used:03d}.png"
            ev.image.save(png)
            inputs += ["-i", str(png)]
            x, y = _overlay_xy(ev, style, video_size)
            in_label = used + 1
            out_label = f"v{used}"
            filter_parts.append(
                f"[{cur}][{in_label}:v]overlay={x}:{y}:"
                f"enable='between(t,{out_start:.3f},{out_end:.3f})'[{out_label}]"
            )
            cur = out_label
            used += 1

        if used == 0:
            raise ValueError("Wybrany fragment nie zawiera żadnego strzału.")

        cur = _append_clock(style, video_size, events, t0, src_start, src_end,
                             tmp_dir, inputs, filter_parts, cur, used + 1, use_drawtext)

        cmd = [
            ffmpeg.ffmpeg_exe(), "-y", *inputs,
            "-t", f"{out_duration:.3f}",
            "-filter_complex", ";".join(filter_parts),
            "-map", f"[{cur}]", "-map", "0:a?",
            "-c:v", "libvpx-vp9", "-crf", "30", "-b:v", "0", "-pix_fmt", "yuv420p",
            "-c:a", "libopus", "-b:a", "96k",
            str(out_path),
        ]
        _run_with_progress(cmd, out_duration, progress_cb, cancel_check)

    return out_path


def render_gif(video_path: str | Path, session: Session, t0: float,
               style: OverlayStyle, mode: AnchorMode, out_path: str | Path,
               progress_cb: ProgressCb | None = None,
               trim_start: float | None = None,
               trim_end: float | None = None,
               fps: int = 12,
               max_width: int = 640,
               cancel_check: CancelCheck | None = None) -> Path:
    """Renderuje animowany GIF z wypalona nakładką (2-pass: palettegen + paletteuse).

    fps — liczba klatek na sekundę GIF (domyślnie 12; przy 24+ plik rośnie drastycznie).
    max_width — maksymalna szerokość; wysokość skalowana proporcjonalnie.
    Nie wspiera audio — GIF jest niemą animacją.
    """
    video_path, out_path = str(video_path), Path(out_path)
    info = ffmpeg.probe(video_path)
    video_size = (info.width, info.height)

    src_start = max(trim_start, 0.0) if trim_start is not None else 0.0
    src_end = trim_end if trim_end is not None else info.duration
    if src_end <= src_start:
        raise ValueError("Koniec przycięcia musi być późniejszy niż początek.")
    out_duration = src_end - src_start

    events = build_events(session, t0, style, mode, video_size, src_end)
    if not events:
        raise ValueError("Brak zdarzeń do nałożenia (pusta oś czasu?).")
    use_drawtext = prepare_clock(style)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        palette = tmp_dir / "palette.png"
        seek = ["-ss", f"{src_start:.3f}"] if src_start > 0 else []
        inputs: list[str] = [*seek, "-i", video_path]
        filter_parts: list[str] = []
        cur = "0:v"

        used = 0
        for ev in events:
            ev_start = max(ev.start, src_start)
            ev_end = min(ev.end, src_end)
            if ev_end <= ev_start:
                continue
            out_start = ev_start - src_start
            out_end = ev_end - src_start

            png = tmp_dir / f"ev_{used:03d}.png"
            ev.image.save(png)
            inputs += ["-i", str(png)]
            x, y = _overlay_xy(ev, style, video_size)
            in_label = used + 1
            out_label = f"v{used}"
            filter_parts.append(
                f"[{cur}][{in_label}:v]overlay={x}:{y}:"
                f"enable='between(t,{out_start:.3f},{out_end:.3f})'[{out_label}]"
            )
            cur = out_label
            used += 1

        if used == 0:
            raise ValueError("Wybrany fragment nie zawiera żadnego strzału.")

        cur = _append_clock(style, video_size, events, t0, src_start, src_end,
                             tmp_dir, inputs, filter_parts, cur, used + 1, use_drawtext)

        scale_flt = f"fps={fps},scale={max_width}:-1:flags=lanczos"
        base_fg = ";".join(filter_parts)

        # Pass 1: wygeneruj paletę kolorów (wymagana dla animowanego GIF).
        fg1 = base_fg + f";[{cur}]{scale_flt},palettegen[pal]"
        cmd1 = [
            ffmpeg.ffmpeg_exe(), "-y", *inputs,
            "-t", f"{out_duration:.3f}",
            "-filter_complex", fg1,
            "-map", "[pal]",
            str(palette),
        ]
        if cancel_check and cancel_check():
            raise RenderCancelled()
        res = subprocess.run(cmd1, capture_output=True, text=True,
                             creationflags=ffmpeg.CREATE_NO_WINDOW)
        if res.returncode != 0:
            raise RuntimeError("Błąd generowania palety GIF:\n" + res.stderr[-2000:])

        # Pass 2: zakoduj GIF używając wygenerowanej palety.
        # Paleta jest kolejnym wejściem — indeks = liczba dotychczasowych wejść
        # (wideo + panele + ew. sekwencja zegara), liczona po wystąpieniach „-i".
        pal_idx = inputs.count("-i")
        inputs2 = inputs + ["-i", str(palette)]
        fg2 = base_fg + f";[{cur}]{scale_flt}[sc];[sc][{pal_idx}:v]paletteuse[out]"
        cmd2 = [
            ffmpeg.ffmpeg_exe(), "-y", *inputs2,
            "-t", f"{out_duration:.3f}",
            "-filter_complex", fg2,
            "-map", "[out]",
            "-loop", "0",
            str(out_path),
        ]
        _run_with_progress(cmd2, out_duration, progress_cb, cancel_check)

    return out_path


def trim_video(video_path: str | Path, out_path: str | Path,
               trim_start: float | None = None,
               trim_end: float | None = None,
               encoder: str = "auto",
               progress_cb: ProgressCb | None = None,
               on_encoder: Callable[[str], None] | None = None,
               on_warn: Callable[[str], None] | None = None,
               cancel_check: CancelCheck | None = None) -> Path:
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
        _run_with_progress(build_cmd(chosen), out_duration, progress_cb, cancel_check)
        if on_encoder:
            on_encoder(chosen)
    except RuntimeError as exc:
        if chosen == "libx264":
            raise
        if on_warn:
            on_warn(f"Enkoder {chosen} zawiódł, używam CPU (x264).\n\n"
                    f"Powód (z FFmpeg):\n{_short_err(exc)}")
        _run_with_progress(build_cmd("libx264"), out_duration, progress_cb, cancel_check)
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


def _run_with_progress(cmd: list[str], duration: float, progress_cb: ProgressCb | None,
                       cancel_check: CancelCheck | None = None) -> None:
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            text=True, creationflags=ffmpeg.CREATE_NO_WINDOW)
    tail: list[str] = []
    assert proc.stderr is not None
    for line in proc.stderr:
        if cancel_check and cancel_check():
            proc.kill()
            proc.wait()
            raise RenderCancelled()
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
    if cancel_check and cancel_check():
        raise RenderCancelled()
    if proc.returncode != 0:
        raise RuntimeError("FFmpeg zakończył się błędem:\n" + "".join(tail))
    if progress_cb:
        progress_cb(1.0)
