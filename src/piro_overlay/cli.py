"""Tryb wiersza poleceń Piro Overlay (działa też z PiroOverlay.exe — patrz app.py).

Przykłady:
    # nakładka z osią z API, auto-wykrycie T0 (bzyczek) i auto-przycięcie wg strzałów
    piro-overlay --video in.mp4 --id 5 --auto -o out.mp4

    # jw. z płynącym czasem od T0 w prawym-górnym rogu
    piro-overlay --video in.mp4 --id 5 --auto --clock --clock-position top-right -o out.mp4

    # samo przycięcie (bez nakładki): 5 s przed T0 → 75 s po T0
    piro-overlay --video in.mp4 --auto --auto-window 75 --no-overlay -o out.mp4

    # klasycznie, z ręcznym T0 i osią z tekstu
    piro-overlay --video in.mp4 --timeline "1: 2.81s | 2: 4.63s (+1.82s)" --t0 3.2 -o out.mp4
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, api, audio_sync, ffmpeg, render
from .models import ANCHOR_POSITIONS, AnchorMode, Lang, OverlayStyle, Session
from .parser import parse_timeline

# Domyślne okno czasu (s) po T0, gdy auto-przycięcie nie ma osi strzałów.
_DEFAULT_AUTO_WINDOW = 75.0


def _default_output(video: str) -> str:
    p = Path(video)
    return str(p.with_name(p.stem + "_PiRoOverlay.mp4"))


def _build_session(args: argparse.Namespace) -> Session | None:
    """Sesja z osi czasu (tekst lub API). None gdy nie podano źródła."""
    if args.id is not None:
        return api.fetch_session(args.id)
    if args.timeline:
        return Session(shots=parse_timeline(args.timeline))
    return None


def _audio_src(video: str) -> str:
    """Plik do analizy audio — proxy LRF (DJI) jeśli jest obok, inaczej oryginał."""
    lrf = ffmpeg.find_lrf(video)
    return str(lrf) if lrf else video


def _resolve_t0(args: argparse.Namespace, session: Session | None,
                mode: AnchorMode) -> float:
    """Ustala T0. --auto → detekcja bzyczka (START_SIGNAL); inaczej --t0 lub onset."""
    if args.t0 is not None:
        anchor = args.t0
    elif args.auto:
        detected = audio_sync.detect_dji_start(_audio_src(args.video))
        if detected is None:
            raise SystemExit("Nie wykryto sygnału startu (bzyczka) — podaj --t0 ręcznie.")
        anchor = detected
        print(f"Wykryty sygnał startu (T0): {anchor:.3f}s")
        return anchor  # bzyczek JEST sygnałem startu → bez przeliczania względem strzału
    else:
        detected = audio_sync.detect_start(
            _audio_src(args.video), start=args.trim_start, end=args.trim_end)
        if detected is None:
            raise SystemExit("Nie wykryto sygnału w audio — podaj --t0 ręcznie.")
        anchor = detected
        print(f"Wykryty punkt kotwicy: {anchor:.3f}s ({mode.value})")
    first = session.shots[0].czas if (session and session.shots) else 0.0
    return audio_sync.resolve_t0(anchor, mode, first)


def _compute_trim(args: argparse.Namespace, t0: float | None,
                  session: Session | None,
                  duration: float | None) -> tuple[float | None, float | None]:
    """Zwraca (trim_start, trim_end). Reguły auto: 5 s przed T0 →
    okno stałe (--auto-window) albo ostatni strzał + margines (--tail)."""
    if not (args.auto or args.auto_trim or args.auto_window is not None):
        return args.trim_start, args.trim_end
    if t0 is None:
        raise SystemExit("Auto-przycięcie wymaga T0 — użyj --auto lub --t0.")
    start = max(0.0, t0 - args.lead_in)
    if args.auto_window is not None:
        end = t0 + args.auto_window
    elif session and session.shots:
        _, end = render.auto_trim_window(
            t0, session.shots[-1].czas, tail=args.tail, lead_in=args.lead_in,
            duration=duration)
    else:
        end = t0 + _DEFAULT_AUTO_WINDOW
        print(f"Brak osi strzałów — używam stałego okna {_DEFAULT_AUTO_WINDOW:.0f} s po T0.")
    if duration is not None:
        end = min(end, duration)
    print(f"Auto-przycięcie: {start:.2f}s – {end:.2f}s")
    return start, end


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="piro-overlay", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--video", required=True, help="ścieżka do pliku wideo")
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--timeline", help="oś czasu strzałów jako tekst")
    src.add_argument("--id", type=int, help="ID wyniku z API kalkulatora")
    parser.add_argument("--t0", type=float, help="ręczny czas kotwicy (s); pomija auto-detekcję")
    parser.add_argument("--anchor", choices=[m.value for m in AnchorMode],
                        default=AnchorMode.START_SIGNAL.value, help="typ kotwicy")
    parser.add_argument("--lang", choices=[l.value for l in Lang],
                        default=Lang.PL.value, help="język napisów nakładki")
    parser.add_argument("--trim-start", type=float, default=None,
                        help="początek wycinanego fragmentu (s)")
    parser.add_argument("--trim-end", type=float, default=None,
                        help="koniec wycinanego fragmentu (s)")
    parser.add_argument("--encoder", choices=["auto", "gpu", "cpu"], default="auto",
                        help="enkoder wideo: auto (NVENC jeśli jest), gpu, cpu")
    # --- auto-detekcja T0 + auto-przycięcie ---
    parser.add_argument("--auto", action="store_true",
                        help="auto-wykryj T0 (bzyczek, START_SIGNAL) i auto-przytnij")
    parser.add_argument("--auto-window", type=float, default=None,
                        help="stałe okno po T0 (s) do przycięcia zamiast „ostatni strzał + margines”")
    parser.add_argument("--lead-in", type=float, default=5.0,
                        help="ile sekund przed T0 zostawić przy auto-przycięciu (domyślnie 5)")
    parser.add_argument("--auto-trim", action="store_true",
                        help="przytnij wg strzałów: od T0−lead-in do ostatniego strzału + margines")
    parser.add_argument("--tail", type=float, default=5.0,
                        help="margines po ostatnim strzale (s) dla auto-przycięcia")
    # --- nakładka / zegar ---
    parser.add_argument("--no-overlay", action="store_true",
                        help="bez nakładki — tylko przytnij wideo")
    parser.add_argument("--clock", action="store_true",
                        help="pokaż płynący czas od T0 nad nakładką")
    parser.add_argument("--clock-position", choices=["auto", *ANCHOR_POSITIONS],
                        default="auto", help="pozycja zegara (auto = nad nakładką)")
    parser.add_argument("--clock-offset-x", type=int, default=32,
                        help="offset X zegara (gdy pozycja ≠ auto)")
    parser.add_argument("--clock-offset-y", type=int, default=32,
                        help="offset Y zegara (gdy pozycja ≠ auto)")
    parser.add_argument("-o", "--output", default=None,
                        help="ścieżka wyjściowa (domyślnie: obok źródła z sufiksem _PiRoOverlay)")
    args = parser.parse_args(argv)

    mode = AnchorMode.START_SIGNAL if args.auto else AnchorMode(args.anchor)
    session = _build_session(args)
    if not args.no_overlay and not (session and session.shots):
        raise SystemExit("Nakładka wymaga osi czasu — podaj --timeline lub --id "
                         "(albo użyj --no-overlay).")

    duration = ffmpeg.probe(args.video).duration or None

    # T0 potrzebny do nakładki oraz do auto-przycięcia.
    needs_t0 = (not args.no_overlay) or args.auto or args.auto_trim or args.auto_window is not None
    t0 = _resolve_t0(args, session, mode) if needs_t0 else None

    trim_start, trim_end = _compute_trim(args, t0, session, duration)
    output = args.output or _default_output(args.video)

    def on_progress(p: float) -> None:
        print(f"\rRender: {p * 100:5.1f}%", end="", flush=True)

    if args.no_overlay:
        render.trim_video(args.video, output, trim_start=trim_start, trim_end=trim_end,
                          encoder=args.encoder, progress_cb=on_progress)
    else:
        style = OverlayStyle(
            lang=Lang(args.lang),
            show_running_clock=args.clock,
            clock_position=args.clock_position,
            clock_offset_x=args.clock_offset_x,
            clock_offset_y=args.clock_offset_y,
        )
        render.render_video(args.video, session, t0, style, mode, output, on_progress,
                            trim_start=trim_start, trim_end=trim_end,
                            encoder=args.encoder)
    print(f"\nZapisano: {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
