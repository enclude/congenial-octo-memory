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


def test_sanitize_filename_part():
    from piro_overlay.pipeline import sanitize_filename_part as f
    assert f("Jarosław Zjawiński") == "Jaroslaw_Zjawinski"
    assert f('ŁUKASZ W.') == "LUKASZ_W"
    assert f("a/b:c*d?") == "abcd"
    assert f("   ") == "" and f("") == ""


def test_expand_name_template_variables_and_unknown_kept():
    from piro_overlay.models import Session, Shot
    from piro_overlay.pipeline import expand_name_template as x
    s = Session(shots=[Shot(1, 1.0), Shot(2, 2.5, 1.5)], nazwa_toru="Tor 3 — Bill drill",
                uczestnik="Jarosław Z.", liczba_strzalow=2, czas_bazowy=30.52, hit_factor=3.1)
    assert x("_PiRoOverlay_{id}_{uczestnik}", s, 326) == "_PiRoOverlay_326_Jaroslaw_Z"
    assert x("{tor}_{strzaly}_{czas}_{hf}", s, 326) == "Tor_3_Bill_drill_2_30_52_3_10"
    assert x("{nieznane}_{id}", s, 7) == "{nieznane}_7"
    assert x("_PiRoOverlay", s, 1) == "_PiRoOverlay"
    # brak sesji / ID → puste podstawienia, szablon nie wybucha
    assert x("{id}_{uczestnik}_{czas}", None, None) == "__"


# --- ID-tone v3: rozwiązanie kodu tymczasowego do ID wpisu w bazie ---

def _cand(entry_id: int, temp_id: str = "30147"):
    from datetime import datetime, timezone
    from piro_overlay.api import SessionCandidate
    return SessionCandidate(id=entry_id,
                            data_zapisu=datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc),
                            temp_id=temp_id)


def test_resolve_id_tone_channel_zero_is_entry_id(monkeypatch):
    from piro_overlay.audio_sync import IdToneCode

    def boom(*a, **k):  # kanał 0 nie może odpytywać bazy
        raise AssertionError("kanał 0 nie pyta o temp_id")

    monkeypatch.setattr(pipeline.api, "find_sessions_by_temp_id", boom)
    out = pipeline.resolve_id_tone(IdToneCode(0, 1234), "brak.mp4")
    assert out.session_id == 1234 and out.info == ""


def test_resolve_id_tone_single_temp_candidate(monkeypatch):
    from piro_overlay.audio_sync import IdToneCode
    seen = []

    def fake(temp_id):
        seen.append(temp_id)
        return [_cand(1234)]

    monkeypatch.setattr(pipeline.api, "find_sessions_by_temp_id", fake)
    out = pipeline.resolve_id_tone(IdToneCode(3, 147), "brak.mp4")
    assert seen == ["30147"]
    assert out.session_id == 1234 and out.info == "3-0147 → #1234"


def test_resolve_id_tone_no_entry_gives_no_id(monkeypatch):
    from piro_overlay.audio_sync import IdToneCode
    monkeypatch.setattr(pipeline.api, "find_sessions_by_temp_id", lambda t: [])
    out = pipeline.resolve_id_tone(IdToneCode(3, 147), "brak.mp4")
    assert out.session_id is None and "3-0147" in out.info


def test_resolve_id_tone_api_error_does_not_raise(monkeypatch):
    from piro_overlay.audio_sync import IdToneCode

    def fake(temp_id):
        raise pipeline.api.ApiUnsupported("stary serwer")

    monkeypatch.setattr(pipeline.api, "find_sessions_by_temp_id", fake)
    out = pipeline.resolve_id_tone(IdToneCode(3, 147), "brak.mp4")
    assert out.session_id is None and out.info


def test_resolve_id_tone_ambiguous_candidates_need_recording(monkeypatch):
    # Dwa wpisy z tym samym kodem (licznik kodów zawija się po 9999) i nagranie,
    # którego czasu nie da się ustalić → brak ID, bez zgadywania.
    from piro_overlay.audio_sync import IdToneCode
    from piro_overlay import session_match
    monkeypatch.setattr(pipeline.api, "find_sessions_by_temp_id",
                        lambda t: [_cand(1234), _cand(1250)])
    monkeypatch.setattr(pipeline.ffmpeg, "probe",
                        lambda v: pipeline.ffmpeg.VideoInfo(
                            duration=30.0, fps=30.0, width=320, height=240))
    monkeypatch.setattr(session_match, "recording_start", lambda *a, **k: None)
    out = pipeline.resolve_id_tone(IdToneCode(3, 147), "brak.mp4")
    assert out.session_id is None and "2 wpis" in out.info


def test_batch_variants_order_and_flags():
    vs = pipeline.batch_variants(overlay=True, timer=True, trim=True)
    assert [v.key for v in vs] == ["overlay", "timer", "trim"]
    assert [(v.no_overlay, v.clock) for v in vs] == [
        (False, False), (False, True), (True, False)]


def test_batch_variants_subset_keeps_canonical_order():
    vs = pipeline.batch_variants(overlay=False, timer=True, trim=True)
    assert [v.key for v in vs] == ["timer", "trim"]
    assert pipeline.batch_variants(overlay=False, timer=False, trim=False) == []


