"""Testy wspólnej orkiestracji (pipeline) — bez FFmpeg i sieci."""

from __future__ import annotations

import pytest

from piro_overlay import pipeline
from piro_overlay.models import AnchorMode, Session, Shot


def test_build_session_from_timeline():
    session = pipeline.build_session("1: 1.0s | 2: 2.5s (+1.5s)", None)
    assert session is not None
    assert [s.czas for s in session.shots] == [1.0, 2.5]


def test_build_session_none_without_source():
    assert pipeline.build_session(None, None) is None
    assert pipeline.build_session("", None) is None


def test_compute_t0_start_signal_keeps_anchor():
    session = Session(shots=[Shot(1, 2.0)])
    assert pipeline.compute_t0(10.0, AnchorMode.START_SIGNAL, session) == 10.0


def test_compute_t0_first_shot_subtracts_offset():
    session = Session(shots=[Shot(1, 2.0)])
    assert pipeline.compute_t0(10.0, AnchorMode.FIRST_SHOT, session) == 8.0


def test_compute_t0_without_session_uses_zero_offset():
    assert pipeline.compute_t0(10.0, AnchorMode.FIRST_SHOT, None) == 10.0


def test_compute_trim_passthrough_without_auto():
    assert pipeline.compute_trim(None, None, 100.0, auto=False) == (None, None)
    assert pipeline.compute_trim(
        None, None, 100.0, auto=False, trim_start=2.0, trim_end=30.0) == (2.0, 30.0)


def test_compute_trim_auto_requires_t0():
    with pytest.raises(pipeline.PipelineError):
        pipeline.compute_trim(None, None, 100.0, auto=True)


def test_compute_trim_auto_window():
    start, end = pipeline.compute_trim(
        10.0, None, 200.0, auto=True, auto_window=75.0)
    assert start == 5.0            # t0 − lead_in
    assert end == 85.0             # t0 + auto_window


def test_compute_trim_auto_window_alone_implies_auto():
    # W CLI samo --auto-window włącza auto-przycięcie — pipeline zachowuje to samo.
    start, end = pipeline.compute_trim(
        10.0, None, 200.0, auto=False, auto_window=75.0)
    assert (start, end) == (5.0, 85.0)


def test_compute_trim_auto_uses_last_shot():
    session = Session(shots=[Shot(1, 1.0), Shot(2, 20.0, 19.0)])
    start, end = pipeline.compute_trim(10.0, session, 200.0, auto=True)
    assert start == 5.0
    assert end == 10.0 + 20.0 + 5.0  # t0 + ostatni strzał + tail


def test_compute_trim_auto_without_shots_uses_default_window():
    start, end = pipeline.compute_trim(10.0, None, None, auto=True)
    assert start == 5.0
    assert end == 10.0 + pipeline.DEFAULT_AUTO_WINDOW


def test_compute_trim_end_clamped_to_duration():
    _, end = pipeline.compute_trim(
        10.0, None, 30.0, auto=True, auto_window=75.0)
    assert end == 30.0


def test_compute_trim_lead_in_clamped_to_zero():
    start, _ = pipeline.compute_trim(2.0, None, 100.0, auto=True, auto_window=10.0)
    assert start == 0.0
