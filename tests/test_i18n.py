"""Testy tłumaczeń: kompletność kluczy PL/EN oraz łańcuch fallbacku."""

from __future__ import annotations

from piro_overlay import i18n
from piro_overlay.i18n import Translator, available_keys, get_translator
from piro_overlay.models import Lang


def test_all_keys_have_both_languages():
    # Komentarz w i18n.py obiecuje: „każdy klucz musi mieć wpis dla obu języków".
    missing = {
        key: [lang.value for lang in Lang if lang not in entry]
        for key, entry in i18n._STRINGS.items()
        if any(lang not in entry for lang in Lang)
    }
    assert not missing, f"Klucze bez kompletu języków: {missing}"


def test_translator_returns_selected_language():
    assert Translator(Lang.PL).t("shot") == "Strzał"
    assert Translator(Lang.EN).t("shot") == "Shot"


def test_translator_unknown_key_is_marked():
    assert Translator(Lang.PL).t("no_such_key") == "[no_such_key]"


def test_translator_fallback_to_english(monkeypatch):
    # Klucz tylko po angielsku → wybrany PL spada na EN.
    monkeypatch.setitem(i18n._STRINGS, "only_en", {Lang.EN: "English only"})
    assert Translator(Lang.PL).t("only_en") == "English only"


def test_translator_is_callable():
    tr = get_translator(Lang.EN)
    assert tr("done") == "Done"


def test_available_keys_matches_strings():
    assert set(available_keys()) == set(i18n._STRINGS.keys())
