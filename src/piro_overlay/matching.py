"""Automatyczne wiązanie ujęć wideo z wpisami kalkulatora — algorytm punktowy.

Specyfikacja: `DOPASOWANIE-WIDEO.md` §3 (repo `esp32-timer-camera-control`, ADR-063).
Moduł domenowy bez Qt/FFmpeg/sieci: dostaje gotowe `Take` (sygnały wyciągnięte z pliku
przez `pipeline.extract_take`) i listę `SessionCandidate` (API), zwraca `Assignment`.
Punkty i progi: `matching_score` (wartości startowe do kalibracji).

Czas: wszystko porównujemy jako czas ŚCIENNY lokalny w sekundach („UTC-shaped", jak
`timer_sess_id`/`rec_start`/nazwa DJI). Czasy UTC (`data_zapisu`, nazwa PXL,
`creation_time`) przeliczamy na strefę użytkownika PRZED porównaniem.

Zegary: E (ESP), T (timer), D (kamera DJI), P (telefon). Offset urządzenia
`δ = zegar_urządzenia − E` estymujemy z kotwic (ujęcia z ID-tone kanału 0), a start
skorygowany to `start_raw − δ`.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, tzinfo
from pathlib import Path
from typing import Callable, Iterable

from . import matching_score as S
from . import session_match as sm
from .api import SessionCandidate
from .audio_sync import IdToneCode
from .parser import extract_start_delay

_EPOCH = datetime(1970, 1, 1)
_DJI_NAME_RE = re.compile(r"^DJI_\d{14}_\d{4}(?:_[A-Z])?$", re.IGNORECASE)
_PXL_NAME_RE = re.compile(r"^PXL_\d{8}_\d{9}", re.IGNORECASE)


# ---------------------------------------------------------------------------
# czas ścienny
# ---------------------------------------------------------------------------

def wall_of(dt: datetime, tz: tzinfo) -> float:
    """Aware → czas ścienny w `tz`; naiwny traktujemy jako już ścienny."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(tz).replace(tzinfo=None)
    return (dt - _EPOCH).total_seconds()


def wall_to_datetime(wall: float, tz: tzinfo) -> datetime:
    """Czas ścienny (s) → aware datetime w `tz`."""
    return (_EPOCH + timedelta(seconds=wall)).replace(tzinfo=tz)


def fmt_wall(wall: float | None) -> str:
    if wall is None:
        return "?"
    return (_EPOCH + timedelta(seconds=wall)).strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# ujęcie
# ---------------------------------------------------------------------------

def classify(path: str | Path) -> str:
    """Rodzaj ujęcia po prefiksie nazwy: `dji` | `pixel` | `other`."""
    stem = Path(path).stem
    if _DJI_NAME_RE.match(stem):
        return "dji"
    if _PXL_NAME_RE.match(stem):
        return "pixel"
    return "other"


def device_key(kind: str, path: str | Path, cam: str = "") -> str:
    """Klucz urządzenia — ujęcia jednego klucza konkurują o wpisy (≤ 1 ujęcie na wpis).

    DJI i Pixel z prefiksu nazwy (`cam` = skrót kamery z metadanych, gdy znany); inne
    pliki — po katalogu (jeden katalog ≈ jedno urządzenie)."""
    if kind == "dji":
        return "dji:" + cam if cam else "dji"
    if kind == "pixel":
        return "pxl"
    return "other:" + str(Path(path).parent)


@dataclass(frozen=True)
class Take:
    """Jedno ujęcie: plik MP4 (+ proxy LRF / miniatura THM tego samego rdzenia)."""
    stem: str
    path: Path
    kind: str                        # dji | pixel | other
    device_key: str
    start_raw: float | None          # start wg zegara urządzenia, czas ścienny (s)
    start_src: str = ""              # filename | creation_time | mtime | ""
    duration: float = 0.0
    t0: float | None = None          # bzyczek w pliku (s od początku)
    tone: IdToneCode | None = None   # ramka ID-tone (z `pos_s`)
    files: tuple[Path, ...] = ()

    @property
    def key(self) -> str:
        """Unikalny klucz ujęcia (rdzeń nazwy bywa ten sam w dwóch katalogach)."""
        return str(self.path)


