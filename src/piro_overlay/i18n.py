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
