"""Wspólna orkiestracja przepływu: sesja → T0 → przycięcie.

Rdzeń logiki dzielony przez CLI (`cli.py`) i backend WWW (`web/`) — bez Qt,
bez argparse i bez print. Komunikaty dla użytkownika (printy CLI, odpowiedzi
HTTP) należą do warstw wejścia; tu tylko wartości i `PipelineError`.
"""

from __future__ import annotations

from pathlib import Path

from . import api, audio_sync, ffmpeg, render
from .models import AnchorMode, Session
from .parser import parse_timeline

# Domyślne okno czasu (s) po T0, gdy auto-przycięcie nie ma osi strzałów.
DEFAULT_AUTO_WINDOW = 75.0


class PipelineError(RuntimeError):
    """Błąd przepływu z komunikatem dla użytkownika końcowego."""


def build_session(timeline: str | None, result_id: int | None) -> Session | None:
    """Sesja z osi czasu (tekst lub API). None gdy nie podano źródła."""
    if result_id is not None:
        return api.fetch_session(result_id)
    if timeline:
        return Session(shots=parse_timeline(timeline))
    return None


def audio_source(video: str | Path) -> str:
    """Plik do analizy audio — proxy LRF (DJI) jeśli jest obok, inaczej oryginał."""
    lrf = ffmpeg.find_lrf(video)
    return str(lrf) if lrf else str(video)


def detect_start_signal(video: str | Path) -> float | None:
    """T0 z bzyczka shot-timera. Bzyczek JEST sygnałem startu — bez przeliczania."""
    return audio_sync.detect_dji_start(audio_source(video))


def detect_anchor(video: str | Path, start: float | None = None,
                  end: float | None = None) -> float | None:
    """Punkt kotwicy z pierwszego onsetu audio (bez filtra bzyczka)."""
    return audio_sync.detect_start(audio_source(video), start=start, end=end)


def compute_t0(anchor: float, mode: AnchorMode, session: Session | None) -> float:
    """Przelicza kotwicę na T0 względem trybu i pierwszego strzału."""
    first = session.shots[0].czas if (session and session.shots) else 0.0
    return audio_sync.resolve_t0(anchor, mode, first)


def compute_trim(t0: float | None, session: Session | None,
                 duration: float | None, *, auto: bool,
                 auto_window: float | None = None,
                 lead_in: float = 5.0, tail: float = 5.0,
                 trim_start: float | None = None,
                 trim_end: float | None = None,
                 ) -> tuple[float | None, float | None]:
    """Zwraca (trim_start, trim_end). Reguły auto: `lead_in` s przed T0 →
    okno stałe (`auto_window`) albo ostatni strzał + margines (`tail`);
    bez osi strzałów — DEFAULT_AUTO_WINDOW po T0."""
    if not (auto or auto_window is not None):
        return trim_start, trim_end
    if t0 is None:
        raise PipelineError("Auto-przycięcie wymaga T0 — użyj --auto lub --t0.")
    start = max(0.0, t0 - lead_in)
    if auto_window is not None:
        end = t0 + auto_window
    elif session and session.shots:
        _, end = render.auto_trim_window(
            t0, session.shots[-1].czas, tail=tail, lead_in=lead_in,
            duration=duration)
    else:
        end = t0 + DEFAULT_AUTO_WINDOW
    if duration is not None:
        end = min(end, duration)
    return start, end