_SIDE_SUFFIXES = (".lrf", ".thm")


def group_by_stem(paths: Iterable[str | Path]) -> list[tuple[Path, tuple[Path, ...]]]:
    """MP4 + LRF + THM o tym samym rdzeniu (w tym samym katalogu) = jedno ujęcie.

    Zwraca [(plik_główny, wszystkie_pliki)], tylko grupy z plikiem wideo."""
    groups: dict[tuple[str, str], list[Path]] = {}
    for p in map(Path, paths):
        groups.setdefault((str(p.parent).lower(), p.stem.upper()), []).append(p)
    out: list[tuple[Path, tuple[Path, ...]]] = []
    for files in groups.values():
        main = [f for f in files if f.suffix.lower() not in _SIDE_SUFFIXES]
        if main:
            out.append((sorted(main)[0], tuple(sorted(files))))
    return sorted(out, key=lambda g: (str(g[0].parent).lower(), g[0].name.lower()))


# ---------------------------------------------------------------------------
# wpis
# ---------------------------------------------------------------------------

def entry_beep(c: SessionCandidate) -> tuple[float, str] | None:
    """Beep (T0) wpisu jako czas ścienny i zegar: `("E")` z `t_beep_ms` (ESP), `("T")`
    z `timer_sess_id + start_delay` (zegar timera, dryfuje), None dla wpisu ręcznego."""
    if c.t_beep_ms > 0:
        return c.t_beep_ms / 1000.0, "E"
    if c.timer_sess_id > 0:
        delay = extract_start_delay(c.opis)[1] if c.opis else None
        return c.timer_sess_id + (delay or 0.0), "T"
    return None


def entry_order_key(c: SessionCandidate, tz: tzinfo) -> float:
    b = entry_beep(c)
    return b[0] if b else wall_of(c.data_zapisu, tz) - c.czas_bazowy


# ---------------------------------------------------------------------------
# punkty
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Evidence:
    kind: str            # tone | tone_pos | preroll | duration | name | beep | saved | shots | station | order
    points: int
    reason: str
    contradiction: bool = False


@dataclass(frozen=True)
class PairScore:
    entry: SessionCandidate
    evidence: tuple[Evidence, ...] = ()

    @property
    def score(self) -> int:
        return sum(e.points for e in self.evidence)

    def plus(self, *ev: Evidence) -> "PairScore":
        return replace(self, evidence=self.evidence + tuple(ev))

    def has_tone(self) -> bool:
        return any(e.kind == "tone" and e.points > 0 for e in self.evidence)


def _tier(absd: float, tiers: tuple[tuple[float, int], ...], scale: float,
          bad_s: float, bad: int, pts_scale: float = 1.0) -> tuple[int, bool]:
    for lim, pts in tiers:
        if absd <= lim * scale:
            return round(pts * pts_scale), False
    if absd > bad_s * scale:
        return round(bad * pts_scale), True
    return 0, False


def _clock_free_evidence(take: Take, c: SessionCandidate) -> list[Evidence]:
    """Dowody niezależne od zegarów (T0 ↔ pre-roll, czas trwania) — tylko DJI sterowane
    przez ESP (plik zaczyna i kończy ESP, więc te wielkości są porównywalne)."""
    out: list[Evidence] = []
    if take.kind != "dji":
        return out
    if (take.t0 is not None and c.video_preroll_ms is not None and c.video_preroll_ms >= 0
            and c.video_status != "partial"):
        # `partial`/REC spóźniony (preroll < 0): plik bez początku sesji — test pomijamy
        d = abs(take.t0 - c.video_preroll_ms / 1000.0)
        pts, bad = _tier(d, S.PREROLL_TIERS, 1.0, S.PREROLL_BAD_S, S.PREROLL_BAD)
        if pts:
            out.append(Evidence("preroll", pts,
                                f"T0 {take.t0:.2f} s vs pre-roll {c.video_preroll_ms / 1000:.2f} s",
                                bad))
    if (c.video_duration_s > 0 and take.duration > 0
            and c.video_status not in ("interrupted", "stop_unconfirmed")):
        d = abs(take.duration - c.video_duration_s)
        if d <= S.DURATION_TOL_S:
            out.append(Evidence("duration", S.DURATION_MATCH,
                                f"długość {take.duration:.0f} s ≈ {c.video_duration_s} s"))
        elif d > S.DURATION_BAD_S:
            out.append(Evidence("duration", S.DURATION_BAD,
                                f"długość {take.duration:.0f} s ≠ {c.video_duration_s} s", True))
    return out


