"""Wspólna orkiestracja przepływu: sesja → T0 → przycięcie.

Rdzeń logiki dzielony przez CLI (`cli.py`) i backend WWW (`web/`) — bez Qt,
bez argparse i bez print. Komunikaty dla użytkownika (printy CLI, odpowiedzi
HTTP) należą do warstw wejścia; tu tylko wartości i `PipelineError`.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from . import api, audio_sync, ffmpeg, render, session_match
from .models import AnchorMode, Session
from .parser import parse_timeline

# Domyślne okno czasu (s) po T0, gdy auto-przycięcie nie ma osi strzałów.
DEFAULT_AUTO_WINDOW = 75.0


class PipelineError(RuntimeError):
    """Błąd przepływu z komunikatem dla użytkownika końcowego."""


def build_session(timeline: str | None, result_id: int | None,
                  nazwa_toru: str | None = None,
                  uczestnik: str | None = None) -> Session | None:
    """Sesja z osi czasu (tekst lub API). None gdy nie podano źródła.

    `nazwa_toru`/`uczestnik` nadpisują metadane z API (albo uzupełniają sesję
    z tekstu, która metadanych nie ma) — patrz `apply_meta_override`.
    """
    if result_id is not None:
        session = api.fetch_session(result_id)
    elif timeline:
        session = Session(shots=parse_timeline(timeline))
    else:
        return None
    return apply_meta_override(session, nazwa_toru, uczestnik)


def apply_meta_override(session: Session, nazwa_toru: str | None,
                        uczestnik: str | None) -> Session:
    """Nadpisuje nazwę toru / uczestnika w sesji.

    Puste (None albo same białe znaki) = zostaw wartość z sesji (z API). Nie ma
    trybu „wyczyść” — ukrycie metadanych to sprawa stylu nakładki, nie danych.
    """
    changes = {}
    if nazwa_toru is not None and nazwa_toru.strip():
        changes["nazwa_toru"] = nazwa_toru.strip()
    if uczestnik is not None and uczestnik.strip():
        changes["uczestnik"] = uczestnik.strip()
    return replace(session, **changes) if changes else session


def audio_source(video: str | Path) -> str:
    """Plik do analizy audio — proxy LRF (DJI) jeśli jest obok, inaczej oryginał."""
    lrf = ffmpeg.find_lrf(video)
    return str(lrf) if lrf else str(video)


def detect_start_signal(video: str | Path) -> float | None:
    """T0 z bzyczka shot-timera. Bzyczek JEST sygnałem startu — bez przeliczania."""
    return audio_sync.detect_dji_start(audio_source(video))


def detect_id_tone(video: str | Path) -> int | None:
    """ID sesji z sygnału tonowego (timer odtwarza go po zapisie w bazie).

    ZAWSZE analizuje oryginalny plik, NIE `audio_source()`/proxy LRF — pasmo
    5000-7000 Hz zweryfikowano pomiarem na oryginalnym pliku (DJI Osmo Nano),
    a sygnał gra pod koniec nagrania, poza oknem na które LRF zwykle się
    używa (detekcja T0 na początku).
    """
    return audio_sync.decode_id_tone(str(video))


def find_session_by_time(video: str | Path, *, t0: float | None = None,
                         info: ffmpeg.VideoInfo | None = None,
                         hint_id: int | None = None) -> session_match.MatchResult:
    """Dopasowuje nagranie do wpisu w kalkulatorze PO CZASIE (opcja awaryjna, gdy
    sygnał ID z audio jest nieczytelny) — jedno wejście dla GUI/CLI/wsadu.

    Start nagrania: `session_match.recording_start` (nazwa DJI → `creation_time`
    → mtime). Kandydaci: `api.find_sessions` (tryb listy — widzi też
    `timer_sess_id`, więc łapie wpisy wysłane hurtowo z timera), a gdy serwer
    jeszcze nie ma trybu listy (`ApiUnsupported`) — `api.find_sessions_by_scan`
    po pojedynczych `?id=` (tylko `data_zapisu`). `t0` (bzyczek) zawęża okno
    do sekund; bez niego sesja może być gdziekolwiek w nagraniu.
    `recording=None` w wyniku = nie dało się ustalić czasu nagrania.
    """
    info = info or ffmpeg.probe(video)
    rec = session_match.recording_start(video, info.duration, info.creation_time)
    if rec is None:
        return session_match.MatchResult(None, (), None)
    frm, to, tz_off = session_match.query_window(rec, info.duration)
    try:
        cands = api.find_sessions(frm, to, tz_offset_s=tz_off)
    except api.ApiUnsupported:
        cands = api.find_sessions_by_scan(frm, to, hint_id=hint_id)
    matches = session_match.match_sessions(cands, rec, info.duration, t0)
    hits = [m for m in matches if m.in_window]
    if t0 is not None and len(hits) >= 2:
        # Kilka sesji w oknie czasu (zegar timera dryfuje, strzelcy co ~60–100 s):
        # rozstrzyga odcisk strzałów — oś czasu każdej sesji przyłożona do energii
        # audio od T0. Na proxy LRF (jak detekcja T0): ładowanie audio raz.
        timelines = {m.candidate.id: shots for m in hits
                     if (shots := session_match.candidate_shots(m.candidate))}
        if len(timelines) >= 2:
            scores = audio_sync.shot_alignment_scores(audio_source(video), t0, timelines)
            matches = session_match.apply_shot_scores(matches, scores)
    return session_match.MatchResult(rec, matches, session_match.pick(matches))


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


# ---------------------------------------------------------------------------
# T0 przestarzały z pamięci pliku (`file_settings.json`) — patrz CLAUDE.md
# „Wykrywanie przestarzałego T0 z pamięci pliku". Zapisany T0 niesie wersję
# detektora, który go wyznaczył (`audio_sync.START_DETECTOR_VERSION` w chwili
# detekcji); 0 = T0 ustawiony ręcznie (nigdy nie proponujemy nowej detekcji),
# brak/None = wpis sprzed śledzenia wersji (traktowany jak przestarzały).
# ---------------------------------------------------------------------------

def t0_needs_recheck(saved_detector: int | None, current: int) -> bool:
    """Czy warto uruchomić ponowną detekcję T0 i porównać z zapisaną wartością.

    False dla T0 ustawionego ręcznie (`saved_detector == 0`) — użytkownik
    świadomie skorygował wartość, nie proponujemy jej nadpisania. True gdy
    wersja jest nieznana (stary wpis bez klucza) albo starsza niż bieżąca.
    """
    if saved_detector == 0:
        return False
    if saved_detector is None:
        return True
    return saved_detector < current


def t0_differs(a: float, b: float, tol: float = 0.3) -> bool:
    """Czy dwie wartości T0 różnią się o więcej niż `tol` sekund."""
    return abs(a - b) > tol


# ---------------------------------------------------------------------------
# Skan katalogu z nagraniami (używa go „Automat z folderu…" w oknie wsadowym)
# ---------------------------------------------------------------------------

#: Rozszerzenia traktowane jako plik wideo (bez rozróżniania wielkości liter).
#: Proxy DJI (.LRF) i miniatury (.THM) celowo NIE są tu wymienione — do listy
#: wsadowej trafia tylko oryginał, proxy dokłada się samo (`ffmpeg.find_lrf`).
VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".mkv", ".avi", ".m4v"})


def scan_video_dir(path: str | Path, recursive: bool = False) -> list[Path]:
    """Pliki wideo w katalogu, posortowane po nazwie (katalog → nazwa).

    Pomija wszystko, co nie ma rozszerzenia z `VIDEO_SUFFIXES` (czyli m.in.
    proxy `.LRF` i miniatury `.THM` leżące obok nagrań DJI) oraz pliki ukryte
    i „._" (AppleDouble z kart formatowanych na macOS — to nie są nagrania).
    """
    root = Path(path)
    if not root.is_dir():
        raise PipelineError(f"To nie jest katalog: {root}")
    it = root.rglob("*") if recursive else root.glob("*")
    files = [p for p in it
             if p.suffix.lower() in VIDEO_SUFFIXES
             and not p.name.startswith(".")
             and p.is_file()]
    return sorted(files, key=lambda p: (str(p.parent).lower(), p.name.lower()))
