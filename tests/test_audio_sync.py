"""Testy czystych funkcji audio_sync (bez FFmpeg)."""

from __future__ import annotations

from piro_overlay.audio_sync import resolve_t0
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
