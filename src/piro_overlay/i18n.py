"""Tłumaczenia etykiet (nakładka + GUI).

Teksty pojawiają się w dwóch miejscach (wypalana nakładka oraz interfejs GUI),
więc zamiast surowych słowników używamy klasy `Translator` z jawnym fallbackiem:
brakujący klucz w wybranym języku spada na angielski, a w ostateczności zwraca
`[klucz]` — dzięki czemu luka jest natychmiast widoczna w UI/na nakładce,
zamiast wywalać render wyjątkiem KeyError.
"""

from __future__ import annotations

from .models import Lang

# Pojedyncze źródło prawdy dla wszystkich etykiet.
# Każdy klucz musi mieć wpis dla obu języków; testy to weryfikują.
_STRINGS: dict[str, dict[Lang, str]] = {
    # --- nakładka ---
    "shot": {Lang.PL: "Strzał", Lang.EN: "Shot"},
    "split": {Lang.PL: "Split", Lang.EN: "Split"},
    "of": {Lang.PL: "z", Lang.EN: "of"},
    "start": {Lang.PL: "START", Lang.EN: "START"},
    "first_shot": {Lang.PL: "Pierwszy strzał", Lang.EN: "First shot"},
    "base_time": {Lang.PL: "Czas bazowy", Lang.EN: "Base time"},
    "penalties": {Lang.PL: "Suma kar", Lang.EN: "Penalties"},
    "final_time": {Lang.PL: "Czas końcowy", Lang.EN: "Final time"},
    "hit_factor": {Lang.PL: "Hit Factor", Lang.EN: "Hit Factor"},
    "summary": {Lang.PL: "Podsumowanie", Lang.EN: "Summary"},
    # dopełniacz po liczbie w nakładce metadanych ("9 strzałów" / "9 shots")
    "shots_label": {Lang.PL: "strzałów", Lang.EN: "shots"},
    # --- GUI ---
    "app_title": {Lang.PL: "Piro Overlay", Lang.EN: "Piro Overlay"},
    "choose_video": {Lang.PL: "Wybierz wideo", Lang.EN: "Choose video"},
    "source_text": {Lang.PL: "Tekst", Lang.EN: "Text"},
    "source_id": {Lang.PL: "ID (API)", Lang.EN: "ID (API)"},
    "fetch": {Lang.PL: "Pobierz", Lang.EN: "Fetch"},
    "render": {Lang.PL: "Renderuj", Lang.EN: "Render"},
    "anchor_start_signal": {Lang.PL: "Sygnał startu", Lang.EN: "Start signal"},
    "anchor_first_shot": {Lang.PL: "Pierwszy strzał", Lang.EN: "First shot"},
    "offset": {Lang.PL: "Korekta T0", Lang.EN: "T0 offset"},
    "appearance": {Lang.PL: "Wygląd nakładki", Lang.EN: "Overlay appearance"},
    "language": {Lang.PL: "Język", Lang.EN: "Language"},
    "output": {Lang.PL: "Plik wyjściowy", Lang.EN: "Output file"},
    "done": {Lang.PL: "Gotowe", Lang.EN: "Done"},
    # --- pasek akcji (GUI) ---
    "act_open_video": {Lang.PL: "Otwórz wideo…", Lang.EN: "Open video…"},
    "act_fetch_api": {Lang.PL: "Pobierz z API", Lang.EN: "Fetch from API"},
    "act_detect_start": {Lang.PL: "Wykryj sygnał startu", Lang.EN: "Detect start signal"},
    "act_auto_trim": {Lang.PL: "Auto-przycięcie", Lang.EN: "Auto trim"},
    "act_add_queue": {Lang.PL: "Dodaj do kolejki", Lang.EN: "Add to queue"},
    "act_queue": {Lang.PL: "Kolejka…", Lang.EN: "Queue…"},
    "act_batch": {Lang.PL: "Wsadowo…", Lang.EN: "Batch…"},
    "act_cancel": {Lang.PL: "Zatrzymaj", Lang.EN: "Stop"},
    "act_theme": {Lang.PL: "Motyw", Lang.EN: "Theme"},
    "theme_dark": {Lang.PL: "ciemny", Lang.EN: "dark"},
    "theme_light": {Lang.PL: "jasny", Lang.EN: "light"},
    # --- sekcje inspektora (GUI) ---
    "sec_input": {Lang.PL: "Wejście", Lang.EN: "Input"},
    "sec_sync": {Lang.PL: "Synchronizacja i przycięcie", Lang.EN: "Sync and trim"},
    "sec_colors": {Lang.PL: "Kolory", Lang.EN: "Colours"},
    "sec_meta": {Lang.PL: "Nakładka metadanych", Lang.EN: "Metadata overlay"},
    "sec_clock": {Lang.PL: "Zegar", Lang.EN: "Clock"},
    "sec_banner": {Lang.PL: "Plansza START", Lang.EN: "START banner"},
    "sec_output": {Lang.PL: "Wyjście", Lang.EN: "Output"},
    # --- pola ścieżek i walidacja osi czasu (GUI, iteracja III) ---
    "path_video_placeholder": {Lang.PL: "Przeciągnij plik wideo…",
                               Lang.EN: "Drop a video file…"},
    "path_output_placeholder": {Lang.PL: "Plik wynikowy…", Lang.EN: "Output file…"},
    "tip_choose_video": {Lang.PL: "Wybierz plik wideo (Ctrl+O)",
                         Lang.EN: "Choose a video file (Ctrl+O)"},
    "tip_choose_output": {Lang.PL: "Wybierz plik wyjściowy",
                          Lang.EN: "Choose the output file"},
    "timeline_shots": {Lang.PL: "strzałów", Lang.EN: "shots"},
    "timeline_invalid": {Lang.PL: "Nie rozpoznano osi czasu",
                         Lang.EN: "Cannot parse the timeline"},
    "timeline_empty": {Lang.PL: "brak strzałów", Lang.EN: "no shots"},
    # --- wartości list: pozycja nakładki (klucz techniczny zostaje bez zmian) ---
    "pos_top_left": {Lang.PL: "Lewy górny", Lang.EN: "Top left"},
    "pos_top_center": {Lang.PL: "Górny środek", Lang.EN: "Top centre"},
    "pos_top_right": {Lang.PL: "Prawy górny", Lang.EN: "Top right"},
    "pos_bottom_left": {Lang.PL: "Lewy dolny", Lang.EN: "Bottom left"},
    "pos_bottom_center": {Lang.PL: "Dolny środek", Lang.EN: "Bottom centre"},
    "pos_bottom_right": {Lang.PL: "Prawy dolny", Lang.EN: "Bottom right"},
    "pos_clock_auto": {Lang.PL: "Nad nakładką (auto)", Lang.EN: "Above the overlay (auto)"},
}

_FALLBACK_LANG = Lang.EN


class Translator:
    """Tłumacz związany z konkretnym językiem, z łańcuchem fallbacku."""

    def __init__(self, lang: Lang = Lang.PL) -> None:
        self.lang = Lang(lang)

    def t(self, key: str) -> str:
        """Zwraca etykietę dla klucza; fallback: wybrany język → EN → [klucz]."""
        entry = _STRINGS.get(key)
        if entry is None:
            return f"[{key}]"
        if self.lang in entry:
            return entry[self.lang]
        if _FALLBACK_LANG in entry:
            return entry[_FALLBACK_LANG]
        return f"[{key}]"

    # Skrót: translator jest wywoływalny jak funkcja — tr("shot").
    __call__ = t


def get_translator(lang: Lang = Lang.PL) -> Translator:
    """Fabryka tłumacza dla danego języka."""
    return Translator(lang)


def available_keys() -> list[str]:
    """Lista wszystkich kluczy — używane w testach kompletności tłumaczeń."""
    return list(_STRINGS.keys())
