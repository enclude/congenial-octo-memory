"""Integracja z API kalkulatora Piro.

GET https://piro-kalkulator.pifpaf.fun/api.php?id=<id>
GET https://piro-kalkulator.pifpaf.fun/api.php?from=<unix UTC>&to=<unix UTC>&tz_offset=<s>

Oś czasu strzałów znajduje się w polu `data.opis` (ten sam format co tekst wklejany
ręcznie), pozostałe pola wzbogacają nagłówek i podsumowanie nakładki.

Tryb listy (okno czasu) służy do dopasowania nagrania do sesji, gdy sygnał ID
z audio jest nieczytelny — patrz `session_match.py`. Starszy serwer bez tego
trybu odpowiada 400 „Brak … parametru id" → `ApiUnsupported`, a
`find_sessions_by_scan` odtwarza tę listę z pojedynczych `?id=` (ID rosną razem
z `data_zapisu`, więc wystarczy wyszukiwanie binarne).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import requests

from .models import Session
from .parser import extract_start_delay, parse_timeline

API_BASE_URL = "https://piro-kalkulator.pifpaf.fun/api.php"
DEFAULT_TIMEOUT = 15


class ApiError(RuntimeError):
    """Błąd komunikacji z API kalkulatora lub niepoprawna odpowiedź."""


class ApiUnsupported(ApiError):
    """Serwer API nie zna żądanego trybu (stara wersja kalkulatora)."""


@dataclass(frozen=True)
class SessionCandidate:
    """Skrót wpisu z bazy kalkulatora do dopasowania po czasie (bez osi strzałów)."""
    id: int
    data_zapisu: datetime            # UTC (SQLite CURRENT_TIMESTAMP), aware
    nazwa_toru: str = ""
    uczestnik: str = ""
    liczba_strzalow: int = 0
    czas_bazowy: float = 0.0
    timer_sn: str = ""
    timer_sess_id: int = 0           # start sesji NA TIMERZE, unixtime w czasie lokalnym; 0 = wpis ręczny
    opis: str = ""                   # surowa oś czasu (do odcisku strzałów w session_match)


def parse_data_zapisu(text: str) -> datetime:
    """`"2026-08-12 17:52:12"` (UTC — SQLite CURRENT_TIMESTAMP) → aware datetime UTC."""
    return datetime.strptime(text.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def candidate_from_payload(data: dict[str, Any]) -> SessionCandidate:
    """Buduje `SessionCandidate` z `data` odpowiedzi `?id=` albo z elementu listy `?from=&to=`."""
    czasy = data.get("czasy") or {}
    czas_bazowy = data.get("czas_bazowy", czasy.get("czas_bazowy"))
    return SessionCandidate(
        id=int(data["id"]),
        data_zapisu=parse_data_zapisu(str(data["data_zapisu"])),
        nazwa_toru=str(data.get("nazwa_toru") or ""),
        uczestnik=str(data.get("uczestnik") or ""),
        liczba_strzalow=int(data.get("liczba_strzalow") or 0),
        czas_bazowy=float(czas_bazowy or 0.0),
        timer_sn=str(data.get("timer_sn") or ""),
        timer_sess_id=int(data.get("timer_sess_id") or 0),
        opis=str(data.get("opis") or ""),
    )


def _get_json(params: dict[str, Any], *, base_url: str, timeout: int) -> tuple[int, dict[str, Any]]:
    try:
        resp = requests.get(base_url, params=params, timeout=timeout)
    except requests.RequestException as exc:  # sieć, timeout, DNS itp.
        raise ApiError(f"Błąd połączenia z API: {exc}") from exc
    try:
        payload = resp.json()
    except ValueError as exc:
        raise ApiError(f"Odpowiedź API nie jest poprawnym JSON-em (HTTP {resp.status_code}).") from exc
    return resp.status_code, payload


def find_sessions(from_utc: datetime, to_utc: datetime, *, tz_offset_s: int,
                  base_url: str = API_BASE_URL,
                  timeout: int = DEFAULT_TIMEOUT) -> list[SessionCandidate]:
    """Lista wpisów z okna czasu `[from_utc, to_utc]` (tryb listy `api.php?from=&to=`).

    `tz_offset_s` = przesunięcie czasu lokalnego kamery/timera względem UTC (s) —
    serwer porównuje nim `timer_sess_id` (zegar lokalny timera) z oknem UTC.
    Podnosi `ApiUnsupported`, gdy serwer nie zna trybu listy.
    """
    params = {"from": int(from_utc.timestamp()), "to": int(to_utc.timestamp()),
              "tz_offset": int(tz_offset_s)}
    status, payload = _get_json(params, base_url=base_url, timeout=timeout)
    if not payload.get("ok"):
        message = str((payload.get("error") or {}).get("message") or "")
        # stary api.php ignoruje from/to i skarży się na brak `id`
        if status == 400 and '"id"' in message:
            raise ApiUnsupported("API kalkulatora nie obsługuje wyszukiwania po czasie.")
        raise ApiError(f"API zwróciło błąd (HTTP {status}): {message or 'ok=false'}")
    items = payload.get("data")
    if not isinstance(items, list):
        raise ApiError("Odpowiedź API w trybie listy nie zawiera tablicy `data`.")
    try:
        return [candidate_from_payload(it) for it in items]
    except (KeyError, ValueError, TypeError) as exc:
        raise ApiError(f"Niepoprawny element listy w odpowiedzi API: {exc}") from exc


def fetch_candidate(result_id: int, *, base_url: str = API_BASE_URL,
                    timeout: int = DEFAULT_TIMEOUT) -> SessionCandidate | None:
    """Pojedynczy wpis jako `SessionCandidate`; None dla 404 (brak/usunięty wpis)."""
    status, payload = _get_json({"id": result_id}, base_url=base_url, timeout=timeout)
    if status == 404 or (not payload.get("ok")
                         and (payload.get("error") or {}).get("code") == 404):
        return None
    if not payload.get("ok"):
        raise ApiError(f"API zwróciło błąd (HTTP {status}).")
    try:
        return candidate_from_payload(payload.get("data") or {})
    except (KeyError, ValueError, TypeError) as exc:
        raise ApiError(f"Niepoprawna odpowiedź API dla id={result_id}: {exc}") from exc


# Ile sąsiednich ID sprawdzamy, zanim uznamy dziurę po usuniętych wpisach za koniec bazy.
_SCAN_GAP = 8
_SCAN_MAX_REQUESTS = 150


def find_sessions_by_scan(from_utc: datetime, to_utc: datetime, *,
                          fetch: Callable[[int], SessionCandidate | None] = fetch_candidate,
                          hint_id: int | None = None) -> list[SessionCandidate]:
    """Awaryjny odpowiednik `find_sessions` dla serwera bez trybu listy.

    Wyszukiwanie binarne po ID: wpisy powstają w kolejności zapisu, więc
    `data_zapisu` rośnie razem z `id` (AUTOINCREMENT; usunięte ID nie wracają do
    puli). Widzi tylko `data_zapisu` — wpisy wysłane hurtowo z cache timera po
    czasie strzelania nie zostaną tu dopasowane (potrzebny `timer_sess_id`
    z trybu listy). `hint_id` (np. ostatnio użyte ID) skraca szukanie końca bazy.
    """
    budget = [_SCAN_MAX_REQUESTS]
    cache: dict[int, SessionCandidate | None] = {}

    def get(i: int) -> SessionCandidate | None:
        if i not in cache:
            if budget[0] <= 0:
                raise ApiError("Przekroczono limit zapytań przy skanowaniu ID w API.")
            budget[0] -= 1
            cache[i] = fetch(i)
        return cache[i]

    def probe(i: int) -> SessionCandidate | None:
        """Najbliższy istniejący wpis o ID >= i (dziury po usuniętych), None = koniec bazy."""
        for k in range(i, i + _SCAN_GAP):
            if (c := get(k)) is not None:
                return c
        return None

    # 1. górna granica: podwajaj od podpowiedzi, aż trafisz w koniec bazy
    hi = max(hint_id or 0, 1)
    while probe(hi) is not None:
        hi *= 2
    # 2. binarnie w [0, hi): ostatnie ID z data_zapisu <= to_utc (0 = żadne).
    # Dolna granica NIE może zostać z kroku 1 — podpowiedź bywa wyżej niż okno.
    lo = 0
    while hi - lo > 1:
        mid = (lo + hi) // 2
        c = probe(mid)
        if c is None or c.data_zapisu > to_utc:
            hi = mid
        else:
            lo = mid
    # 3. w dół od `lo`, dopóki wpisy są w oknie (małe okna → kilka żądań)
    out: list[SessionCandidate] = []
    i = lo
    misses = 0
    while i >= 1 and misses < _SCAN_GAP:
        c = get(i)
        i -= 1
        if c is None:
            misses += 1
            continue
        misses = 0
        if c.data_zapisu > to_utc:
            continue
        if c.data_zapisu < from_utc:
            break
        out.append(c)
    out.reverse()
    return out


def fetch_session(result_id: int, *, base_url: str = API_BASE_URL,
                  timeout: int = DEFAULT_TIMEOUT) -> Session:
    """Pobiera wynik po ID i mapuje go na `Session`.

    Podnosi `ApiError` przy błędzie sieci, statusie != 200, `ok != true`
    lub gdy pole `opis` nie zawiera poprawnej osi czasu.
    """
    if result_id <= 0:
        raise ApiError("ID musi być dodatnią liczbą całkowitą.")

    try:
        resp = requests.get(base_url, params={"id": result_id}, timeout=timeout)
    except requests.RequestException as exc:  # sieć, timeout, DNS itp.
        raise ApiError(f"Błąd połączenia z API: {exc}") from exc

    if resp.status_code != 200:
        raise ApiError(f"API zwróciło status HTTP {resp.status_code}.")

    try:
        payload = resp.json()
    except ValueError as exc:
        raise ApiError("Odpowiedź API nie jest poprawnym JSON-em.") from exc

    return session_from_payload(payload)


def session_from_payload(payload: dict[str, Any]) -> Session:
    """Mapuje surową odpowiedź API na `Session` (wydzielone dla testowalności)."""
    if not payload.get("ok"):
        raise ApiError("API zwróciło ok=false lub brak pola ok.")

    data = payload.get("data") or {}
    opis = data.get("opis") or ""
    # Piro-kalkulator dokłada opcjonalnie "opoznienie startu Xs" przed listą
    # strzałów — odcinamy je, resztę parsujemy bez zmian (patrz parser.py).
    opis, start_delay = extract_start_delay(opis)

    try:
        shots = parse_timeline(opis)
    except ValueError as exc:
        raise ApiError(f"Pole 'opis' nie zawiera poprawnej osi czasu: {exc}") from exc

    czasy = data.get("czasy") or {}
    return Session(
        shots=shots,
        start_delay=start_delay,
        nazwa_toru=data.get("nazwa_toru") or None,
        uczestnik=data.get("uczestnik") or None,
        liczba_strzalow=data.get("liczba_strzalow"),
        czas_bazowy=czasy.get("czas_bazowy"),
        suma_kar=czasy.get("suma_kar"),
        czas_koncowy=czasy.get("czas_koncowy"),
        hit_factor=data.get("hit_factor"),
    )
