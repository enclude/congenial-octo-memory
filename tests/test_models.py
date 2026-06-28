"""Testy modelu OverlayStyle — głównie serializacja i normalizacja pól."""

import pytest

from piro_overlay.models import Lang, OverlayStyle, Session, Shot


def test_lang_normalized_from_string():
    # GUI (QComboBox.currentData) potrafi podać czysty str — Lang(str,Enum) gubi
    # typ w round-tripie QVariant. OverlayStyle musi to znormalizować do Lang.
    style = OverlayStyle(lang="pl")
    assert style.lang is Lang.PL
    style_en = OverlayStyle(lang="en")
    assert style_en.lang is Lang.EN


def test_to_dict_works_with_string_lang():
    # Regresja: wcześniej to_dict() robił self.lang.value i wybuchał, gdy lang był
    # str → CICHO blokowało save_last_style / save_file_settings (last_style.json = 0 B).
    style = OverlayStyle(lang="pl")
    d = style.to_dict()            # nie może rzucić
    assert d["lang"] == "pl"


def test_style_dict_roundtrip_preserves_lang():
    style = OverlayStyle(lang="en", scale=1.5, show_running_clock=True)
    restored = OverlayStyle.from_dict(style.to_dict())
    assert restored.lang is Lang.EN
    assert restored.scale == 1.5
    assert restored.show_running_clock is True


def test_invalid_lang_raises():
    with pytest.raises(ValueError):
        OverlayStyle(lang="xx")


def test_session_dict_roundtrip():
    # Serializacja sesji jest potrzebna do zapisu/odczytu kolejki renderów (AppData).
    sess = Session(
        shots=[Shot(numer=1, czas=1.0, split=None),
               Shot(numer=2, czas=2.5, split=1.5)],
        nazwa_toru="Tor A", uczestnik="Jan", liczba_strzalow=2,
        czas_bazowy=2.5, suma_kar=0.0, czas_koncowy=2.5, hit_factor=4.2)
    restored = Session.from_dict(sess.to_dict())
    assert [(s.numer, s.czas, s.split) for s in restored.shots] == \
           [(1, 1.0, None), (2, 2.5, 1.5)]
    assert restored.nazwa_toru == "Tor A"
    assert restored.uczestnik == "Jan"
    assert restored.hit_factor == 4.2


def test_session_dict_roundtrip_minimal():
    sess = Session(shots=[Shot(numer=1, czas=0.8)])
    restored = Session.from_dict(sess.to_dict())
    assert restored.shots[0].split is None
    assert restored.nazwa_toru is None
