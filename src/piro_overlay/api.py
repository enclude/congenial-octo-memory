"""Integracja z API kalkulatora Piro.

GET https://piro-kalkulator.pifpaf.fun/api.php?id=<id>

Oś czasu strzałów znajduje się w polu `data.opis` (ten sam format co tekst wklejany
ręcznie), pozostałe pola wzbogacają nagłówek i podsumowanie nakładki.
"""

from __future__ import annotations

from typing import Any

import requests

from .models import Session
from .parser import parse_timeline

API_BASE_URL = "https://piro-kalkulator.pifpaf.fun/api.php"
DEFAULT_TIMEOUT = 15


class ApiError(RuntimeError):
    """Błąd komunikacji z API kalkulatora lub niepoprawna odpowiedź."""


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

    try:
        shots = parse_timeline(opis)
    except ValueError as exc:
        raise ApiError(f"Pole 'opis' nie zawiera poprawnej osi czasu: {exc}") from exc

    czasy = data.get("czasy") or {}
    return Session(
        shots=shots,
        nazwa_toru=data.get("nazwa_toru") or None,
        uczestnik=data.get("uczestnik") or None,
        liczba_strzalow=data.get("liczba_strzalow"),
        czas_bazowy=czasy.get("czas_bazowy"),
        suma_kar=czasy.get("suma_kar"),
        czas_koncowy=czasy.get("czas_koncowy"),
        hit_factor=data.get("hit_factor"),
    )