def score_pair(take: Take, c: SessionCandidate, *, tz: tzinfo, offset: float = 0.0,
               offset_known: bool = False, stations: set[str] | None = None) -> PairScore:
    """Punkty pary (ujęcie, wpis) z §3.2 — bez odcisku strzałów i kolejności (te
    dokłada `match_takes`, bo zależą od pozostałych kandydatów).

    Kary zależne od zegara urządzenia (nazwa DJI, beep) są pełne i są SPRZECZNOŚCIĄ
    tylko przy zaufanym zegarze: telefon (NTP) albo offset z kotwic (`offset_known`).
    Zegar kamery bez kotwic bywa przestawiony o godzinę (DST, bateria, brak Mimo) —
    wtedy kara jest o połowę mniejsza i sama nie wetuje ID-tone. Tak samo zegar
    timera (wpis bez `t_beep_ms`) i ESP z `clock_ok = false`.
    """
    ev: list[Evidence] = []
    start = take.start_raw - offset if take.start_raw is not None else None
    clock_scale = S.UNSYNCED_SCALE if c.clock_ok is False else 1.0
    device_trusted = take.kind == "pixel" or offset_known
    esp_trusted = c.clock_ok is not False

    # --- ID-tone ---
    tone_ok = True
    if take.tone is not None:
        code = take.tone
        if code.is_db_id:
            if code.value == c.id:
                ev.append(Evidence("tone", S.TONE_DB_MATCH, f"ID-tone #{code.value}"))
            else:
                tone_ok = False
                ev.append(Evidence("tone", S.TONE_DB_OTHER,
                                   f"ID-tone wskazuje #{code.value}", True))
        elif c.temp_id and c.temp_id == code.temp_id:
            b = entry_beep(c)
            ref = b[0] if b else wall_of(c.data_zapisu, tz)
            if start is None:
                ev.append(Evidence("tone", 0, f"kod {code.label}, czas nagrania nieznany"))
            elif abs(ref - start) <= S.TEMP_MAX_AGE_S:
                ev.append(Evidence("tone", S.TONE_TEMP_MATCH, f"kod tymczasowy {code.label}"))
            else:
                ev.append(Evidence("tone", 0, f"stary kod {code.label} (> 12 h od nagrania)"))
        else:
            tone_ok = False
            ev.append(Evidence("tone", S.TONE_TEMP_OTHER,
                               f"kod {code.label} ≠ wpisu ({c.temp_id or 'brak'})", True))
        if (tone_ok and take.kind == "dji" and code.pos_s is not None
                and c.idtone_at_ms > 0 and c.rec_start > 0):
            expected = c.idtone_at_ms / 1000.0 - c.rec_start
            if abs(code.pos_s - expected) <= S.TONE_POS_TOL_S:
                ev.append(Evidence("tone_pos", S.TONE_POS_MATCH,
                                   f"ton w {code.pos_s:.1f} s ≈ {expected:.1f} s"))

    ev.extend(_clock_free_evidence(take, c))

    # --- nazwa DJI vs `video_file` ---
    if take.kind == "dji" and c.video_file:
        raw = sm.video_file_delta(c.video_file, take.path)
        if raw is None:
            if classify(c.video_file) == "dji" or c.video_file.upper().startswith("DJI_"):
                ev.append(Evidence("name", S.NAME_BAD,
                                   f"video_file {c.video_file} to inny plik", True))
        else:
            d = raw - offset
            if S.NAME_DELTA_MIN_S <= d <= S.NAME_DELTA_MAX_S:
                ev.append(Evidence("name", S.NAME_EXACT, f"nazwa pliku ≈ {c.video_file} ({d:+.0f} s)"))
            else:
                trusted = device_trusted and esp_trusted
                pts, bad = _tier(abs(d), S.NAME_TIERS, clock_scale, S.NAME_BAD_S, S.NAME_BAD)
                if bad and not trusted:
                    pts = round(pts * S.UNTRUSTED_PENALTY)
                if pts:
                    ev.append(Evidence("name", pts, f"nazwa pliku vs {c.video_file}: {d:+.0f} s",
                                       bad and trusted))

    # --- beep na osi urządzenia ---
    beep = entry_beep(c)
    if start is not None and beep is not None:
        bs, clk = beep
        scale = clock_scale
        pts_scale = 1.0
        if clk == "T":
            scale *= S.BEEP_TIMER_SCALE
            pts_scale = S.BEEP_TIMER_POINTS
        weak = take.start_src == "mtime"
        if weak:
            scale *= S.UNSYNCED_SCALE
        if take.t0 is not None:
            db = start + take.t0 - bs
            pts, bad = _tier(abs(db), S.BEEP_TIERS, scale, S.BEEP_BAD_S, S.BEEP_BAD, pts_scale)
            label = f"beep {db:+.0f} s ({'ESP' if clk == 'E' else 'timer'})"
        else:
            lo, hi = start, start + max(take.duration, 0.0)
            db = 0.0 if lo <= bs <= hi else min(abs(bs - lo), abs(bs - hi))
            if db <= S.BEEP_NO_T0_TOL_S * scale:
                pts, bad = round(S.BEEP_NO_T0 * pts_scale), False
            elif db > S.BEEP_BAD_S * scale:
                pts, bad = round(S.BEEP_BAD * pts_scale), True
            else:
                pts, bad = 0, False
            label = f"beep {db:.0f} s od nagrania (bez T0)"
        trusted = clk == "E" and esp_trusted and device_trusted and not weak
        if bad and not trusted:
            pts = round(pts * S.UNTRUSTED_PENALTY)
        if pts:
            ev.append(Evidence("beep", pts, label, bad and trusted))
    elif start is not None and beep is None:
        # wpis ręczny: zapis w bazie pada PO końcu sesji
        end = start + (take.t0 if take.t0 is not None else 0.0) + c.czas_bazowy
        span = 0.0 if take.t0 is not None else max(take.duration, 0.0)
        d = wall_of(c.data_zapisu, tz) - end
        if S.SAVE_MIN_S <= d <= S.SAVE_MAX_S + span:
            ev.append(Evidence("saved", S.SAVE_MATCH, f"zapis {d:+.0f} s po sesji"))

    if stations and c.timer_sn and c.timer_sn in stations:
        ev.append(Evidence("station", S.STATION_MATCH, f"stanowisko {c.timer_sn}"))
    return PairScore(c, tuple(ev))


