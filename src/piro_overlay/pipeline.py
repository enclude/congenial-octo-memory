"""Wspólna orkiestracja przepływu: sesja → T0 → przycięcie.

Rdzeń logiki dzielony przez CLI (`cli.py`) i backend WWW (`web/`) — bez Qt,
bez argparse i bez print. Komunikaty dla użytkownika (printy CLI, odpowiedzi
HTTP) należą do warstw wejścia; tu tylko wartości i `PipelineError`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
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


def resolve_id_tone(code: audio_sync.IdToneCode, video: str | Path, *,
                    t0: float | None = None,
                    info: ffmpeg.VideoInfo | None = None) -> IdToneResult:
    """Zamienia ramkę ID-tone na ID wpisu w bazie kalkulatora.

    Kanał 0 → wartość JEST tym ID (bez zapytań). Kanał 1-9 → kod tymczasowy:
    pytamy kalkulator o wpisy z tym `temp_id`; jeden kandydat = trafienie,
    kilku (licznik kodów zawija się po 9999) = rozstrzyga dopasowanie po czasie
    nagrania i odcisku strzałów, jak przy nieczytelnym ID. Bez rozstrzygnięcia
    `session_id` jest None — ZGADYWANIE jest gorsze od braku ID (nakładka
    pokazałaby cudzą sesję).
    """
    if code.is_db_id:
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
    if len(cands) == 1:
        return IdToneResult(code, cands[0].id, f"{code.label} → #{cands[0].id}")
    result = _match_candidates(video, cands, t0=t0, info=info)
    if result.picked is None:
        return IdToneResult(code, None,
                            f"kod tymczasowy {code.label}: {len(cands)} wpisów w bazie, "
                            "czas nagrania nie rozstrzyga — wybierz ID ręcznie", result)
    picked = result.picked.candidate
    return IdToneResult(code, picked.id, f"{code.label} → #{picked.id}", result)


def detect_id(video: str | Path, *, t0: float | None = None,
              info: ffmpeg.VideoInfo | None = None) -> IdToneResult | None:
    """`detect_id_tone` + `resolve_id_tone` — jedno wejście dla GUI/WWW/wsadu.
    None = w audio nie ma czytelnej ramki ID."""
    code = detect_id_tone(video)
    return None if code is None else resolve_id_tone(code, video, t0=t0, info=info)


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
    """Ocena gotowej listy kandydatów względem nagrania (czas + odcisk strzałów).

    Wspólne dla dopasowania po oknie czasu (`find_session_by_time`) i dla
    rozstrzygania kilku wpisów o tym samym kodzie tymczasowym (`resolve_id_tone`).
    """
    info = info or ffmpeg.probe(video)
    rec = session_match.recording_start(video, info.duration, info.creation_time)
    if rec is None:
        return session_match.MatchResult(None, (), None)
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
