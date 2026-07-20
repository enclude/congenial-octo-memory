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

from . import config, ffmpeg, overlay
from .models import AnchorMode, OverlayStyle, Session

ProgressCb = Callable[[float], None]  # postęp 0.0–1.0
CancelCheck = Callable[[], bool]      # zwraca True gdy render ma zostać przerwany
ProcessCb = Callable[[object], None]  # przekazuje uchwyt Popen (lub None) — do ubicia


def _log_render(msg: str) -> None:
    """Dopisuje wiersz do dziennika renderów w AppData (diagnostyka zawieszeń/crashy).

    Cichy i odporny na błędy — diagnostyka nie może wywrócić renderu. Plik bywa
    jedynym śladem, gdy FFmpeg zawiesza się albo aplikacja pada twardo."""
    try:
        path = config.config_dir() / "render_log.txt"
        # przytnij, jeśli urósł (prosty bezpiecznik, bez rotacji)
        if path.exists() and path.stat().st_size > 512 * 1024:
            path.write_text("", encoding="utf-8")
        with open(path, "a", encoding="utf-8") as f:
            f.write(msg.rstrip() + "\n")
    except Exception:  # noqa: BLE001
        pass

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


def build_events(session: Session, t0: float, style: OverlayStyle,
                 video_size: tuple[int, int], duration: float) -> list[_Event]:
    """Tworzy listę zdarzeń nakładki.

    Plansza START / panele strzałów / podsumowanie mają rozłączne okna czasowe;
    nakładka metadanych (jeśli włączona) gra RÓWNOLEGLE z nimi na własnej pozycji."""
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

    # Panele strzałów — wszystkie o STAŁYM rozmiarze (max po wszystkich strzałach),
    # by tło/obramowanie nie zmieniało szerokości między „Strzał 6 z 18" a „18 z 18".
    shot_fixed = overlay.shot_panel_max_size(session, style, video_size)
    n = len(shots)
    for i in range(n):
        start = t0 + shots[i].czas
        if i < n - 1:
            end = t0 + shots[i + 1].czas
        else:
            end = min(start + _LAST_SHOT_HOLD, duration)
        events.append(_Event(
            overlay.render_shot_panel(session, i, style, video_size, shot_fixed),
            start=start, end=end,
        ))

    # Panel podsumowania — od końca ostatniego panelu strzału do końca filmu.
    summary_start = events[-1].end
    if duration > summary_start:
        events.append(_Event(
            overlay.render_summary_panel(session, style, video_size),
            start=summary_start, end=duration,
        ))

    # Nakładka metadanych (tor/uczestnik) — od T0 do końca, własna pozycja (xy),
    # równolegle z panelami strzałów (okna zdarzeń NIE są już wtedy rozłączne —
    # to osobny overlay w łańcuchu, więc filtergraph pozostaje poprawny).
    if style.show_meta_panel:
        meta = overlay.render_meta_panel(session, style, video_size)
        meta_start = max(t0, 0.0)
        if meta is not None and duration > meta_start:
            events.append(_Event(
                meta, start=meta_start, end=duration,
                xy=overlay.panel_origin_at(meta.size, video_size, style.meta_position,
                                           style.meta_offset_x, style.meta_offset_y),
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
                        events: list[_Event], t0: float, src_start: float,
                        last_shot_time: float | None = None) -> tuple[str, str]:
    """Segment drawtext z płynącym zegarem od T0 (nad nakładką) + nowy label.

    Zegar tyka per-klatkę (wyrażenie czasu), więc daje gładkie dziesiąte sekundy.
    Wymaga filtra `drawtext` (libfreetype) — gdy go brak, używamy fallbacku PNG.
    Gdy znamy czas ostatniego strzału, zegar ZAMARZA na nim (nie płynie dalej).
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
    # Elapsed = czas od STARTU; zamrażamy na ostatnim strzale przez min(...).
    if last_shot_time is not None and last_shot_time >= 0:
        e = f"min(t-{c},{last_shot_time:.3f})"
    else:
        e = f"(t-{c})"
    # T+SS.s — część całkowita i dziesiąte sekundy (eif obsługuje tylko int).
    # Dwukropki wewnątrz %{...} trzeba eskejpować (\:) — inaczej parser drawtext
    # potraktuje je jak separator opcji filtra (przecinek w %{...} jest bezpieczny).
    text = (f"T+%{{eif\\:trunc({e})\\:d}}."
            f"%{{eif\\:trunc(mod({e}*10,10))\\:d}}s")
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


def _write_clock_sequence(tmp_dir: Path, style: OverlayStyle,
                          video_size: tuple[int, int], events: list[_Event],
                          t0: float, src_start: float, src_end: float,
                          video_fps: float = _CLOCK_SEQ_FPS,
                          last_shot_time: float | None = None) -> _ClockSeq | None:
    """Zapisuje sekwencję PNG zegara na okno animacji (do ostatniego strzału).

    Daje płynne DZIESIĄTE sekundy na KAŻDEJ binarce FFmpeg (image2 jest zawsze),
    bez rozdmuchania linii poleceń: jedno wejście `-i clk_%05d.png` + jeden
    `overlay`, zamiast setek wejść PNG. Klatki przed STARTEM (t < T0) są
    przezroczyste; wszystkie panele wklejane na płótno o stałym rozmiarze
    (najszerszy panel), wyrównane wg rogu kotwicy, aby przy zmianie liczby cyfr
    (9.9 → 10.0) anchorowana krawędź nie drgała.

    PŁYNNOŚĆ: fps sekwencji = fps wideo (lub jego całkowity dzielnik), więc na
    KAŻDĄ klatkę wyjścia przypada jedna klatka zegara → kadencja jest równa i nie
    „zacina się" (10 fps na wideo 29.97/59.94 dawało dudnienie). Treść i tak
    zaokrąglamy do dziesiątych, więc cyfra zmienia się co 0.1 s.

    ZAMROŻENIE: zegar tyka tylko do `last_shot_time` (czas ostatniego strzału),
    potem ostatnia klatka jest powtarzana do końca (overlay `eof_action=repeat`).
    None gdy zegar nie wejdzie w okno.
    """
    out_duration = src_end - src_start
    if src_end <= max(t0, src_start) or out_duration <= 0:
        return None
    # Zegar płynie do ostatniego strzału, potem zamarza (klatka powtarzana do końca).
    freeze_elapsed = last_shot_time if (last_shot_time is not None and last_shot_time >= 0) \
        else (src_end - t0)
    clock_end_out = min(out_duration, (t0 + freeze_elapsed) - src_start)
    if clock_end_out <= 0:
        return None
    # fps = fps wideo (1:1 → równa kadencja); gdy klatek za dużo, redukujemy
    # CAŁKOWITYM dzielnikiem, by sekwencja nadal dzieliła fps wideo bez dudnienia.
    base_fps = video_fps if video_fps and video_fps > 0 else _CLOCK_SEQ_FPS
    fps = base_fps
    nframes = int(round(clock_end_out * fps)) + 1
    k = 1
    while nframes > _CLOCK_SEQ_MAX_FRAMES:
        k += 1
        fps = base_fps / k
        nframes = int(round(clock_end_out * fps)) + 1
    # Stały rozmiar panelu = max (przy największym elapsed = ostatni strzał).
    # Każda klatka ma identyczny rozmiar tła/obramowania → krawędzie (w tym dolna)
    # nie skaczą przy zmianie liczby cyfr, a pozycja nałożenia jest stała.
    canvas_w, canvas_h = overlay.clock_panel_max_size(style, video_size, max(0.0, freeze_elapsed))
    gap = _clock_gap(video_size, style)
    xy = _clock_xy(style, video_size, (canvas_w, canvas_h), _max_panel_h(events), gap)

    clk_dir = tmp_dir / "clock"
    clk_dir.mkdir(parents=True, exist_ok=True)
    blank = overlay.Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    for i in range(nframes):
        path = clk_dir / f"clk_{i:05d}.png"
        elapsed = (src_start + i / fps) - t0
        if elapsed < 0:
            blank.save(path)
            continue
        elapsed = min(elapsed, freeze_elapsed)   # zamrożenie na ostatnim strzale
        # fixed_size = rozmiar płótna → panel zawsze tej samej wielkości, klejony w (0,0).
        panel = overlay.render_clock_panel(style, video_size, elapsed, (canvas_w, canvas_h))
        canvas = blank.copy()
        canvas.alpha_composite(panel, (0, 0))
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
                  cur: str, next_idx: int, use_drawtext: bool,
                  video_fps: float = _CLOCK_SEQ_FPS,
                  last_shot_time: float | None = None) -> str:
    """Dopina zegar do filtergraphu (drawtext albo sekwencja PNG).

    Mutuje `inputs`/`filter_parts`; zwraca nową etykietę strumienia wideo (`cur`).
    `next_idx` to indeks kolejnego wejścia FFmpeg (0=wideo, 1..N=panele zdarzeń).
    `last_shot_time` — zegar zamarza na nim; `video_fps` — kadencja sekwencji PNG."""
    if not style.show_running_clock:
        return cur
    if use_drawtext:
        seg, cur = _clock_drawtext_seg(cur, style, video_size, events, t0, src_start,
                                       last_shot_time)
        filter_parts.append(seg)
        return cur
    seq = _write_clock_sequence(tmp_dir, style, video_size, events, t0, src_start, src_end,
                                video_fps, last_shot_time)
    if seq is None:
        return cur
    inputs += ["-framerate", f"{seq.fps:g}", "-f", "image2", "-i", seq.pattern]
    # eof_action=repeat → po ostatniej (zamrożonej) klatce zegar zostaje widoczny do końca.
    filter_parts.append(
        f"[{cur}][{next_idx}:v]overlay={seq.xy[0]}:{seq.xy[1]}:eof_action=repeat[vclk]")
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
                 cancel_check: CancelCheck | None = None,
                 on_process: ProcessCb | None = None) -> Path:
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
    events = build_events(session, t0, style, video_size, src_end)
    if not events:
        raise ValueError("Brak zdarzeń do nałożenia (pusta oś czasu?).")
    use_drawtext = prepare_clock(style)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        seek = ["-ss", f"{src_start:.3f}"] if src_start > 0 else []
        inputs: list[str] = [*ffmpeg.UNTRUSTED_INPUT_ARGS, *seek, "-i", video_path]
        filter_parts: list[str] = []
        cur = "0:v:0"   # TYLKO pierwszy strumień wideo (DJI ma drugi: miniatura MJPEG)

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
                             tmp_dir, inputs, filter_parts, cur, used + 1, use_drawtext,
                             info.fps,
                             session.shots[-1].czas if session.shots else None)
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
            _run_with_progress(build_cmd(chosen), out_duration, progress_cb,
                               cancel_check, on_process)
            if on_encoder:
                on_encoder(chosen)
        except RuntimeError as exc:
            if chosen == "libx264":
                raise
            # Fallback: kodowanie sprzętowe zawiodło → spróbuj programowo (x264).
            if on_warn:
                on_warn(f"Enkoder {chosen} zawiódł, używam CPU (x264).\n\n"
                        f"Powód (z FFmpeg):\n{_short_err(exc)}")
            _run_with_progress(build_cmd("libx264"), out_duration, progress_cb,
                               cancel_check, on_process)
            if on_encoder:
                on_encoder("libx264")

    return out_path


def render_webm(video_path: str | Path, session: Session, t0: float,
                style: OverlayStyle, mode: AnchorMode, out_path: str | Path,
                progress_cb: ProgressCb | None = None,
                trim_start: float | None = None,
                trim_end: float | None = None,
                cancel_check: CancelCheck | None = None,
                on_process: ProcessCb | None = None) -> Path:
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

    events = build_events(session, t0, style, video_size, src_end)
    if not events:
        raise ValueError("Brak zdarzeń do nałożenia (pusta oś czasu?).")
    use_drawtext = prepare_clock(style)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        seek = ["-ss", f"{src_start:.3f}"] if src_start > 0 else []
        inputs: list[str] = [*ffmpeg.UNTRUSTED_INPUT_ARGS, *seek, "-i", video_path]
        filter_parts: list[str] = []
        cur = "0:v:0"   # TYLKO pierwszy strumień wideo (DJI ma drugi: miniatura MJPEG)

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
                             tmp_dir, inputs, filter_parts, cur, used + 1, use_drawtext,
                             info.fps,
                             session.shots[-1].czas if session.shots else None)

        cmd = [
            ffmpeg.ffmpeg_exe(), "-y", *inputs,
            "-t", f"{out_duration:.3f}",
            "-filter_complex", ";".join(filter_parts),
            "-map", f"[{cur}]", "-map", "0:a?",
            "-c:v", "libvpx-vp9", "-crf", "30", "-b:v", "0", "-pix_fmt", "yuv420p",
            "-c:a", "libopus", "-b:a", "96k",
            str(out_path),
        ]
        _run_with_progress(cmd, out_duration, progress_cb, cancel_check, on_process)

    return out_path


def render_gif(video_path: str | Path, session: Session, t0: float,
               style: OverlayStyle, mode: AnchorMode, out_path: str | Path,
               progress_cb: ProgressCb | None = None,
               trim_start: float | None = None,
               trim_end: float | None = None,
               fps: int = 12,
               max_width: int = 640,
               cancel_check: CancelCheck | None = None,
               on_process: ProcessCb | None = None) -> Path:
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

    events = build_events(session, t0, style, video_size, src_end)
    if not events:
        raise ValueError("Brak zdarzeń do nałożenia (pusta oś czasu?).")
    use_drawtext = prepare_clock(style)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        palette = tmp_dir / "palette.png"
        seek = ["-ss", f"{src_start:.3f}"] if src_start > 0 else []
        inputs: list[str] = [*ffmpeg.UNTRUSTED_INPUT_ARGS, *seek, "-i", video_path]
        filter_parts: list[str] = []
        cur = "0:v:0"   # TYLKO pierwszy strumień wideo (DJI ma drugi: miniatura MJPEG)

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
                             tmp_dir, inputs, filter_parts, cur, used + 1, use_drawtext,
                             info.fps,
                             session.shots[-1].czas if session.shots else None)

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
        _run_with_progress(cmd2, out_duration, progress_cb, cancel_check, on_process)

    return out_path


def trim_video(video_path: str | Path, out_path: str | Path,
               trim_start: float | None = None,
               trim_end: float | None = None,
               encoder: str = "auto",
               progress_cb: ProgressCb | None = None,
               on_encoder: Callable[[str], None] | None = None,
               on_warn: Callable[[str], None] | None = None,
               cancel_check: CancelCheck | None = None,
               on_process: ProcessCb | None = None) -> Path:
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
            ffmpeg.ffmpeg_exe(), "-y", *hw, *ffmpeg.UNTRUSTED_INPUT_ARGS, *seek, "-i", video_path,
            "-t", f"{out_duration:.3f}",
            "-map", "0:v:0", "-map", "0:a?",   # tylko 1. wideo (pomiń miniaturę MJPEG DJI)
            *_video_encoder_args(enc),
            "-c:a", "aac", "-movflags", "+faststart",
            str(out_path),
        ]

    chosen = _resolve_encoder(encoder)
    try:
        _run_with_progress(build_cmd(chosen), out_duration, progress_cb,
                           cancel_check, on_process)
        if on_encoder:
            on_encoder(chosen)
    except RuntimeError as exc:
        if chosen == "libx264":
            raise
        if on_warn:
            on_warn(f"Enkoder {chosen} zawiódł, używam CPU (x264).\n\n"
                    f"Powód (z FFmpeg):\n{_short_err(exc)}")
        _run_with_progress(build_cmd("libx264"), out_duration, progress_cb,
                           cancel_check, on_process)
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
# Z `-progress`: `out_time_ms=` (mikrosekundy mimo nazwy) — pewniejsze niż „time=".
_OUT_TIME_MS_RE = re.compile(r"out_time_(?:ms|us)=(\d+)")
# Wiersze bloków `-progress pipe:2` (co ~0.5 s po ~12 linii). NIE trafiają do ogona
# błędu — zalewały go tak, że komunikat „Błąd renderu" pokazywał sam postęp,
# a faktyczny błąd FFmpeg (albo jego BRAK — proces ubity z zewnątrz) ginął.
_PROGRESS_LINE_RE = re.compile(
    r"^(?:frame|fps|stream_\d+_\d+_q|bitrate|total_size|out_time(?:_us|_ms)?"
    r"|dup_frames|drop_frames|speed|progress)=")


def _run_with_progress(cmd: list[str], duration: float, progress_cb: ProgressCb | None,
                       cancel_check: CancelCheck | None = None,
                       on_process: ProcessCb | None = None) -> None:
    # `-progress pipe:2 -nostats` → FFmpeg wypisuje postęp REGULARNIE (co ~0.5 s),
    # niezależnie od tego jak wolno liczą się klatki. Bez tego ciężki filtergraph
    # potrafił nie wypisać NIC przez dziesiątki sekund → brak postępu i „Zatrzymaj"
    # nie miało kiedy zadziałać (pętla czytająca stderr blokowała się).
    cmd = [cmd[0], "-progress", "pipe:2", "-nostats", *cmd[1:]]
    _log_render(f"START ({duration:.1f}s): {' '.join(cmd)}")
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            text=True, creationflags=ffmpeg.CREATE_NO_WINDOW)
    if on_process:
        on_process(proc)   # pozwól workerowi ubić proces przy „Zatrzymaj"
    tail: list[str] = []
    last_out_time = ""   # ostatnia pozycja `out_time=` — kontekst przy błędzie
    assert proc.stderr is not None
    try:
        for line in proc.stderr:
            if cancel_check and cancel_check():
                proc.kill()
                proc.wait()
                _log_render("CANCELLED")
                raise RenderCancelled()
            if _PROGRESS_LINE_RE.match(line):
                if line.startswith("out_time="):
                    last_out_time = line.strip()
                if progress_cb and duration > 0:
                    # `-progress` daje wiersze `out_time_ms=` / `out_time=`; łapiemy oba.
                    mms = _OUT_TIME_MS_RE.search(line)
                    if mms:
                        progress_cb(min(int(mms.group(1)) / 1e6 / duration, 1.0))
                continue
            tail.append(line)
            if len(tail) > 80:
                tail.pop(0)
            if progress_cb and duration > 0:
                m = _TIME_RE.search(line)
                if m:
                    h, mm, s = m.groups()
                    t = int(h) * 3600 + int(mm) * 60 + float(s)
                    progress_cb(min(t / duration, 1.0))
    finally:
        if on_process:
            on_process(None)
    proc.wait()
    if cancel_check and cancel_check():
        _log_render("CANCELLED")
        raise RenderCancelled()
    if proc.returncode != 0:
        detail = "".join(tail).strip()
        if not detail:
            # stderr urwał się w pół postępu — FFmpeg nie zdążył nic wypisać,
            # czyli został ubity z zewnątrz (typowo: system przy braku pamięci).
            detail = ("FFmpeg nie wypisał komunikatu błędu — proces został "
                      "przerwany z zewnątrz (np. zabity przez system przy "
                      "braku pamięci / limit RAM kontenera).")
        if proc.returncode < 0:
            detail += (f"\n(Proces ubity sygnałem {-proc.returncode} — kod ujemny "
                       "oznacza przerwanie z zewnątrz, np. OOM killer przy braku RAM.)")
        where = f" przy {last_out_time}" if last_out_time else ""
        _log_render(f"FAIL rc={proc.returncode}{where}:\n" + detail[-3000:])
        raise RuntimeError(
            f"FFmpeg zakończył się błędem (kod {proc.returncode}{where}):\n"
            + detail)
    _log_render("OK")
    if progress_cb:
        progress_cb(1.0)