def contradictions(take: Take, c: SessionCandidate, *, tz: tzinfo,
                   offset: float = 0.0) -> list[str]:
    """Powody sprzeczności pary (np. ID-tone wskazuje wpis, a pre-roll/czas mu przeczą)."""
    return [e.reason for e in score_pair(take, c, tz=tz, offset=offset).evidence
            if e.contradiction]


def shot_evidence(scores: dict[int, float]) -> dict[int, Evidence]:
    """Odcisk strzałów → dowód per wpis: zwycięzca z przewagą ≥ SHOT_RATIO dostaje
    +SHOT_MATCH, oś trafiająca w tło (≈ 1) — SHOT_BACKGROUND."""
    out: dict[int, Evidence] = {}
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    for eid, sc in ranked:
        if sc <= S.SHOT_BACKGROUND_MAX:
            out[eid] = Evidence("shots", S.SHOT_BACKGROUND, f"odcisk {sc:.1f}× (tło)")
    if len(ranked) >= 2 and ranked[0][1] > S.SHOT_BACKGROUND_MAX \
            and ranked[0][1] >= S.SHOT_RATIO * max(ranked[1][1], 1e-9):
        out[ranked[0][0]] = Evidence("shots", S.SHOT_MATCH, f"odcisk {ranked[0][1]:.1f}×")
    return out


