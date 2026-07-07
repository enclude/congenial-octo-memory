"""Testy czystych helperów CLI (bez FFmpeg i sieci)."""

from __future__ import annotations

import argparse

import pytest

from piro_overlay import cli
from piro_overlay.models import Session, Shot


def _args(**overrides) -> argparse.Namespace:
    """Namespace z domyślnymi wartościami jak w parserze CLI."""
    base = dict(
        id=None, timeline=None, t0=None,
        trim_start=None, trim_end=None,
        auto=False, auto_trim=False, auto_window=None,
        lead_in=5.0, tail=5.0,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def test_default_output_adds_suffix():
    assert cli._default_output("/x/clip.mp4").endswith("clip_PiRoOverlay.mp4")


def test_default_output_replaces_extension():
    assert cli._default_output("/x/clip.mov").endswith("clip_PiRoOverlay.mp4")


def test_build_session_from_timeline():
    session = cli._build_session(_args(timeline="1: 1.0s | 2: 2.5s (+1.5s)"))
    assert session is not None
    assert [s.czas for s in session.shots] == [1.0, 2.5]


def test_build_session_none_without_source():
    assert cli._build_session(_args()) is None


def test_compute_trim_passthrough_without_auto():
    # Bez trybów auto zwraca ręczne wartości bez zmian (także None).
    assert cli._compute_trim(_args(), t0=None, session=None, duration=100.0) == (None, None)
    args = _args(trim_start=2.0, trim_end=30.0)
    assert cli._compute_trim(args, t0=None, session=None, duration=100.0) == (2.0, 30.0)


def test_compute_trim_auto_requires_t0():
    with pytest.raises(SystemExit):
        cli._compute_trim(_args(auto=True), t0=None, session=None, duration=100.0)


def test_compute_trim_auto_window():
    start, end = cli._compute_trim(
        _args(auto=True, auto_window=75.0), t0=10.0, session=None, duration=200.0)
    assert start == 5.0            # t0 − lead_in
    assert end == 85.0             # t0 + auto_window


def test_compute_trim_auto_uses_last_shot():
    session = Session(shots=[Shot(1, 1.0), Shot(2, 20.0, 19.0)])
    start, end = cli._compute_trim(
        _args(auto=True), t0=10.0, session=session, duration=200.0)
    assert start == 5.0            # t0 − lead_in
    assert end == 10.0 + 20.0 + 5.0  # t0 + ostatni strzał + tail


def test_compute_trim_auto_without_shots_uses_default_window():
    start, end = cli._compute_trim(
        _args(auto=True), t0=10.0, session=None, duration=None)
    assert start == 5.0
    assert end == 10.0 + cli._DEFAULT_AUTO_WINDOW


def test_compute_trim_end_clamped_to_duration():
    _, end = cli._compute_trim(
        _args(auto=True, auto_window=75.0), t0=10.0, session=None, duration=30.0)
    assert end == 30.0
