"""Modele danych dla Piro Overlay.

Zawiera czyste dataclassy bez zależności od GUI ani FFmpeg, dzięki czemu mogą
być reużyte zarówno przez warstwę desktop (PySide6), CLI, jak i przyszły backend WWW.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


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
    start_delay: float | None = None
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

    def to_dict(self) -> dict:
        """Serializuje sesję do słownika gotowego do zapisu JSON (np. kolejka renderów)."""
        return {
            "shots": [{"numer": s.numer, "czas": s.czas, "split": s.split}
                      for s in self.shots],
            "start_delay": self.start_delay,
            "nazwa_toru": self.nazwa_toru,
            "uczestnik": self.uczestnik,
            "liczba_strzalow": self.liczba_strzalow,
            "czas_bazowy": self.czas_bazowy,
            "suma_kar": self.suma_kar,
            "czas_koncowy": self.czas_koncowy,
            "hit_factor": self.hit_factor,
        }

    @staticmethod
    def from_dict(d: dict) -> "Session":
        """Odtwarza sesję ze słownika (odwrotność `to_dict`)."""
        shots = [
            Shot(numer=int(s["numer"]), czas=float(s["czas"]),
                 split=(None if s.get("split") is None else float(s["split"])))
            for s in d.get("shots", [])
        ]
        return Session(
            shots=shots,
            start_delay=d.get("start_delay"),
            nazwa_toru=d.get("nazwa_toru"),
            uczestnik=d.get("uczestnik"),
            liczba_strzalow=d.get("liczba_strzalow"),
            czas_bazowy=d.get("czas_bazowy"),
            suma_kar=d.get("suma_kar"),
            czas_koncowy=d.get("czas_koncowy"),
            hit_factor=d.get("hit_factor"),
        )


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

    # Styl panelu strzału: "classic" = pojedynczy panel z metadanymi,
    # "list" = przewijana lista ostatnich strzałów (pigułki, najnowszy na dole).
    panel_mode: str = "classic"
    list_max_rows: int = 5
    # W trybie listy aktywny wiersz pokazuje numer jako "x/yy" (postęp przebiegu).
    list_show_progress: bool = True

    # Osobna nakładka metadanych (nazwa toru / uczestnik — x strzałów),
    # pozycjonowana niezależnie od panelu strzału.
    show_meta_panel: bool = False
    meta_position: str = "top-left"
    meta_offset_x: int = 32
    meta_offset_y: int = 32

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

    # Płynący zegar od T0 (nad nakładką ze strzałami, widoczny od STARTU)
    show_running_clock: bool = False
    # Pozycja zegara: "auto" = nad nakładką ze strzałami; albo jeden z ANCHOR_POSITIONS
    # (wtedy zegar pozycjonowany niezależnie wg własnego offsetu).
    clock_position: str = "auto"
    clock_offset_x: int = 32
    clock_offset_y: int = 32

    # Plansza START
    start_banner_duration: float = 1.0
    start_banner_scale: float = 1.0
    start_banner_bg_color: tuple[int, int, int, int] = (0, 0, 0, 150)
    start_banner_text_color: tuple[int, int, int, int] = (255, 196, 0, 255)
    start_banner_border_enabled: bool = False
    start_banner_border_color: tuple[int, int, int, int] = (255, 196, 0, 220)
    start_banner_border_width: int = 3

    def __post_init__(self) -> None:
        # Normalizuj język do Lang. GUI podaje go przez QComboBox.currentData(),
        # a że Lang to (str, Enum), Qt gubi typ w round-tripie QVariant i zwraca
        # czysty str "pl"/"en". Bez tego `to_dict()` (self.lang.value) wybuchał i
        # CICHO blokował zapis stylu/ustawień pliku (last_style.json = 0 B!).
        if not isinstance(self.lang, Lang):
            self.lang = Lang(self.lang)
        if self.position not in ANCHOR_POSITIONS:
            raise ValueError(
                f"position musi być jednym z {ANCHOR_POSITIONS}, otrzymano {self.position!r}"
            )
        if self.clock_position not in ("auto", *ANCHOR_POSITIONS):
            raise ValueError(
                f"clock_position musi być 'auto' lub jednym z {ANCHOR_POSITIONS}, "
                f"otrzymano {self.clock_position!r}"
            )
        if self.panel_mode not in ("classic", "list"):
            raise ValueError(
                f"panel_mode musi być 'classic' lub 'list', otrzymano {self.panel_mode!r}"
            )
        if self.meta_position not in ANCHOR_POSITIONS:
            raise ValueError(
                f"meta_position musi być jednym z {ANCHOR_POSITIONS}, "
                f"otrzymano {self.meta_position!r}"
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
            "panel_mode": self.panel_mode,
            "list_max_rows": self.list_max_rows,
            "list_show_progress": self.list_show_progress,
            "show_meta_panel": self.show_meta_panel,
            "meta_position": self.meta_position,
            "meta_offset_x": self.meta_offset_x,
            "meta_offset_y": self.meta_offset_y,
            "bg_color": c(self.bg_color),
            "corner_radius": self.corner_radius,
            "border_enabled": self.border_enabled,
            "border_color": c(self.border_color),
            "border_width": self.border_width,
            "text_color": c(self.text_color),
            "accent_color": c(self.accent_color),
            "show_running_clock": self.show_running_clock,
            "clock_position": self.clock_position,
            "clock_offset_x": self.clock_offset_x,
            "clock_offset_y": self.clock_offset_y,
            "start_banner_duration": self.start_banner_duration,
            "start_banner_scale": self.start_banner_scale,
            "start_banner_bg_color": c(self.start_banner_bg_color),
            "start_banner_text_color": c(self.start_banner_text_color),
            "start_banner_border_enabled": self.start_banner_border_enabled,
            "start_banner_border_color": c(self.start_banner_border_color),
            "start_banner_border_width": self.start_banner_border_width,
        }

    def to_json(self, path: str | Path) -> None:
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
            panel_mode=d.get("panel_mode", "classic"),
            list_max_rows=int(d.get("list_max_rows", 5)),
            list_show_progress=bool(d.get("list_show_progress", True)),
            show_meta_panel=bool(d.get("show_meta_panel", False)),
            meta_position=d.get("meta_position", "top-left"),
            meta_offset_x=int(d.get("meta_offset_x", 32)),
            meta_offset_y=int(d.get("meta_offset_y", 32)),
            bg_color=color("bg_color", (0, 0, 0, 170)),
            corner_radius=int(d.get("corner_radius", 18)),
            border_enabled=bool(d.get("border_enabled", True)),
            border_color=color("border_color", (255, 255, 255, 220)),
            border_width=int(d.get("border_width", 3)),
            text_color=color("text_color", (255, 255, 255, 255)),
            accent_color=color("accent_color", (255, 196, 0, 255)),
            show_running_clock=bool(d.get("show_running_clock", False)),
            clock_position=d.get("clock_position", "auto"),
            clock_offset_x=int(d.get("clock_offset_x", 32)),
            clock_offset_y=int(d.get("clock_offset_y", 32)),
            start_banner_duration=float(d.get("start_banner_duration", 1.0)),
            start_banner_scale=float(d.get("start_banner_scale", 1.0)),
            start_banner_bg_color=color("start_banner_bg_color", (0, 0, 0, 150)),
            start_banner_text_color=color("start_banner_text_color", (255, 196, 0, 255)),
            start_banner_border_enabled=bool(d.get("start_banner_border_enabled", False)),
            start_banner_border_color=color("start_banner_border_color", (255, 196, 0, 220)),
            start_banner_border_width=int(d.get("start_banner_border_width", 3)),
        )

    @staticmethod
    def from_json(path: str | Path) -> "OverlayStyle":
        """Wczytuje styl z pliku JSON."""
        with open(path, encoding="utf-8") as f:
            return OverlayStyle.from_dict(json.load(f))
