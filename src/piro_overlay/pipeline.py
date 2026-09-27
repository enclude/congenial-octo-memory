"""Wspólna orkiestracja przepływu: sesja → T0 → przycięcie.

Rdzeń logiki dzielony przez CLI (`cli.py`) i backend WWW (`web/`) — bez Qt,
bez argparse i bez print. Komunikaty dla użytkownika (printy CLI, odpowiedzi
HTTP) należą do warstw wejścia; tu tylko wartości i `PipelineError`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import timedelta, timezone
from pathlib import Path

from . import api, assignment_store, audio_sync, ffmpeg, matching, render, session_match
from .matching_score import BATCH_CLUSTER_GAP_S, BATCH_QUERY_MARGIN_S
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


def detect_id_tone(video: str | Path) -> audio_sync.IdToneCode | None:
    """Ramka ID-tone v3 z audio: kanał + wartość (`audio_sync.IdToneCode`).

    Kanał 0 = wartość jest ID wpisu w bazie kalkulatora; kanał 1-9 = wartość
    jest KODEM TYMCZASOWYM sesji nagranej offline (rozwiązywany przez
    `resolve_id_tone`).

    ZAWSZE analizuje oryginalny plik, NIE `audio_source()`/proxy LRF — pasmo
    5000-7000 Hz zweryfikowano pomiarem na oryginalnym pliku (DJI Osmo Nano),
    a sygnał gra pod koniec nagrania, poza oknem na które LRF zwykle się
    używa (detekcja T0 na początku).
    """
    return audio_sync.decode_id_tone(str(video))


@dataclass(frozen=True)
class IdToneResult:
    """Wynik rozwiązania ramki ID-tone do ID wpisu w bazie kalkulatora."""
    code: audio_sync.IdToneCode
    session_id: int | None            # None = nie dało się jednoznacznie ustalić
    info: str = ""                    # tekst dla UI ("3-0147 → #1234") albo powód braku
    match: session_match.MatchResult | None = None   # tylko gdy rozstrzygał czas/odcisk


def take_for_video(video: str | Path, *, t0: float | None = None,
                   info: ffmpeg.VideoInfo | None = None,
                   tone: audio_sync.IdToneCode | None = None,
                   tz=None) -> matching.Take:
    """`matching.Take` jednego pliku z JUŻ znanych sygnałów (bez analizy audio).

    Czas startu: `session_match.recording_start` (nazwa → `creation_time` → mtime);
    plik nieczytelny/nieistniejący → ujęcie bez czasu (dowody czasowe pominięte)."""
    tz = tz or session_match.local_tz()
    path = Path(video)
    if info is None:
        try:
            info = ffmpeg.probe(video)
        except Exception:  # noqa: BLE001 — brak pliku/ffprobe: ujęcie bez czasu i długości
            info = None
    duration = info.duration if info else 0.0
    rec = session_match.recording_start(video, duration, info.creation_time if info else "",
                                        tz) if info else None
    kind = matching.classify(path)
    return matching.Take(stem=path.stem, path=path, kind=kind,
                         device_key=matching.device_key(kind, path),
                         start_raw=matching.wall_of(rec.start, tz) if rec else None,
                         start_src=rec.source if rec else "", duration=duration or 0.0,
                         t0=t0, tone=tone, files=(path,))


def resolve_id_tone(code: audio_sync.IdToneCode, video: str | Path, *,
                    t0: float | None = None,
                    info: ffmpeg.VideoInfo | None = None) -> IdToneResult:
    """Zamienia ramkę ID-tone na ID wpisu w bazie kalkulatora.

    Kanał 0 → wartość JEST tym ID, ale wpis jest pobierany i sprawdzany pod kątem
    sprzeczności z plikiem (T0 ↔ pre-roll, beep na osi urządzenia, czas trwania —
    O3: telefon potrafi złapać ton SĄSIEDNIEGO stanowiska); sprzeczność → brak ID
    z opisem „do decyzji: …". Błąd sieci → ID przyjęte jak dotąd (bez kontroli).
    Kanał 1-9 → kod tymczasowy: pytamy kalkulator o wpisy z tym `temp_id`; także
    JEDEN kandydat przechodzi ocenę czasu (≤ 12 h od nagrania i brak sprzeczności — O2:
    licznik zawija się po 9999, a właściwy wpis mógł jeszcze nie dotrzeć), kilku —
    rozstrzyga dopasowanie po czasie nagrania i odcisku strzałów. Bez rozstrzygnięcia
    `session_id` jest None — ZGADYWANIE jest gorsze od braku ID (nakładka pokazałaby
    cudzą sesję).
    """
    tz = session_match.local_tz()
    if code.is_db_id:
        try:
            cand = api.fetch_candidate(code.value)
        except api.ApiError as exc:
            return IdToneResult(code, code.value,
                                f"#{code.value}: nie sprawdzono spójności z wpisem ({exc})")
        if cand is None:
            return IdToneResult(code, None,
                                f"do decyzji: ID-tone #{code.value} — brak takiego wpisu w bazie")
        take = take_for_video(video, t0=t0, info=info, tone=code, tz=tz)
        bad = matching.contradictions(take, cand, tz=tz)
        if bad:
            return IdToneResult(code, None,
                                f"do decyzji: ID-tone #{code.value}, ale " + "; ".join(bad))
        return IdToneResult(code, code.value)
    try:
        cands = api.find_sessions_by_temp_id(code.temp_id)
    except api.ApiUnsupported:
        return IdToneResult(code, None,
                            f"kod tymczasowy {code.label}: kalkulator nie obsługuje "
                            "kodów tymczasowych — podaj ID ręcznie")
    except api.ApiError as exc:
        return IdToneResult(code, None,
                            f"kod tymczasowy {code.label}: odpytanie bazy nie powiodło się ({exc})")
    if not cands:
        return IdToneResult(code, None,
                            f"kod tymczasowy {code.label}: brak wpisu w bazie — "
                            "wyślij sesje z timera i spróbuj ponownie")
    take = take_for_video(video, t0=t0, info=info, tone=code, tz=tz)
    if len(cands) == 1:
        decision = matching.decide(take, [matching.score_pair(take, cands[0], tz=tz)])
        if decision.state != "picked":
            return IdToneResult(code, None,
                                f"do decyzji: kod tymczasowy {code.label} → #{cands[0].id}: "
                                + "; ".join(decision.reasons))
        return IdToneResult(code, cands[0].id, f"{code.label} → #{cands[0].id}")
    result = _match_candidates(video, cands, t0=t0, info=info)
    note = f" ({result.info})" if result.info else ""
    if result.picked is None:
        return IdToneResult(code, None,
                            f"kod tymczasowy {code.label}: {len(cands)} wpisów w bazie, "
                            f"czas nagrania nie rozstrzyga — wybierz ID ręcznie{note}", result)
    picked = result.picked.candidate
    check = matching.score_pair(take, picked, tz=tz)
    tone_ev = [e for e in check.evidence if e.kind == "tone"]
    bad = [e.reason for e in check.evidence if e.contradiction]
    if bad or not tone_ev or tone_ev[0].points <= 0:
        why = "; ".join(bad or [e.reason for e in tone_ev] or ["czas nagrania nieznany"])
        return IdToneResult(code, None,
                            f"do decyzji: kod tymczasowy {code.label} → #{picked.id}: {why}{note}",
                            result)
    return IdToneResult(code, picked.id, f"{code.label} → #{picked.id}{note}", result)


def detect_id(video: str | Path, *, t0: float | None = None,
              info: ffmpeg.VideoInfo | None = None) -> IdToneResult | None:
    """`detect_id_tone` + `resolve_id_tone` — jedno wejście dla GUI/WWW/wsadu.
    None = w audio nie ma czytelnej ramki ID. Bez podanego `t0` wykrywa bzyczek —
    kontrola sprzeczności (T0 ↔ pre-roll, beep) bez T0 jest dużo słabsza."""
    code = detect_id_tone(video)
    if code is None:
        return None
    if t0 is None:
        try:
            t0 = detect_start_signal(video)
        except Exception:  # noqa: BLE001 — brak T0 to tylko słabsza kontrola
            t0 = None
    return resolve_id_tone(code, video, t0=t0, info=info)


_POLISH_MAP = str.maketrans({
    "ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "ø": "o", "Ø": "O",
})
_FORBIDDEN_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename_part(text: str) -> str:
    """Tekst (np. nazwa uczestnika) → bezpieczny fragment nazwy pliku.

    Diakrytyki → ASCII (Jarosław → Jaroslaw), białe znaki → „_", znaki
    niedozwolone w nazwach Windows/Unix usunięte, kropki brzegowe zdjęte.
    "" gdy nic nie zostaje.
    """
    if not text:
        return ""
    text = text.translate(_POLISH_MAP)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"\s+", "_", text.strip())
    text = _FORBIDDEN_RE.sub("", text)
    return text.strip(". ")


# Zmienne szablonu nazwy pliku (prefiks/sufiks we wsadzie). Nieznane `{x}` zostają
# dosłownie — ktoś może chcieć nawiasów w nazwie, a literówka nie może wywalić wsadu.
NAME_TEMPLATE_VARS = ("id", "uczestnik", "tor", "strzaly", "czas", "hf", "typ")
_VAR_RE = re.compile(r"\{(" + "|".join(NAME_TEMPLATE_VARS) + r")\}")


def expand_name_template(template: str, session: Session | None,
                         session_id: int | None, variant_key: str = "") -> str:
    """Podstawia `{id}`, `{uczestnik}`, `{tor}`, `{strzaly}`, `{czas}` (czas bazowy),
    `{hf}` (hit factor), `{typ}` (wariant wsadu: overlay/timer/trim) — wartości
    sanityzowane; brak danych → pusty tekst."""
    if "{" not in template:
        return template
    czas = session.base_time if session else None
    values = {
        "typ": variant_key,
        "id": str(session_id) if session_id else "",
        "uczestnik": sanitize_filename_part((session.uczestnik or "") if session else ""),
        "tor": sanitize_filename_part((session.nazwa_toru or "") if session else ""),
        "strzaly": str(session.total_shots) if session and session.total_shots else "",
        "czas": f"{czas:.2f}".replace(".", "_") if czas is not None else "",
        "hf": (f"{session.hit_factor:.2f}".replace(".", "_")
               if session and session.hit_factor is not None else ""),
    }
    return _VAR_RE.sub(lambda m: values[m.group(1)], template)


@dataclass(frozen=True)
class BatchVariant:
    """Wariant wyjścia wsadu: `key` idzie do sufiksu nazwy pliku (`_overlay`/`_timer`/
    `_trim`), `no_overlay` → `render.trim_video`, `clock` → `show_running_clock`."""
    key: str
    no_overlay: bool
    clock: bool


BATCH_VARIANTS = (
    BatchVariant("overlay", no_overlay=False, clock=False),
    BatchVariant("timer", no_overlay=False, clock=True),
    BatchVariant("trim", no_overlay=True, clock=False),
)


def batch_variants(*, overlay: bool, timer: bool, trim: bool) -> list[BatchVariant]:
    """Zaznaczone warianty w stałej kolejności overlay → timer → trim."""
    flags = {"overlay": overlay, "timer": timer, "trim": trim}
    return [v for v in BATCH_VARIANTS if flags[v.key]]


def batch_variant_suffix(variants: list[BatchVariant], variant: BatchVariant) -> str:
    """Sufiks wariantu w nazwie pliku — tylko gdy wariantów jest więcej niż jeden
    (przy jednym nazwa zostaje jak dotąd, bez `_overlay`)."""
    return "" if len(variants) <= 1 else "_" + variant.key


_TYP_VAR = "{typ}"


def batch_output_name(prefix: str, stem: str, suffix: str, session: Session | None,
                      session_id: int | None, variants: list[BatchVariant],
                      variant: BatchVariant, ext: str) -> str:
    """Względna nazwa pliku wyjściowego wsadu: prefiks + stem + sufiks (szablony
    rozwinięte dla `variant`) + ext. Automatyczny sufiks wariantu (`_overlay`…) dochodzi
    tylko gdy wariantów jest >1 I użytkownik NIE użył `{typ}` w szablonie (sam wybrał,
    gdzie wariant ma stać). Ukośniki `/` `\\` w szablonie = podkatalogi (np. prefiks
    `{typ}\\` daje `overlay\\plik.mp4`); katalogi tworzy wołający (`Path.mkdir`).
    Wartości zmiennych nigdy nie zawierają separatorów (`sanitize_filename_part`)."""
    name = (expand_name_template(prefix, session, session_id, variant.key) + stem
            + expand_name_template(suffix, session, session_id, variant.key))
    if _TYP_VAR not in prefix and _TYP_VAR not in suffix:
        name += batch_variant_suffix(variants, variant)
    return name.replace("\\", "/") + ext


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
    return _match_candidates(video, cands, t0=t0, info=info)


def _match_candidates(video: str | Path, cands: list[api.SessionCandidate], *,
                      t0: float | None,
                      info: ffmpeg.VideoInfo | None) -> session_match.MatchResult:
    """Ocena gotowej listy kandydatów względem nagrania (nazwa pliku + okno nagrania
    + czas + odcisk strzałów).

    Wspólne dla dopasowania po oknie czasu (`find_session_by_time`) i dla
    rozstrzygania kilku wpisów o tym samym kodzie tymczasowym (`resolve_id_tone`).
    Pola nagrania z kalkulatora (`video_file`, `rec_start`/`rec_stop`) są opcjonalne:
    stary serwer ich nie zwraca → zachowanie jak dotąd.
    """
    info = info or ffmpeg.probe(video)
    rec = session_match.recording_start(video, info.duration, info.creation_time)
    if rec is None:
        return session_match.MatchResult(None, (), None)
    notes: list[str] = []
    kept, dropped = session_match.filter_by_recording_window(
        cands, rec, info.duration, t0, video)
    if dropped and not kept:
        # „nigdy nie zgaduj" działa w obie strony: okno z urządzenia mogło mieć zły
        # zegar — wszystkich nie wyrzucamy, zostaje ocena po czasie jak dotąd
        notes.append(f"okno nagrania wykluczyło wszystkich kandydatów ({dropped}) "
                     "— pominięto ten filtr")
    elif dropped:
        cands = kept
        notes.append(f"okno nagrania odrzuciło {dropped}")
    matches = session_match.match_sessions(cands, rec, info.duration, t0, video)
    named = [m for m in matches if m.file_match]
    if len(named) == 1:
        notes.insert(0, "dopasowano po nazwie pliku")
        return session_match.MatchResult(rec, matches, named[0], "; ".join(notes))
    if len(named) > 1:
        notes.insert(0, f"{len(named)} wpisy wskazują ten plik (duplikat?) — wybierz ręcznie")
    hits = [m for m in matches if m.in_window]
    if t0 is not None and len(hits) >= 2 and not named:
        # Kilka sesji w oknie czasu (zegar timera dryfuje, strzelcy co ~60–100 s):
        # rozstrzyga odcisk strzałów — oś czasu każdej sesji przyłożona do energii
        # audio od T0. Na proxy LRF (jak detekcja T0): ładowanie audio raz.
        timelines = {m.candidate.id: shots for m in hits
                     if (shots := session_match.candidate_shots(m.candidate))}
        if len(timelines) >= 2:
            scores = audio_sync.shot_alignment_scores(audio_source(video), t0, timelines)
            matches = session_match.apply_shot_scores(matches, scores)
    return session_match.MatchResult(rec, matches, session_match.pick(matches),
                                     "; ".join(notes))


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


# ---------------------------------------------------------------------------
# Automatyczne wiązanie wsadowe: folder z karty DJI + folder z telefonu
# (`DOPASOWANIE-WIDEO.md` §3.4, logika punktowa w `matching.py`)
# ---------------------------------------------------------------------------

def extract_take(path: str | Path, files: tuple[Path, ...] = (), *, tz=None) -> matching.Take:
    """Sygnały jednego ujęcia: czas startu, długość, T0 (bzyczek), ramka ID-tone z pozycją."""
    try:
        t0 = detect_start_signal(path)
    except Exception:  # noqa: BLE001 — plik bez audio: ujęcie bez T0
        t0 = None
    try:
        tone = detect_id_tone(path)
    except Exception:  # noqa: BLE001
        tone = None
    take = take_for_video(path, t0=t0, tone=tone, tz=tz)
    return replace(take, files=files or (Path(path),))


def fetch_entries_for_takes(takes: list[matching.Take], *, tz=None) -> list[api.SessionCandidate]:
    """Kandydaci z API dla całej partii: okno czasu wszystkich ujęć ± 1 h (osobne
    zapytanie per „dzień" — skupisko ujęć bez przerwy > 6 h) ∪ wpisy z kodami
    tymczasowymi z tonów ∪ wpisy wskazane tonem kanału 0 (pobierane po ID)."""
    tz = tz or session_match.local_tz()
    out: dict[int, api.SessionCandidate] = {}
    timed = sorted((t for t in takes if t.start_raw is not None), key=lambda t: t.start_raw)
    clusters: list[list[matching.Take]] = []
    for t in timed:
        if clusters and t.start_raw - (clusters[-1][-1].start_raw + clusters[-1][-1].duration) \
                <= BATCH_CLUSTER_GAP_S:
            clusters[-1].append(t)
        else:
            clusters.append([t])
    for group in clusters:
        lo = matching.wall_to_datetime(group[0].start_raw - BATCH_QUERY_MARGIN_S, tz)
        hi = matching.wall_to_datetime(max(t.start_raw + t.duration for t in group)
                                       + BATCH_QUERY_MARGIN_S, tz)
        off = int((lo.utcoffset() or timedelta(0)).total_seconds())
        frm, to = lo.astimezone(timezone.utc), hi.astimezone(timezone.utc)
        try:
            found = api.find_sessions(frm, to, tz_offset_s=off)
        except api.ApiUnsupported:
            found = api.find_sessions_by_scan(frm, to)
        for c in found:
            out.setdefault(c.id, c)
    for code in {t.tone for t in takes if t.tone is not None}:
        try:
            if code.is_db_id:
                if code.value not in out and (c := api.fetch_candidate(code.value)) is not None:
                    out[c.id] = c
            else:
                for c in api.find_sessions_by_temp_id(code.temp_id):
                    out.setdefault(c.id, c)
        except api.ApiError:
            continue       # brak jednego wpisu nie może zatrzymać całej partii
    return list(out.values())


def _shot_scorer(take: matching.Take, timelines: dict[int, list[float]]) -> dict[int, float]:
    return audio_sync.shot_alignment_scores(audio_source(take.path), take.t0, timelines)


def _locked_assignment(take: matching.Take) -> matching.Assignment | None:
    rec = assignment_store.load(take.path)
    if rec is None or not rec.locked:
        return None
    reasons = rec.reasons or (("decyzja ręczna",) if rec.source == "manual" else ())
    return matching.Assignment(take, rec.entry_id, rec.state, rec.score,
                               reasons=tuple(reasons) + ("zapisane wcześniej",),
                               locked=True, source=rec.source)


def match_folders(dirs: list[str | Path], *, recursive: bool = False, save: bool = True,
                  tz=None, progress=None,
                  entries: list[api.SessionCandidate] | None = None) -> matching.MatchReport:
    """Automatyczne wiązanie wszystkich nagrań z katalogów (karta DJI, telefon, …).

    1. pliki → ujęcia (`matching.group_by_stem`; LRF/THM obok MP4 = to samo ujęcie),
    2. sygnały per ujęcie (`extract_take`: start, długość, T0, ID-tone z pozycją),
    3. kandydaci z API (`fetch_entries_for_takes`) — albo gotowa lista `entries`,
    4. `matching.match_takes` (offsety z kotwic, punkty, odcisk, przydział 1:1 per
       urządzenie), zapisane wcześniej `picked`/ręczne przypisania są nietykalne,
    5. `save` → wynik do plików bocznych (`assignment_store`); `picked` blokuje się.
    `progress(i, n, path)` — opcjonalny postęp ekstrakcji (najwolniejszy etap).
    """
    tz = tz or session_match.local_tz()
    paths: list[Path] = []
    for d in dirs:
        root = Path(d)
        it = root.rglob("*") if recursive else root.glob("*")
        if not root.is_dir():
            raise PipelineError(f"To nie jest katalog: {root}")
        paths.extend(p for p in it if p.is_file() and not p.name.startswith(".")
                     and p.suffix.lower() in VIDEO_SUFFIXES | {".lrf", ".thm"})
    groups = matching.group_by_stem(paths)
    takes: list[matching.Take] = []
    locked: dict[str, matching.Assignment] = {}
    for i, (main, files) in enumerate(groups):
        if progress:
            progress(i, len(groups), main)
        rec = assignment_store.load(main)
        if rec is not None and rec.locked:
            # zablokowane — bez analizy audio, tylko czas z nazwy/metadanych
            take = replace(take_for_video(main, tz=tz), files=files)
            locked[take.key] = _locked_assignment(take)
        else:
            take = extract_take(main, files, tz=tz)
        takes.append(take)
    if entries is None:
        entries = fetch_entries_for_takes([t for t in takes if t.key not in locked], tz=tz)
    report = matching.match_takes(takes, entries, tz=tz, shot_scorer=_shot_scorer,
                                  locked=locked)
    if save:
        for a in report.assignments:
            if not a.locked:
                assignment_store.save(a.take.path, assignment_store.StoredAssignment(
                    a.entry_id, a.state, "auto", a.score, a.reasons))
    return report
