"""Modele danych dla Piro Overlay.

Zawiera czyste dataclassy bez zależności od GUI ani FFmpeg, dzięki czemu mogą
być reużyte zarówno przez warstwę desktop (PySide6), CLI, jak i przyszły backend WWW.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AnchorMode(str, Enum):
    """Sposób interpretacji wykrytego punktu odniesienia na osi czasu wideo.

    START_SIGNAL — wykryty punkt to sygnał startu (buzzer); T0 = punkt.
    FIRST_SHOT   — wykryty punkt to pierwszy strzał; T0 = punkt − czas pierwszego strzału.
    """

    START_SIGNAL = "start_signal"
    FIRST_SHOT = "first_shot"


class Lang(str, Enum):
    """Język etykiet wypalanych na nakładce oraz w GUI."""

    PL = "pl"
    EN = "en"


@dataclass(frozen=True)
class Shot:
    """Pojedynczy strzał z osi czasu.

    czas  — czas od startu sesji (sygnału), w sekundach.
    split — przyrost względem poprzedniego strzału (None dla pierwszego strzału).
    """

    numer: int
    czas: float
    split: float | None = None


@dataclass
class Session:
    """Komplet danych sesji: oś czasu strzałów + opcjonalne metadane z kalkulatora."""

    shots: list[Shot]
    nazwa_toru: str | None = None
    uczestnik: str | None = None
    liczba_strzalow: int | None = None
    czas_bazowy: float | None = None
    suma_kar: float | None = None
    czas_koncowy: float | None = None
    hit_factor: float | None = None

    @property
    def total_shots(self) -> int:
        """Łączna liczba strzałów — z metadanych API lub z długości osi czasu."""
        return self.liczba_strzalow or len(self.shots)

    @property
    def base_time(self) -> float | None:
        """Czas bazowy — z metadanych API lub czas ostatniego strzału."""
        if self.czas_bazowy is not None:
            return self.czas_bazowy
        return self.shots[-1].czas if self.shots else None


# Predefiniowane kotwice (rogi/krawędzie) pozycjonowania panelu.
ANCHOR_POSITIONS = (
    "top-left",
    "top-center",
    "top-right",
    "bottom-left",
    "bottom-center",
    "bottom-right",
)


@dataclass
class OverlayStyle:
    """Konfiguracja wyglądu nakładki — w pełni edytowalna z GUI.

    Kolory jako krotki RGBA (0–255). `scale` skaluje cały panel względem
    wysokości wideo, dzięki czemu nakładka wygląda spójnie niezależnie od
    rozdzielczości materiału.
    """

    # Język etykiet
    lang: Lang = Lang.PL

    # Rozmiar / skala (1.0 = bazowy rozmiar dobrany do wysokości wideo)
    scale: float = 1.0

    # Pozycja: jedna z ANCHOR_POSITIONS + dokładny offset w pikselach
    position: str = "bottom-left"
    offset_x: int = 32
    offset_y: int = 32

    # Tło panelu (RGBA — ostatni kanał to przezroczystość)
    bg_color: tuple[int, int, int, int] = (0, 0, 0, 170)
    corner_radius: int = 18

    # Obramowanie
    border_enabled: bool = True
    border_color: tuple[int, int, int, int] = (255, 255, 255, 220)
    border_width: int = 3

    # Kolory napisów
    text_color: tuple[int, int, int, int] = (255, 255, 255, 255)
    accent_color: tuple[int, int, int, int] = (255, 196, 0, 255)

    # Plansza START
    start_banner_duration: float = 1.0
    start_banner_scale: float = 1.0
    start_banner_bg_color: tuple[int, int, int, int] = (0, 0, 0, 200)
    start_banner_text_color: tuple[int, int, int, int] = (255, 196, 0, 255)

    def __post_init__(self) -> None:
        if self.position not in ANCHOR_POSITIONS:
            raise ValueError(
                f"position musi być jednym z {ANCHOR_POSITIONS}, otrzymano {self.position!r}"
            )
