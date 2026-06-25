"""Parsowanie osi czasu strzałów.

Format (identyczny dla wklejanego tekstu i pola `opis` z API):

    "1: 2.81s | 2: 4.63s (+1.82s) | 3: 6.28s (+1.65s) | ..."

Każdy token: `numer: czas s (+split s)`. Split jest opcjonalny (brak przy 1. strzale).
"""

from __future__ import annotations

import re

from .models import Shot

# numer: czas s  (opcjonalnie:  (+split s) )
_TOKEN_RE = re.compile(
    r"""
    (?P<numer>\d+)        \s* : \s*
    (?P<czas>\d+(?:\.\d+)?) \s* s
    (?:                                   # opcjonalna grupa splitu
        \s* \( \s* \+ \s*
        (?P<split>\d+(?:\.\d+)?) \s* s \s* \)
    )?
    """,
    re.VERBOSE,
)


class TimelineParseError(ValueError):
    """Błąd parsowania osi czasu strzałów."""


def parse_timeline(text: str) -> list[Shot]:
    """Parsuje ciąg osi czasu na listę `Shot`.

    Podnosi `TimelineParseError`, gdy ciąg jest pusty, nie zawiera poprawnych
    tokenów, numeracja nie jest ciągła (1..N) albo czasy nie rosną.
    """
    if text is None or not text.strip():
        raise TimelineParseError("Pusta oś czasu strzałów.")

    shots: list[Shot] = []
    for raw in text.split("|"):
        token = raw.strip()
        if not token:
            continue
        m = _TOKEN_RE.fullmatch(token)
        if not m:
            raise TimelineParseError(f"Nie rozpoznano tokenu strzału: {token!r}")
        split = m.group("split")
        shots.append(
            Shot(
                numer=int(m.group("numer")),
                czas=float(m.group("czas")),
                split=float(split) if split is not None else None,
            )
        )

    if not shots:
        raise TimelineParseError("Nie znaleziono żadnego strzału w osi czasu.")

    _validate(shots)
    return shots


def _validate(shots: list[Shot]) -> None:
    for i, shot in enumerate(shots, start=1):
        if shot.numer != i:
            raise TimelineParseError(
                f"Numeracja strzałów nie jest ciągła: oczekiwano {i}, otrzymano {shot.numer}."
            )
        if i > 1 and shot.czas < shots[i - 2].czas:
            raise TimelineParseError(
                f"Czas strzału {shot.numer} ({shot.czas}s) jest mniejszy niż poprzedniego."
            )
