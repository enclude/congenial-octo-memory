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


def test_apply_meta_override_replaces_api_values():
    base = Session(shots=[Shot(1, 1.0)], nazwa_toru="Z API", uczestnik="Ktoś")
    out = pipeline.apply_meta_override(base, "Tor 3", " Jaro ")
    assert (out.nazwa_toru, out.uczestnik) == ("Tor 3", "Jaro")
    assert out.shots == base.shots
    assert (base.nazwa_toru, base.uczestnik) == ("Z API", "Ktoś")  # bez mutacji


def test_apply_meta_override_blank_keeps_api_values():
    base = Session(shots=[Shot(1, 1.0)], nazwa_toru="Z API", uczestnik="Ktoś")
    assert pipeline.apply_meta_override(base, None, None) is base
    out = pipeline.apply_meta_override(base, "   ", "")
    assert (out.nazwa_toru, out.uczestnik) == ("Z API", "Ktoś")


def test_apply_meta_override_partial():
    base = Session(shots=[Shot(1, 1.0)], nazwa_toru="Z API", uczestnik="Ktoś")
    out = pipeline.apply_meta_override(base, None, "Jaro")
    assert (out.nazwa_toru, out.uczestnik) == ("Z API", "Jaro")


def test_build_session_from_timeline_with_override():
    session = pipeline.build_session("1: 1.0s | 2: 2.5s", None, "Tor 3", "Jaro")
    assert (session.nazwa_toru, session.uczestnik) == ("Tor 3", "Jaro")
    assert len(session.shots) == 2


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


def test_t0_needs_recheck_manual_never_rechecked():
    assert pipeline.t0_needs_recheck(0, 5) is False


def test_t0_needs_recheck_unknown_detector_is_stale():
    assert pipeline.t0_needs_recheck(None, 2) is True


def test_t0_needs_recheck_older_version_is_stale():
    assert pipeline.t0_needs_recheck(1, 2) is True


def test_t0_needs_recheck_current_version_is_fresh():
    assert pipeline.t0_needs_recheck(2, 2) is False


def test_t0_needs_recheck_newer_version_is_fresh():
    assert pipeline.t0_needs_recheck(3, 2) is False


def test_t0_differs_within_tolerance():
    assert pipeline.t0_differs(26.2, 26.4) is False
    assert pipeline.t0_differs(26.2, 26.45, tol=0.3) is False


def test_t0_differs_beyond_tolerance():
    assert pipeline.t0_differs(26.2, 32.05) is True


# --- skan katalogu z nagraniami (przycisk „Automat z folderu…") -------------

def _make_dir(tmp_path):
    """Katalog jak z karty DJI: nagrania, proxy LRF, miniatura, śmieci, podkatalog."""
    (tmp_path / "DJI_0002.MP4").write_bytes(b"x")
    (tmp_path / "DJI_0002.LRF").write_bytes(b"x")
    (tmp_path / "DJI_0001.mp4").write_bytes(b"x")
    (tmp_path / "DJI_0001.lrf").write_bytes(b"x")
    (tmp_path / "DJI_0001.THM").write_bytes(b"x")
    (tmp_path / "klip.MOV").write_bytes(b"x")
    (tmp_path / "stare.avi").write_bytes(b"x")
    (tmp_path / "film.m4v").write_bytes(b"x")
    (tmp_path / "zrzut.png").write_bytes(b"x")
    (tmp_path / "._DJI_0003.MP4").write_bytes(b"x")   # AppleDouble
    sub = tmp_path / "kam2"
    sub.mkdir()
    (sub / "DJI_0100.mp4").write_bytes(b"x")
    (sub / "notatki.txt").write_bytes(b"x")
    return tmp_path


def test_scan_video_dir_filters_and_sorts(tmp_path):
    found = pipeline.scan_video_dir(_make_dir(tmp_path))
    assert [p.name for p in found] == [
        "DJI_0001.mp4", "DJI_0002.MP4", "film.m4v", "klip.MOV", "stare.avi"]


def test_scan_video_dir_recursive_includes_subdirs(tmp_path):
    found = pipeline.scan_video_dir(_make_dir(tmp_path), recursive=True)
    assert "DJI_0100.mp4" in [p.name for p in found]
    assert len(found) == 6


def test_scan_video_dir_skips_lrf_next_to_mp4(tmp_path):
    (tmp_path / "a.MP4").write_bytes(b"x")
    (tmp_path / "a.LRF").write_bytes(b"x")
    assert [p.name for p in pipeline.scan_video_dir(tmp_path)] == ["a.MP4"]


def test_scan_video_dir_empty(tmp_path):
    assert pipeline.scan_video_dir(tmp_path) == []


def test_scan_video_dir_rejects_non_directory(tmp_path):
    f = tmp_path / "plik.mp4"
    f.write_bytes(b"x")
    with pytest.raises(pipeline.PipelineError):
        pipeline.scan_video_dir(f)
