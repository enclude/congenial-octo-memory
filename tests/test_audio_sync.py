"""Testy audio_sync: czyste funkcje + detekcja bzyczka end-to-end (FFmpeg)."""

from __future__ import annotations

from piro_overlay.audio_sync import detect_dji_start, resolve_t0
from piro_overlay.models import AnchorMode


def test_resolve_t0_start_signal_is_identity():
    # Kotwica = sygnał startu → T0 to dokładnie ta kotwica.
    assert resolve_t0(3.25, AnchorMode.START_SIGNAL, 2.81) == 3.25


def test_resolve_t0_first_shot_subtracts_offset():
    # Kotwica = pierwszy strzał → T0 cofnięty o czas pierwszego strzału.
    assert resolve_t0(10.0, AnchorMode.FIRST_SHOT, 2.5) == 7.5


def test_resolve_t0_first_shot_can_be_negative():
    # Sygnał startu przed początkiem nagrania — dozwolone (T0 < 0).
    assert resolve_t0(1.0, AnchorMode.FIRST_SHOT, 2.5) == -1.5


def test_detect_dji_start_typical_2700hz_buzzer(tiny_video):
    # Dotychczasowy „typowy" buzzer ~2.7 kHz — musi działać bez zmian.
    t0 = detect_dji_start(tiny_video)
    assert t0 is not None
    assert abs(t0 - 0.5) < 0.15


def test_detect_dji_start_4600hz_buzzer(tiny_video_4600hz):
    # Timer z sesji 2026-07-19 gra 4.6 kHz — dawny sufit pasma (4500 Hz)
    # odrzucał go głównym testem, a fallback łapał obce ciche piski.
    t0 = detect_dji_start(tiny_video_4600hz)
    assert t0 is not None
    assert abs(t0 - 0.5) < 0.15


def test_detect_dji_start_ignores_id_tones(id_tone_video):
    # GUARD poszerzenia pasma do 4800 Hz: tony protokołu ID (marker 5000 Hz,
    # cyfry 5200–7000 Hz) leżą tuż nad sufitem i NIE mogą być brane za bzyczek.
    assert detect_dji_start(id_tone_video) is None