# ---------------------------------------------------------------------------
# decyzja
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Assignment:
    take: Take
    entry_id: int | None
    state: str                       # picked | ambiguous | none
    score: int = 0
    margin: int = 0
    reasons: tuple[str, ...] = ()
    top: tuple[tuple[int, int], ...] = ()   # (entry_id, score) — do dialogu „do decyzji"
    locked: bool = False             # zapisane wcześniej (picked albo decyzja ręczna)
    source: str = "auto"             # auto | manual

    @property
    def label(self) -> str:
        """Tekst dla UI/CLI: „#1247 (…)" / „do decyzji: …" / „brak wpisu"."""
        why = "; ".join(self.reasons)
        if self.state == "picked":
            return f"#{self.entry_id}" + (f" ({why})" if why else "")
        if self.state == "ambiguous":
            return "do decyzji: " + (why or "kilku kandydatów")
        return "brak wpisu" + (f": {why}" if why else "")


def _top(scored: list[PairScore], n: int = 3) -> tuple[tuple[int, int], ...]:
    return tuple((p.entry.id, p.score) for p in scored[:n])


def _fmt_top(scored: list[PairScore]) -> str:
    return ", ".join(f"#{p.entry.id} ({p.entry.uczestnik or p.entry.nazwa_toru or '?'}, {p.score} pkt)"
                     for p in scored[:3])


def decide(take: Take, scored: list[PairScore]) -> Assignment:
    """§3.3: `picked` tylko przy ≥ PICK_MIN i przewadze ≥ PICK_MARGIN bez sprzeczności.

    Sprzeczność = dowód ≤ HARD_NEG albo KAŻDY dowód oznaczony `contradiction` przy
    zwycięzcy (ostrzej niż sam HARD_NEG w specyfikacji: T0↔pre-roll −25 czy czas
    trwania −15 same nie przekraczają progu, a przeczą ID-tone — A6/O3)."""
    scored = sorted(scored, key=lambda p: -p.score)
    if not scored or scored[0].score <= 0:
        why = tuple(e.reason for e in scored[0].evidence) if scored else ()
        return Assignment(take, None, "none", scored[0].score if scored else 0,
                          reasons=why or ("brak pasującego wpisu",), top=_top(scored))
    best = scored[0]
    second = max(scored[1].score, 0) if len(scored) > 1 else 0
    margin = best.score - second
    bad = [e for e in best.evidence if e.contradiction or e.points <= S.HARD_NEG]
    if bad:
        head = next((e.reason for e in best.evidence if e.kind == "tone" and e.points > 0), "")
        why = (f"{head}, ale " if head else "sprzeczne dowody: ") + "; ".join(e.reason for e in bad)
        return Assignment(take, None, "ambiguous", best.score, margin, (why,), _top(scored))
    if best.score >= S.PICK_MIN and margin >= S.PICK_MARGIN:
        return Assignment(take, best.entry.id, "picked", best.score, margin,
                          tuple(e.reason for e in best.evidence if e.points > 0), _top(scored))
    if best.score >= S.PICK_MIN:
        why = f"przewaga {margin} pkt < {S.PICK_MARGIN}: {_fmt_top(scored)}"
    else:
        why = f"za mało dowodów ({best.score} pkt < {S.PICK_MIN}): {_fmt_top(scored)}"
    return Assignment(take, None, "ambiguous", best.score, margin, (why,), _top(scored))


# ---------------------------------------------------------------------------
# offset zegara urządzenia (O6)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DeviceOffset:
    device_key: str
    delta_s: float = 0.0
    anchors: int = 0
    known: bool = False
    iqr_s: float | None = None

    @property
    def note(self) -> str:
        if self.known:
            return f"offset {self.device_key} {self.delta_s:+.1f} s z {self.anchors} kotwic"
        return f"offset {self.device_key} nieznany ({self.anchors} kotwic)"