def test_batch_variant_suffix_only_for_multiple_variants():
    single = pipeline.batch_variants(overlay=False, timer=True, trim=False)
    assert pipeline.batch_variant_suffix(single, single[0]) == ""
    multi = pipeline.batch_variants(overlay=True, timer=False, trim=True)
    assert [pipeline.batch_variant_suffix(multi, v) for v in multi] == ["_overlay", "_trim"]


def test_batch_output_name_typ_variable_and_subdirs():
    from piro_overlay.pipeline import BATCH_VARIANTS, batch_output_name
    from piro_overlay.models import Session, Shot
    sess = Session(shots=[Shot(1, 1.0, None)], uczestnik="Jan K.")
    ov, tm, tr = BATCH_VARIANTS
    both = [ov, tm]
    # bez {typ}: automatyczny sufiks wariantu przy >1 wariancie
    assert batch_output_name("", "clip", "_x", sess, 5, both, tm, ".mp4") == "clip_x_timer.mp4"
    assert batch_output_name("", "clip", "_x", sess, 5, [tr], tr, ".mp4") == "clip_x.mp4"
    # {typ} w prefiksie: podstawiony, automatyczny sufiks NIE dochodzi, \\ → podkatalog
    assert (batch_output_name("{typ}\\{uczestnik}_", "clip", "", sess, 5, both, ov, ".mp4")
            == "overlay/Jan_K_clip.mp4")
    assert batch_output_name("", "clip", "_{typ}", sess, 5, both, tm, ".mp4") == "clip_timer.mp4"


# --- pola nagrania z kalkulatora w dopasowaniu po czasie ---

def _vcand(entry_id, sess_local, **kw):
    from datetime import datetime, timezone
    from piro_overlay.api import SessionCandidate
    epoch = int(sess_local.replace(tzinfo=timezone.utc).timestamp())
    return SessionCandidate(id=entry_id,
                            data_zapisu=datetime(2026, 8, 12, 17, 52, 12, tzinfo=timezone.utc),
                            timer_sess_id=epoch, **kw)


def _epoch(dt):
    from datetime import timezone
    return int(dt.replace(tzinfo=timezone.utc).timestamp())


def _time_match(monkeypatch, tmp_path, cands, t0=32.05):
    from piro_overlay.ffmpeg import VideoInfo

    def no_scores(*a, **k):
        raise AssertionError("odcisk strzałów nie powinien być liczony")

    video = tmp_path / "DJI_20260812195106_0035_D.MP4"
    video.write_bytes(b"x")
    monkeypatch.setattr(pipeline.api, "find_sessions", lambda *a, **k: list(cands))
    monkeypatch.setattr(pipeline.audio_sync, "shot_alignment_scores", no_scores)
    info = VideoInfo(duration=90.0, fps=50, width=1, height=1)
    return pipeline.find_session_by_time(video, t0=t0, info=info)


def test_find_session_by_time_video_file_short_circuits(monkeypatch, tmp_path):
    from datetime import datetime
    a = _vcand(343, datetime(2026, 8, 12, 19, 51, 37), opis="1: 1.0s")
    b = _vcand(344, datetime(2026, 8, 12, 19, 53, 30), opis="1: 1.5s",
               video_file="DJI_20260812195106_????_D.MP4")
    r = _time_match(monkeypatch, tmp_path, [a, b])
    assert r.picked.candidate.id == 344 and r.picked.reason == "video_file"
    assert "dopasowano po nazwie pliku" in r.info


def test_find_session_by_time_recording_window_drops_neighbour(monkeypatch, tmp_path):
    from datetime import datetime
    a = _vcand(343, datetime(2026, 8, 12, 19, 51, 37),
               rec_start=_epoch(datetime(2026, 8, 12, 19, 51, 5)),
               rec_stop=_epoch(datetime(2026, 8, 12, 19, 52, 40)))
    b = _vcand(344, datetime(2026, 8, 12, 19, 53, 30),
               rec_start=_epoch(datetime(2026, 8, 12, 19, 53, 0)),
               rec_stop=_epoch(datetime(2026, 8, 12, 19, 54, 30)))
    r = _time_match(monkeypatch, tmp_path, [a, b])
    assert r.picked.candidate.id == 343 and r.picked.reason == "timer"
    assert [m.candidate.id for m in r.matches] == [343]
    assert "okno nagrania odrzuciło 1" in r.info


def test_find_session_by_time_window_rejecting_all_falls_back(monkeypatch, tmp_path):
    from datetime import datetime
    far = dict(rec_start=_epoch(datetime(2026, 8, 12, 12, 0, 0)),
               rec_stop=_epoch(datetime(2026, 8, 12, 12, 1, 0)))
    a = _vcand(343, datetime(2026, 8, 12, 19, 51, 37), **far)
    r = _time_match(monkeypatch, tmp_path, [a])
    assert r.picked.candidate.id == 343            # jak dotąd — po czasie timera
    assert "wykluczyło wszystkich" in r.info


def test_find_session_by_time_old_server_unchanged(monkeypatch, tmp_path):
    from datetime import datetime
    a = _vcand(343, datetime(2026, 8, 12, 19, 51, 37))
    b = _vcand(344, datetime(2026, 8, 12, 19, 53, 30))
    r = _time_match(monkeypatch, tmp_path, [a, b], t0=None)   # bez T0 → bez odcisku
    assert r.picked is None and r.ambiguous and r.info == ""
    assert not any(m.file_match for m in r.matches)
