"""Modele danych dla Piro Overlay.

Zawiera czyste dataclassy bez zależności od GUI ani FFmpeg, dzięki czemu mogą
być reużyte zarówno przez warstwę desktop (PySide6), CLI, jak i przyszły backend WWW.
"""

from __future__ import annotations

import json
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
    start_banner_border_enabled: bool = True
    start_banner_border_color: tuple[int, int, int, int] = (255, 196, 0, 220)
    start_banner_border_width: int = 3

    def __post_init__(self) -> None:
        if self.position not in ANCHOR_POSITIONS:
            raise ValueError(
                f"position musi być jednym z {ANCHOR_POSITIONS}, otrzymano {self.position!r}"
            )

    def to_dict(self) -> dict:
        """Serializuje styl do słownika gotowego do zapisu JSON."""
        def c(t):
            return list(t)
        return {
            "lang": self.lang.value,
            "scale": self.scale,
            "position": self.position,
            "offset_x": self.offset_x,
            "offset_y": self.offset_y,
            "bg_color": c(self.bg_color),
            "corner_radius": self.corner_radius,
            "border_enabled": self.border_enabled,
            "border_color": c(self.border_color),
            "border_width": self.border_width,
            "text_color": c(self.text_color),
            "accent_color": c(self.accent_color),
            "start_banner_duration": self.start_banner_duration,
            "start_banner_scale": self.start_banner_scale,
            "start_banner_bg_color": c(self.start_banner_bg_color),
            "start_banner_text_color": c(self.start_banner_text_color),
            "start_banner_border_enabled": self.start_banner_border_enabled,
            "start_banner_border_color": c(self.start_banner_border_color),
            "start_banner_border_width": self.start_banner_border_width,
        }

    def to_json(self, path) -> None:
        """Zapisuje styl do pliku JSON."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @staticmethod
    def from_dict(d: dict) -> "OverlayStyle":
        """Wczytuje styl ze słownika (np. załadowanego z JSON)."""
        def color(key, default):
            v = d.get(key, default)
            return tuple(int(x) for x in v) if isinstance(v, (list, tuple)) else tuple(default)

        return OverlayStyle(
            lang=Lang(d.get("lang", Lang.PL.value)),
            scale=float(d.get("scale", 1.0)),
            position=d.get("position", "bottom-left"),
            offset_x=int(d.get("offset_x", 32)),
            offset_y=int(d.get("offset_y", 32)),
            bg_color=color("bg_color", (0, 0, 0, 170)),
            corner_radius=int(d.get("corner_radius", 18)),
            border_enabled=bool(d.get("border_enabled", True)),
            border_color=color("border_color", (255, 255, 255, 220)),
            border_width=int(d.get("border_width", 3)),
            text_color=color("text_color", (255, 255, 255, 255)),
            accent_color=color("accent_color", (255, 196, 0, 255)),
            start_banner_duration=float(d.get("start_banner_duration", 1.0)),
            start_banner_scale=float(d.get("start_banner_scale", 1.0)),
            start_banner_bg_color=color("start_banner_bg_color", (0, 0, 0, 200)),
            start_banner_text_color=color("start_banner_text_color", (255, 196, 0, 255)),
            start_banner_border_enabled=bool(d.get("start_banner_border_enabled", True)),
            start_banner_border_color=color("start_banner_border_color", (255, 196, 0, 220)),
            start_banner_border_width=int(d.get("start_banner_border_width", 3)),
        )

    @staticmethod
    def from_json(path) -> "OverlayStyle":
        """Wczytuje styl z pliku JSON."""
        with open(path, encoding="utf-8") as f:
            return OverlayStyle.from_dict(json.load(f))