def estimate_offsets(takes: Iterable[Take], entries: dict[int, SessionCandidate]
                     ) -> dict[str, DeviceOffset]:
    """δ per urządzenie z kotwic: ujęcia z tonem kanału 0 wskazującym wpis z `t_beep_ms`
    (zegar ESP), bez sprzeczności niezależnych od zegarów. ≥ OFFSET_MIN_ANCHORS kotwic
    i IQR ≤ OFFSET_MAX_IQR_S → mediana; inaczej 0 i „nieznany" (wzorem ADR-047 ESP)."""
    samples: dict[str, list[float]] = {}
    keys: set[str] = set()
    for t in takes:
        keys.add(t.device_key)
        if t.tone is None or not t.tone.is_db_id or t.t0 is None or t.start_raw is None:
            continue
        c = entries.get(t.tone.value)
        if c is None or c.t_beep_ms <= 0 or c.clock_ok is False:
            continue
        if any(e.contradiction for e in _clock_free_evidence(t, c)):
            continue
        samples.setdefault(t.device_key, []).append(t.start_raw + t.t0 - c.t_beep_ms / 1000.0)
    out: dict[str, DeviceOffset] = {}
    for k in keys:
        d = sorted(samples.get(k, []))
        if len(d) >= S.OFFSET_MIN_ANCHORS:
            q = statistics.quantiles(d, n=4, method="inclusive")
            iqr = q[2] - q[0]
            if iqr <= S.OFFSET_MAX_IQR_S:
                out[k] = DeviceOffset(k, statistics.median(d), len(d), True, iqr)
                continue
            out[k] = DeviceOffset(k, 0.0, len(d), False, iqr)
            continue
        out[k] = DeviceOffset(k, 0.0, len(d), False)
    return out


# ---------------------------------------------------------------------------
# przydział globalny per urządzenie (O4)
# ---------------------------------------------------------------------------

def _monotone_assignment(takes: list[Take], entries: list[SessionCandidate],
                         weight: dict[tuple[str, int], int]) -> dict[str, int]:
    """Maksymalna suma punktów przy 1 ujęcie ↔ ≤ 1 wpis, 1 wpis ↔ ≤ 1 ujęcie i
    zachowanej kolejności (DP po posortowanych listach, O(n·m)). Zwraca {Take.key: entry_id}."""
    n, m = len(takes), len(entries)
    M = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            w = weight.get((takes[i - 1].key, entries[j - 1].id), 0)
            best = max(M[i - 1][j], M[i][j - 1])
            if w > 0:
                best = max(best, M[i - 1][j - 1] + w)
            M[i][j] = best
    out: dict[str, int] = {}
    i, j = n, m
    while i > 0 and j > 0:
        w = weight.get((takes[i - 1].key, entries[j - 1].id), 0)
        if w > 0 and M[i][j] == M[i - 1][j - 1] + w:
            out[takes[i - 1].key] = entries[j - 1].id
            i, j = i - 1, j - 1
        elif M[i][j] == M[i - 1][j]:
            i -= 1
        else:
            j -= 1
    return out


ShotScorer = Callable[[Take, dict[int, list[float]]], dict[int, float]]


@dataclass
class MatchReport:
    assignments: list[Assignment]
    offsets: dict[str, DeviceOffset] = field(default_factory=dict)


