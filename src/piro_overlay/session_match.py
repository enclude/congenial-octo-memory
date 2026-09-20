"""Dopasowanie nagrania do sesji z kalkulatora PO CZASIE (gdy sygnał ID z audio zawodzi).

Bez Qt/argparse. Dwa źródła czasu po stronie bazy są komplementarne:

* ``timer_sess_id`` — start sesji NA TIMERZE (unixtime, ale w czasie LOKALNYM
  urządzenia). Dokładny co do sekund, tylko dla wpisów zapisanych z timera.
  Odporny na hurtową wysyłkę z cache pod koniec dnia.
* ``data_zapisu`` — chwila zapisu w bazie (UTC, SQLite ``CURRENT_TIMESTAMP``).
  Zawsze obecny, ale sesja kończy się PRZED zapisem — wpis ręczny do kalkulatora
  albo „Zapisz w bazie" na timerze pada zwykle kilka–kilkadziesiąt sekund po
  ostatnim strzale, a przy hurtowej wysyłce godziny później (wtedy bezużyteczny).

Po stronie nagrania: czas startu z nazwy pliku DJI (``DJI_YYYYMMDDHHMMSS_NNNN_D``,
czas LOKALNY kamery), z tagu kontenera ``creation_time`` (DJI: UTC z „Z") albo
z mtime pliku (koniec nagrania → minus długość). Pomiar na realnym pliku
``DJI_20260707180623_0051_D.MP4``: nazwa 18:06:23 CEST, ``creation_time``
16:06:24Z, mtime 18:06:59 (długość 33 s) — trzy źródła zgodne co do sekundy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path

from .api import SessionCandidate

# start sesji na timerze poprzedza bzyczek (T0) o `start_delay` (~1–2 s) i klik
# „Start" — ale zegar timera DRYFUJE: 2026-08-12 zgadzał się z kamerą co do 2 s,
# 2026-09-20 szedł ~110 s do przodu (sesje 350–360 mają data_zapisu PRZED startem
# na timerze), a po południu znów ~0. Stąd szerokie okno i brak auto-wyboru, gdy
# w oknie jest więcej niż jeden kandydat z timera (patrz `pick`).
TIMER_TOL_S = 150.0
# zapis w bazie pada PO końcu sesji: od razu (timer „Zapisz w bazie") do kilku minut
# (ręczne wpisanie do kalkulatora między strzelcami)
SAVE_MIN_S = -15.0
SAVE_MAX_S = 300.0
# jednoznaczność: najlepszy kandydat musi wyprzedzać kolejnego (tej samej podstawy)
# o tyle sekund — realne dane: kolejny strzelec zapisuje wynik 40 s – 3 min po poprzednim,
# więc samo „w oknie" nie rozstrzyga, ale różnica |Δ| 3 s vs 180 s już tak
PICK_MARGIN_S = 60.0
# margines okna zapytania do API wokół nagrania
QUERY_LEAD_S = 120.0
QUERY_TAIL_S = SAVE_MAX_S + 120.0

# `DJI_20260812195106_0035_D.MP4`, ogólnie `..._20260812_195106...` / `20260812195106`
_DJI_RE = re.compile(r"^DJI_(\d{14})(?:_|$)")
_GENERIC_RE = re.compile(r"(?<!\d)(\d{8})[_\-T ]?(\d{6})(?!\d)")


@dataclass(frozen=True)
class RecordingTime:
    start: datetime          # aware, strefa lokalna
    source: str              # "filename" | "creation_time" | "mtime"


@dataclass(frozen=True)
class Match:
    candidate: SessionCandidate
    basis: str               # "timer" (timer_sess_id) | "saved" (data_zapisu)
    delta_s: float           # timer: start sesji − oczekiwany start; saved: zapis − oczekiwany koniec
    in_window: bool          # mieści się w tolerancji dla swojej podstawy
    shot_score: float | None = None   # odcisk strzałów (audio_sync.shot_alignment_score), gdy liczony


# odcisk rozstrzyga, gdy najlepszy wygrywa z drugim co najmniej tyle razy
# (na 24 nagraniach z 2026-09-20 właściwa sesja miała ≥1,4×; duplikat wpisu = 1,0×)
SHOT_SCORE_RATIO = 1.3


@dataclass(frozen=True)
class MatchResult:
    recording: RecordingTime | None
    matches: tuple[Match, ...]          # posortowane od najlepszego
    picked: Match | None                # jednoznaczne trafienie albo None (brak / kilka)

    @property
    def ambiguous(self) -> bool:
        return self.picked is None and any(m.in_window for m in self.matches)


def local_tz() -> tzinfo:
    tz = datetime.now().astimezone().tzinfo
    assert tz is not None
    return tz


def parse_creation_time(text: str) -> datetime | None:
    """ISO 8601 z tagu `creation_time`; naiwny czas traktujemy jako UTC (tak zapisuje FFmpeg/DJI)."""
    text = text.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def time_from_filename(path: str | Path, tz: tzinfo | None = None) -> datetime | None:
    """Czas startu nagrania z nazwy pliku (DJI, potem ogólny `YYYYMMDD[_]HHMMSS`), w strefie `tz`."""
    stem = Path(path).stem
    m = _DJI_RE.match(stem)
    digits = m.group(1) if m else None
    if digits is None:
        g = _GENERIC_RE.search(stem)
        digits = g.group(1) + g.group(2) if g else None
    if digits is None:
        return None
    try:
        naive = datetime.strptime(digits, "%Y%m%d%H%M%S")
    except ValueError:
        return None
    return naive.replace(tzinfo=tz or local_tz())


def recording_start(path: str | Path, duration: float, creation_time: str = "",
                    tz: tzinfo | None = None) -> RecordingTime | None:
    """Start nagrania: nazwa pliku → `creation_time` → mtime − długość. None gdy nic nie ma."""
    tz = tz or local_tz()
    if (t := time_from_filename(path, tz)) is not None:
        return RecordingTime(t, "filename")
    if (c := parse_creation_time(creation_time)) is not None:
        return RecordingTime(c.astimezone(tz), "creation_time")
    try:
        mtime = Path(path).stat().st_mtime
    except OSError:
        return None
    end = datetime.fromtimestamp(mtime, tz)
    return RecordingTime(end - timedelta(seconds=max(duration, 0.0)), "mtime")


def query_window(rec: RecordingTime, duration: float) -> tuple[datetime, datetime, int]:
    """Okno `[from, to]` (UTC) i `tz_offset` (s) dla `api.find_sessions`."""
    frm = rec.start - timedelta(seconds=QUERY_LEAD_S)
    to = rec.start + timedelta(seconds=max(duration, 0.0) + QUERY_TAIL_S)
    off = rec.start.utcoffset() or timedelta(0)
    return frm.astimezone(timezone.utc), to.astimezone(timezone.utc), int(off.total_seconds())


def timer_start(cand: SessionCandidate, tz: tzinfo) -> datetime | None:
    """`timer_sess_id` (unixtime w czasie LOKALNYM timera) → aware datetime w `tz`."""
    if cand.timer_sess_id <= 0:
        return None
    wall = datetime.fromtimestamp(cand.timer_sess_id, timezone.utc).replace(tzinfo=None)
    return wall.replace(tzinfo=tz)


def match_sessions(candidates: list[SessionCandidate], rec: RecordingTime,
                   duration: float, t0: float | None = None) -> tuple[Match, ...]:
    """Ocena kandydatów względem nagrania; wynik posortowany od najlepszego.

    Znany T0 (bzyczek w nagraniu) daje oczekiwany START sesji = start nagrania + T0;
    bez T0 sesja może zaczynać się gdziekolwiek w nagraniu — tolerancje rozszerzają
    się o całą długość nagrania (jednoznaczność wtedy rzadsza).
    """
    tz = rec.start.tzinfo or local_tz()
    duration = max(duration, 0.0)
    est_start = rec.start + timedelta(seconds=t0) if t0 is not None else rec.start
    span = 0.0 if t0 is not None else duration
    out: list[Match] = []
    for cand in candidates:
        ts = timer_start(cand, tz)
        if ts is not None:
            delta = (ts - est_start).total_seconds()
            ok = -TIMER_TOL_S <= delta <= span + TIMER_TOL_S
            out.append(Match(cand, "timer", delta, ok))
            continue
        est_end = est_start + timedelta(seconds=cand.czas_bazowy)
        delta = (cand.data_zapisu - est_end).total_seconds()
        ok = SAVE_MIN_S <= delta <= span + SAVE_MAX_S
        out.append(Match(cand, "saved", delta, ok))

    def key(m: Match) -> tuple[int, int, float]:
        # w oknie przed spoza okna; timer przed saved (dokładniejszy); mniejsze |delta| pierwsze
        return (0 if m.in_window else 1, 0 if m.basis == "timer" else 1, abs(m.delta_s))

    return tuple(sorted(out, key=key))


def candidate_shots(cand: SessionCandidate) -> list[float] | None:
    """Czasy strzałów z `opis` kandydata (None, gdy brak/nieczytelne)."""
    from .parser import TimelineParseError, extract_start_delay, parse_timeline
    if not cand.opis:
        return None
    text, _ = extract_start_delay(cand.opis)
    try:
        return [s.czas for s in parse_timeline(text)]
    except (TimelineParseError, ValueError):
        return None


def apply_shot_scores(matches: tuple[Match, ...],
                      scores: dict[int, float]) -> tuple[Match, ...]:
    """Dopisuje odcisk strzałów i sortuje trafienia w oknie po nim (malejąco);
    kandydaci bez wyniku i spoza okna zostają za nimi w dotychczasowym porządku."""
    from dataclasses import replace
    scored = tuple(replace(m, shot_score=scores.get(m.candidate.id)) for m in matches)
    top = sorted((m for m in scored if m.in_window and m.shot_score is not None),
                 key=lambda m: -m.shot_score)
    rest = [m for m in scored if not (m.in_window and m.shot_score is not None)]
    return tuple(top) + tuple(rest)


def pick(matches: tuple[Match, ...]) -> Match | None:
    """Jednoznaczne trafienie albo None (użytkownik wybiera z listy).

    Jedno trafienie w oknie → ono. Kilka → wygrywa timer nad `data_zapisu`
    (odporny na hurtową wysyłkę), ale DWA kandydaci z timera w oknie = zawsze
    niejednoznaczne: przy dryfie zegara timera o ~2 min (realne, 2026-09-20)
    bliższy |Δ| wskazywał SĄSIEDNIĄ sesję (0003 → 343 zamiast 344), więc bliskość
    nic tu nie dowodzi. Dla `data_zapisu` (zegar serwera, wiarygodny) zostaje
    reguła marginesu `PICK_MARGIN_S`.
    """
    hits = [m for m in matches if m.in_window]
    if not hits:
        return None
    if len(hits) == 1:
        return hits[0]
    scored = sorted((m for m in hits if m.shot_score is not None),
                    key=lambda m: -m.shot_score)
    if len(scored) >= 2 and scored[0].shot_score >= SHOT_SCORE_RATIO * max(scored[1].shot_score, 1e-9):
        return scored[0]          # odcisk strzałów rozstrzyga niezależnie od zegarów
    if scored:
        return None               # policzony, ale bez wyraźnego zwycięzcy (np. duplikat wpisu)
    timer_hits = [m for m in hits if m.basis == "timer"]
    if timer_hits:
        return timer_hits[0] if len(timer_hits) == 1 else None
    best, second = hits[0], hits[1]      # posortowane po |delta| w match_sessions
    if abs(second.delta_s) - abs(best.delta_s) >= PICK_MARGIN_S:
        return best
    return None
