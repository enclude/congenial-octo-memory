"""Testy audio_sync: czyste funkcje + detekcja bzyczka end-to-end (FFmpeg)."""

from __future__ import annotations

import numpy as np

from piro_overlay.audio_sync import _impact_ring, detect_dji_start, resolve_t0
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


def test_impact_ring_field_profiles():
    # Liczby z realnego nagrania DJI (sesja 2026-08-12, plik _0035): kling
    # zrzutu zamka (spadek 12×) vs bzyczek timera (płaska obwiednia, wahania ~5×).
    assert _impact_ring(np.array([4834.0, 383.0, 393.0]))
    assert not _impact_ring(np.array([266.0, 456.0, 228.0, 393.0, 328.0, 207.0,
                                      108.0, 112.0, 306.0, 440.0, 599.0, 532.0,
                                      273.0]))


def test_detect_dji_start_ignores_slide_drop_ring(impact_then_buzzer_video):
    # GUARD obwiedni (v0.42.0): zrzut zamka („Load and make ready" przed KAŻDYM
    # startem) dzwoni tonalnie >150 ms w paśmie buzzera i wygrywał jako
    # najwcześniejszy run — realny przypadek z sesji 2026-08-12 (T0 wykryte
    # o 6 s za wcześnie). Profil impulsu (szczyt ≥5× reszty) musi odpaść.
    t0 = detect_dji_start(impact_then_buzzer_video)
    assert t0 is not None
    assert abs(t0 - 2.0) < 0.15


def test_detect_dji_start_prefers_solid_run_over_marginal(marginal_then_buzzer_video):
    # SCORING (v0.42.0): wczesny kandydat ledwo nad progami (≤200 ms,
    # conc <0.85) przegrywa z późniejszym solidnym bzyczkiem (≥300 ms,
    # conc ≥0.9) — drugi bezpiecznik na artefakty, których obwiednia nie łapie.
    t0 = detect_dji_start(marginal_then_buzzer_video)
    assert t0 is not None
    assert abs(t0 - 2.0) < 0.15


def test_detect_dji_start_marginal_alone_still_wins(tmp_path):
    # Marginalny kandydat BEZ solidnego rywala nadal wygrywa — scoring nie
    # może zgubić krótkiego/zaszumionego bzyczka, gdy nic lepszego nie gra.
    from conftest import _make_tone_video
    video = _make_tone_video(
        tmp_path / "marginal_only.mp4",
        "if(between(t,0.5,0.65),0.35*sin(2*PI*4000*t)+0.186*sin(2*PI*1000*t),0)")
    t0 = detect_dji_start(video)
    assert t0 is not None
    assert abs(t0 - 0.5) < 0.15


def test_detect_dji_start_ignores_id_tones(id_tone_video):
    # GUARD poszerzenia pasma do 4800 Hz: tony protokołu ID (marker 5000 Hz,
    # cyfry 5200–7000 Hz) leżą tuż nad sufitem i NIE mogą być brane za bzyczek.
    assert detect_dji_start(id_tone_video) is None