def match_takes(takes: list[Take], entries: list[SessionCandidate], *, tz: tzinfo,
                shot_scorer: ShotScorer | None = None,
                locked: dict[str, Assignment] | None = None) -> MatchReport:
    """Przebieg wsadowy §3.4 kroki 2–5: offsety, punkty, odcisk, przydział, decyzja.

    `locked` = {Take.key: Assignment} zapisanych wcześniej przypisań (picked albo ręczne) —
    nie są przeliczane, a ich wpis jest zajęty dla innych ujęć tego urządzenia."""
    locked = locked or {}
    by_id: dict[int, SessionCandidate] = {}
    for c in entries:
        by_id.setdefault(c.id, c)
    uniq = list(by_id.values())
    offsets = estimate_offsets(takes, by_id)

    def score_all(stations: dict[str, set[str]]) -> dict[str, list[PairScore]]:
        out: dict[str, list[PairScore]] = {}
        for t in takes:
            if t.key in locked:
                continue
            off = offsets.get(t.device_key, DeviceOffset(t.device_key))
            out[t.key] = sorted((score_pair(t, c, tz=tz, offset=off.delta_s,
                                             offset_known=off.known,
                                             stations=stations.get(t.device_key))
                                  for c in uniq), key=lambda p: -p.score)
        return out

    scored = score_all({})
    # stanowisko: `timer_sn` wpisów pewnie przypisanych po ID-tone temu urządzeniu
    stations: dict[str, set[str]] = {}
    for t in takes:
        a = locked.get(t.key)
        if a is not None and a.entry_id in by_id:
            sn = by_id[a.entry_id].timer_sn
        elif t.key in scored and (d := decide(t, scored[t.key])).state == "picked" \
                and scored[t.key][0].has_tone():
            sn = by_id[d.entry_id].timer_sn
        else:
            continue
        if sn:
            stations.setdefault(t.device_key, set()).add(sn)
    if stations:
        scored = score_all(stations)

    if shot_scorer is not None:
        from .session_match import candidate_shots
        for t in takes:
            if t.key not in scored or t.t0 is None:
                continue
            top = [p for p in scored[t.key] if p.score > S.HARD_NEG][:S.SHOT_TOP_K]
            timelines = {p.entry.id: shots for p in top if (shots := candidate_shots(p.entry))}
            if not timelines:
                continue
            extra = shot_evidence(shot_scorer(t, timelines))
            scored[t.key] = sorted((p.plus(extra[p.entry.id]) if p.entry.id in extra else p
                                     for p in scored[t.key]), key=lambda p: -p.score)

    # przydział globalny per urządzenie
    devices: dict[str, list[Take]] = {}
    for t in takes:
        devices.setdefault(t.device_key, []).append(t)
    holder: dict[tuple[str, int], str] = {}     # (device, entry_id) → Take.key właściciela
    assigned: dict[str, int] = {}
    for dev, group in devices.items():
        for t in group:
            a = locked.get(t.key)
            if a is not None and a.entry_id is not None:
                holder[(dev, a.entry_id)] = t.key
        free = [t for t in group if t.key in scored]
        ordered = sorted((t for t in free if t.start_raw is not None), key=lambda t: t.start_raw)
        ents = sorted((c for c in uniq if (dev, c.id) not in holder),
                      key=lambda c: entry_order_key(c, tz))
        weight = {(t.key, p.entry.id): p.score for t in ordered for p in scored[t.key]
                  if p.score > 0 and (dev, p.entry.id) not in holder}
        dp = _monotone_assignment(ordered, ents, weight)
        for t in free:
            if t.start_raw is None and scored[t.key] and scored[t.key][0].score > 0:
                eid = scored[t.key][0].entry.id
                if (dev, eid) not in holder:
                    dp[t.key] = eid
        for key, eid in dp.items():
            holder[(dev, eid)] = key
            assigned[key] = eid
        n_assigned = sum(1 for t in free if t.key in dp)
        if n_assigned >= 2:
            for t in free:
                if t.key in dp:
                    scored[t.key] = sorted(
                        (p.plus(Evidence("order", S.ORDER_OK, "kolejność nagrań zgodna"))
                         if p.entry.id == dp[t.key] else p for p in scored[t.key]),
                        key=lambda p: -p.score)

    result: list[Assignment] = []
    for t in takes:
        if t.key in locked:
            result.append(replace(locked[t.key], take=t, locked=True))
            continue
        sc = scored[t.key]
        best = sc[0] if sc else None
        eid = assigned.get(t.key)
        if best is not None and best.score >= S.PICK_MIN and eid != best.entry.id:
            owner = holder.get((t.device_key, best.entry.id))
            why = (f"konflikt z {Path(owner).name} o #{best.entry.id}" if owner and owner != t.key
                   else f"#{best.entry.id} narusza kolejność nagrań {t.device_key}")
            a = Assignment(t, None, "ambiguous", best.score, 0, (why,), _top(sc))
        else:
            a = decide(t, sc)
        result.append(a)

    # zwycięzca konfliktu bez wyraźnej przewagi nad przegranym też idzie do decyzji
    for i, a in enumerate(result):
        if a.state != "picked" or a.locked:
            continue
        rivals = [o for o in result if o is not a and o.take.device_key == a.take.device_key
                  and o.state == "ambiguous" and o.top and o.top[0][0] == a.entry_id
                  and o.top[0][1] >= S.PICK_MIN and a.score - o.top[0][1] < S.PICK_MARGIN]
        if rivals:
            result[i] = Assignment(a.take, None, "ambiguous", a.score, a.margin,
                                   (f"konflikt z {rivals[0].take.path.name} o #{a.entry_id}",), a.top)
    return MatchReport(result, offsets)
