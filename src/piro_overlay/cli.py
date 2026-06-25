"""Tryb wiersza poleceń Piro Overlay.

Przykłady:
    piro-overlay --video in.mp4 --id 5 -o out.mp4
    piro-overlay --video in.mp4 --timeline "1: 2.81s | 2: 4.63s (+1.82s)" --t0 3.2 -o out.mp4
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, api, audio_sync, render
from .models import AnchorMode, Lang, OverlayStyle, Session
from .parser import parse_timeline


def _default_output(video: str) -> str:
    p = Path(video)
    return str(p.with_name(p.stem + "_PiRoOverlay.mp4"))


def _build_session(args: argparse.Namespace) -> Session:
    if args.id is not None:
        return api.fetch_session(args.id)
    return Session(shots=parse_timeline(args.timeline))


def _resolve_t0(args: argparse.Namespace, session: Session, mode: AnchorMode) -> float:
    if args.t0 is not None:
        anchor = args.t0
    else:
        detected = audio_sync.detect_start(
            args.video, start=args.trim_start, end=args.trim_end)
        if detected is None:
            raise SystemExit("Nie wykryto sygnału w audio — podaj --t0 ręcznie.")
        anchor = detected
        print(f"Wykryty punkt kotwicy: {anchor:.3f}s ({mode.value})")
    return audio_sync.resolve_t0(anchor, mode, session.shots[0].czas)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="piro-overlay", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--video", required=True, help="ścieżka do pliku wideo")
    src = parser.add_mutually_exclusive_group(required=True)
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
    parser.add_argument("--auto-trim", action="store_true",
                        help="przytnij wynik: od ~T0 do ostatniego strzału + margines")
    parser.add_argument("--tail", type=float, default=5.0,
                        help="margines po ostatnim strzale (s) dla --auto-trim")
    parser.add_argument("-o", "--output", default=None,
                        help="ścieżka wyjściowa (domyślnie: obok źródła z sufiksem _PiRoOverlay)")
    args = parser.parse_args(argv)

    mode = AnchorMode(args.anchor)
    session = _build_session(args)
    t0 = _resolve_t0(args, session, mode)
    style = OverlayStyle(lang=Lang(args.lang))
    output = args.output or _default_output(args.video)

    trim_start, trim_end = args.trim_start, args.trim_end
    if args.auto_trim:
        from . import ffmpeg
        dur = ffmpeg.probe(args.video).duration or None
        trim_start, trim_end = render.auto_trim_window(
            t0, session.shots[-1].czas, tail=args.tail, duration=dur)
        print(f"Auto-przycięcie: {trim_start:.2f}s – {trim_end:.2f}s")

    def on_progress(p: float) -> None:
        print(f"\rRender: {p * 100:5.1f}%", end="", flush=True)

    render.render_video(args.video, session, t0, style, mode, output, on_progress,
                        trim_start=trim_start, trim_end=trim_end,
                        encoder=args.encoder)
    print(f"\nZapisano: {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
