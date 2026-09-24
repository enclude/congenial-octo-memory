"""Dopasowanie nagrania do sesji po czasie (session_match + api.find_sessions*)."""
from datetime import datetime, timedelta, timezone

import pytest

from piro_overlay import api, session_match as sm
from piro_overlay.api import SessionCandidate

CEST = timezone(timedelta(hours=2))


def _local_epoch(dt_local: datetime) -> int:
    """`timer_sess_id` = unixtime W CZASIE LOKALNYM (naiwny zegar timera)."""
    return int(dt_local.replace(tzinfo=timezone.utc).timestamp())


def _cand(id_: int, saved_utc: datetime, *, czas=30.0, sess_local: datetime | None = None,
          **kw) -> SessionCandidate:
    return SessionCandidate(
        id=id_, data_zapisu=saved_utc, czas_bazowy=czas,
        timer_sess_id=_local_epoch(sess_local) if sess_local else 0, **kw)


# Realny przypadek: DJI_20260812195106_0035_D.MP4 (start 19:51:06 CEST), T0 = 32,05 s,
# ID 326 zapisane 17:52:12 UTC (= 19:52:12 lokalnie), czas bazowy 30,52 s.
REC = sm.RecordingTime(datetime(2026, 8, 12, 19, 51, 6, tzinfo=CEST), "filename")
SAVED_326 = datetime(2026, 8, 12, 17, 52, 12, tzinfo=timezone.utc)


def test_time_from_filename_dji_and_generic():
    t = sm.time_from_filename("DJI_20260812195106_0035_D.MP4", CEST)
    assert t == datetime(2026, 8, 12, 19, 51, 6, tzinfo=CEST)
    assert sm.time_from_filename("GX010042_20260812_195106.MP4", CEST) == t
    assert sm.time_from_filename("clip.mp4", CEST) is None
    assert sm.time_from_filename("DJI_99999999999999_0001_D.MP4", CEST) is None


def test_time_from_filename_pixel_is_utc():
    # PXL_20260920_101908466.mp4 z zawodów: 10:19:08 UTC = 12:19:08 CEST
    t = sm.time_from_filename("PXL_20260920_101908466.mp4", CEST)
    assert t == datetime(2026, 9, 20, 12, 19, 8, tzinfo=CEST)
    assert sm.time_from_filename("PXL_20260920_101908466.RAW-01.COVER.jpg", CEST) == t
    assert sm.time_from_filename("PXL_2026.mp4", CEST) is None


def test_parse_creation_time_utc_z_and_naive():
    z = sm.parse_creation_time("2026-07-07T16:06:24.000000Z")
    assert z == datetime(2026, 7, 7, 16, 6, 24, tzinfo=timezone.utc)
    naive = sm.parse_creation_time("2026-07-07 16:06:24")
    assert naive.tzinfo is timezone.utc
    assert sm.parse_creation_time("") is None
    assert sm.parse_creation_time("garbage") is None


def test_recording_start_prefers_filename_then_creation_time_then_mtime(tmp_path):
    dji = tmp_path / "DJI_20260707180623_0051_D.MP4"
    dji.write_bytes(b"x")
    r = sm.recording_start(dji, 33.0, "2026-07-07T16:06:24Z", CEST)
    assert r.source == "filename" and r.start.hour == 18

    other = tmp_path / "clip.mp4"
    other.write_bytes(b"x")
    r = sm.recording_start(other, 33.0, "2026-07-07T16:06:24Z", CEST)
    assert r.source == "creation_time"
    assert r.start == datetime(2026, 7, 7, 18, 6, 24, tzinfo=CEST)

    r = sm.recording_start(other, 33.0, "", CEST)
    assert r.source == "mtime"
    mtime = datetime.fromtimestamp(other.stat().st_mtime, CEST)
    assert abs((mtime - r.start).total_seconds() - 33.0) < 0.01

    assert sm.recording_start(tmp_path / "missing.mp4", 1.0, "", CEST) is None


def test_query_window_is_utc_with_tz_offset():
    frm, to, off = sm.query_window(REC, 60.0)
    assert frm.tzinfo is timezone.utc and to.tzinfo is timezone.utc
    assert off == 7200
    assert frm < REC.start < to
    assert (to - REC.start).total_seconds() > 60.0 + sm.SAVE_MAX_S


def test_match_saved_only_with_t0_picks_real_case():
    cands = [_cand(325, SAVED_326 - timedelta(minutes=8), czas=45.0, uczestnik="Daniel"),
             _cand(326, SAVED_326, czas=30.52, uczestnik="Jaro"),
             _cand(327, SAVED_326 + timedelta(minutes=3), czas=20.0)]
    matches = sm.match_sessions(cands, REC, duration=90.0, t0=32.05)
    picked = sm.pick(matches)
    assert picked is not None and picked.candidate.id == 326
    assert picked.basis == "saved"
    # zapis 19:52:12 vs oczekiwany koniec 19:51:06 + 32,05 + 30,52 = 19:52:08,6 → Δ ≈ +3,4 s
    assert 0 < picked.delta_s < 10


def test_match_timer_sess_id_wins_over_saved_and_survives_bulk_upload():
    # wpis z timera wysłany hurtowo 4 h później — data_zapisu bezużyteczne,
    # ale timer_sess_id = start sesji (19:51:37 lokalnie, ~1 s przed bzyczkiem)
    bulk = _cand(330, SAVED_326 + timedelta(hours=4), czas=30.5,
                 sess_local=datetime(2026, 8, 12, 19, 51, 37))
    # wpis ręczny zapisany w sensownym oknie — konkurent po data_zapisu
    manual = _cand(331, SAVED_326 + timedelta(seconds=40), czas=30.0)
    matches = sm.match_sessions([manual, bulk], REC, duration=90.0, t0=32.05)
    assert matches[0].candidate.id == 330 and matches[0].basis == "timer"
    assert abs(matches[0].delta_s + 1.05) < 0.5
    picked = sm.pick(matches)
    assert picked is not None and picked.candidate.id == 330   # timer rozstrzyga


def test_match_without_t0_uses_whole_recording_window():
    inside = _cand(1, SAVED_326, czas=30.0)
    later = _cand(2, SAVED_326 + timedelta(minutes=20), czas=30.0)
    matches = sm.match_sessions([later, inside], REC, duration=90.0, t0=None)
    assert [m.candidate.id for m in matches] == [1, 2]
    assert matches[0].in_window and not matches[1].in_window
    assert sm.pick(matches).candidate.id == 1


def test_pick_none_when_ambiguous_or_empty():
    a = _cand(1, SAVED_326, czas=30.0)
    b = _cand(2, SAVED_326 + timedelta(seconds=30), czas=30.0)
    matches = sm.match_sessions([a, b], REC, duration=90.0, t0=32.05)
    assert all(m.in_window for m in matches)
    assert sm.pick(matches) is None      # |Δ| 3 s vs 33 s — za blisko, by rozstrzygnąć
    result = sm.MatchResult(REC, matches, None)
    assert result.ambiguous
    assert sm.pick(()) is None
    assert not sm.MatchResult(REC, (), None).ambiguous


def test_pick_two_timer_hits_are_always_ambiguous():
    # 2026-09-20: zegar timera ~110 s do przodu — nagranie 0003 (T0 11,7 s) miało
    # 343 przy Δ+49 i 344 przy Δ+111, a właściwe było 344. Bliskość nie rozstrzyga.
    a = _cand(1, SAVED_326, sess_local=datetime(2026, 8, 12, 19, 51, 37))
    b = _cand(2, SAVED_326, sess_local=datetime(2026, 8, 12, 19, 53, 30))
    matches = sm.match_sessions([a, b], REC, 90.0, t0=32.05)
    assert [m.in_window for m in matches] == [True, True]
    assert sm.pick(matches) is None
    assert sm.MatchResult(REC, matches, None).ambiguous
    # poza oknem (150 s) drugi już nie przeszkadza
    far = _cand(3, SAVED_326, sess_local=datetime(2026, 8, 12, 19, 57, 0))
    assert sm.pick(sm.match_sessions([far, a], REC, 90.0, t0=32.05)).candidate.id == 1


def test_match_rejects_session_saved_before_it_could_end():
    # zapis 2 min PRZED oczekiwanym końcem = inna, wcześniejsza sesja
    early = _cand(9, SAVED_326 - timedelta(minutes=2), czas=30.0)
    (m,) = sm.match_sessions([early], REC, duration=90.0, t0=32.05)
    assert not m.in_window and m.delta_s < sm.SAVE_MIN_S


# --- api: parsowanie i tryb listy ---

def test_candidate_from_payload_single_and_list_shapes():
    single = {"id": 326, "data_zapisu": "2026-08-12 17:52:12", "nazwa_toru": "ŁUKASZ W.",
              "uczestnik": "Jaro", "liczba_strzalow": 10,
              "czasy": {"czas_bazowy": 30.52}, "timer_sn": "SG-1", "timer_sess_id": 5}
    c = api.candidate_from_payload(single)
    assert c.czas_bazowy == 30.52 and c.data_zapisu == SAVED_326 and c.timer_sess_id == 5
    listed = {"id": 1, "data_zapisu": "2026-08-12 17:52:12", "czas_bazowy": 12.5}
    assert api.candidate_from_payload(listed).czas_bazowy == 12.5


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


def test_find_sessions_parses_list_and_sends_window(monkeypatch):
    seen = {}

    def fake_get(url, params=None, timeout=None):
        seen.update(params)
        return _Resp(200, {"ok": True, "data": [
            {"id": 7, "data_zapisu": "2026-08-12 17:52:12", "czas_bazowy": 3.0,
             "timer_sess_id": 0}]})

    monkeypatch.setattr(api.requests, "get", fake_get)
    frm = datetime(2026, 8, 12, 17, 50, tzinfo=timezone.utc)
    out = api.find_sessions(frm, frm + timedelta(minutes=5), tz_offset_s=7200)
    assert [c.id for c in out] == [7]
    assert seen == {"from": int(frm.timestamp()), "to": int(frm.timestamp()) + 300,
                    "tz_offset": 7200}


def test_find_sessions_old_server_raises_unsupported(monkeypatch):
    monkeypatch.setattr(api.requests, "get", lambda *a, **k: _Resp(400, {
        "ok": False, "error": {"code": 400, "message":
                               'Brak lub nieprawidłowy parametr "id". Wymagana dodatnia liczba'}}))
    frm = datetime(2026, 8, 12, tzinfo=timezone.utc)
    with pytest.raises(api.ApiUnsupported):
        api.find_sessions(frm, frm, tz_offset_s=0)


def test_find_sessions_other_error_is_plain_api_error(monkeypatch):
    monkeypatch.setattr(api.requests, "get", lambda *a, **k: _Resp(500, {
        "ok": False, "error": {"code": 500, "message": "boom"}}))
    frm = datetime(2026, 8, 12, tzinfo=timezone.utc)
    with pytest.raises(api.ApiError) as ei:
        api.find_sessions(frm, frm, tz_offset_s=0)
    assert not isinstance(ei.value, api.ApiUnsupported)


def test_find_sessions_by_temp_id_parses_list(monkeypatch):
    seen = {}

    def fake_get(url, params=None, timeout=None):
        seen.update(params)
        return _Resp(200, {"ok": True, "data": [
            {"id": 1234, "data_zapisu": "2026-09-20 10:00:00", "czas_bazowy": 12.0,
             "timer_sess_id": 0, "temp_id": "30147"}]})

    monkeypatch.setattr(api.requests, "get", fake_get)
    out = api.find_sessions_by_temp_id("30147")
    assert [(c.id, c.temp_id) for c in out] == [(1234, "30147")]
    assert seen == {"temp_id": "30147"}


def test_find_sessions_by_temp_id_old_server_raises_unsupported(monkeypatch):
    monkeypatch.setattr(api.requests, "get", lambda *a, **k: _Resp(400, {
        "ok": False, "error": {"code": 400, "message":
                               'Brak lub nieprawidłowy parametr "id". Wymagana dodatnia liczba'}}))
    with pytest.raises(api.ApiUnsupported):
        api.find_sessions_by_temp_id("30147")


def test_find_sessions_by_temp_id_error_is_plain_api_error(monkeypatch):
    monkeypatch.setattr(api.requests, "get", lambda *a, **k: _Resp(500, {
        "ok": False, "error": {"code": 500, "message": "boom"}}))
    with pytest.raises(api.ApiError) as ei:
        api.find_sessions_by_temp_id("30147")
    assert not isinstance(ei.value, api.ApiUnsupported)


def _fake_db(n=400, gap=(150, 151, 152), start=datetime(2026, 1, 1, tzinfo=timezone.utc)):
    """ID 1..n co 10 minut; `gap` = usunięte wpisy (404)."""
    calls = []

    def fetch(i):
        calls.append(i)
        if i < 1 or i > n or i in gap:
            return None
        return SessionCandidate(id=i, data_zapisu=start + timedelta(minutes=10 * i))
    return fetch, calls, start


def test_find_sessions_by_scan_binary_search_over_ids():
    fetch, calls, start = _fake_db()
    frm = start + timedelta(minutes=10 * 300 - 1)
    to = start + timedelta(minutes=10 * 303 + 1)
    out = api.find_sessions_by_scan(frm, to, fetch=fetch)
    assert [c.id for c in out] == [300, 301, 302, 303]
    assert len(calls) < api._SCAN_MAX_REQUESTS
    assert len(calls) < 40   # ~log2(400) + końcówka, nie 400 żądań


def test_find_sessions_by_scan_crosses_deleted_gap_and_uses_hint():
    fetch, calls, start = _fake_db()
    frm = start + timedelta(minutes=10 * 148)
    to = start + timedelta(minutes=10 * 154)
    out = api.find_sessions_by_scan(frm, to, fetch=fetch, hint_id=140)
    assert [c.id for c in out] == [148, 149, 153, 154]


def test_find_sessions_by_scan_empty_window_after_last_entry():
    fetch, calls, start = _fake_db(n=50)
    frm = start + timedelta(days=365)
    assert api.find_sessions_by_scan(frm, frm + timedelta(hours=1), fetch=fetch) == []


def test_find_sessions_by_scan_budget_guard():
    def fetch(i):
        return SessionCandidate(id=i, data_zapisu=datetime(2020, 1, 1, tzinfo=timezone.utc))
    frm = datetime(2030, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(api.ApiError):
        api.find_sessions_by_scan(frm, frm, fetch=fetch)   # baza „bez końca" → limit żądań


# --- odcisk strzałów (rozstrzyganie przy kilku kandydatach w oknie) ---

def _synthetic_shots(shot_times, t0=5.0, sr=16000, total=20.0, seed=1):
    import numpy as np
    rng = np.random.default_rng(seed)
    x = rng.normal(0, 0.01, int(total * sr))
    for s in shot_times:
        i = int((t0 + s) * sr)
        x[i:i + int(0.02 * sr)] += rng.normal(0, 1.0, int(0.02 * sr))   # impuls 20 ms
    return x, sr


def test_shot_alignment_score_prefers_true_timeline():
    from piro_overlay import audio_sync
    true = [1.0, 1.7, 2.3, 3.4, 4.1, 5.0]
    other = [1.3, 2.0, 2.9, 3.8, 4.6, 5.5]        # inny strzelec, podobny rytm
    x, sr = _synthetic_shots(true)
    good = audio_sync.shot_alignment_score(x, sr, 5.0, true)
    bad = audio_sync.shot_alignment_score(x, sr, 5.0, other)
    assert good > sm.SHOT_SCORE_RATIO * bad
    assert audio_sync.shot_alignment_score(x, sr, 5.0, []) == 0.0


def test_candidate_shots_parses_opis_with_prefixes():
    c = SessionCandidate(id=1, data_zapisu=SAVED_326,
                         opis="20.09.2026, 13:00:08 | opoznienie startu 3s | 1: 3.76s | 2: 4.76s (+1.00s)")
    assert sm.candidate_shots(c) == [3.76, 4.76]
    assert sm.candidate_shots(SessionCandidate(id=2, data_zapisu=SAVED_326)) is None
    assert sm.candidate_shots(SessionCandidate(id=3, data_zapisu=SAVED_326, opis="śmieci")) is None


def test_shot_scores_break_timer_tie_and_duplicate_stays_ambiguous():
    # 2026-09-20: dwa kandydaci z timera w oknie (dryf zegara) — sam czas = None
    a = _cand(343, SAVED_326, sess_local=datetime(2026, 8, 12, 19, 51, 37))
    b = _cand(344, SAVED_326, sess_local=datetime(2026, 8, 12, 19, 53, 30))
    matches = sm.match_sessions([a, b], REC, 90.0, t0=32.05)
    assert sm.pick(matches) is None
    scored = sm.apply_shot_scores(matches, {343: 1.4, 344: 3.5})
    assert [m.candidate.id for m in scored] == [344, 343]
    assert sm.pick(scored).candidate.id == 344
    # duplikat wpisu (ta sama oś dwa razy) → remis → nadal wybór użytkownika
    dup = sm.apply_shot_scores(matches, {343: 7.6, 344: 7.6})
    assert sm.pick(dup) is None
    # wynik tylko dla jednego kandydata → bez rozstrzygnięcia po odcisku
    assert sm.pick(sm.apply_shot_scores(matches, {343: 5.0})) is None


def test_find_session_by_time_uses_fingerprint_for_multiple_hits(monkeypatch, tmp_path):
    from piro_overlay import api as _api, audio_sync, pipeline
    from piro_overlay.ffmpeg import VideoInfo
    video = tmp_path / "DJI_20260812195106_0035_D.MP4"
    video.write_bytes(b"x")
    a = _cand(343, SAVED_326, sess_local=datetime(2026, 8, 12, 19, 51, 37), opis="1: 1.0s | 2: 2.0s (+1.0s)")
    b = _cand(344, SAVED_326, sess_local=datetime(2026, 8, 12, 19, 53, 30), opis="1: 1.5s | 2: 2.5s (+1.0s)")
    monkeypatch.setattr(_api, "find_sessions", lambda *a_, **k: [a, b])
    seen = {}

    def fake_scores(path, t0, timelines):
        seen.update(timelines)
        return {343: 1.0, 344: 4.0}
    monkeypatch.setattr(audio_sync, "shot_alignment_scores", fake_scores)
    monkeypatch.setattr(pipeline, "audio_source", lambda v: str(v))
    info = VideoInfo(duration=90.0, fps=50, width=1, height=1)
    r = pipeline.find_session_by_time(video, t0=32.05, info=info)
    assert seen == {343: [1.0, 2.0], 344: [1.5, 2.5]}
    assert r.picked.candidate.id == 344 and r.picked.shot_score == 4.0
    # bez T0 odcisk nie jest liczony (nie ma od czego mierzyć) → niejednoznaczne
    seen.clear()
    r2 = pipeline.find_session_by_time(video, t0=None, info=info)
    assert seen == {} and r2.picked is None and r2.ambiguous


# --- pola nagrania z kalkulatora: video_file, rec_start/rec_stop ---

VIDEO = "DJI_20260812195106_0035_D.MP4"


def test_candidate_from_payload_video_fields_single_list_and_old_server():
    single = {"id": 1, "data_zapisu": "2026-08-12 17:52:12",
              "wideo": {"plik": "DJI_20260812195106_????_D.MP4",
                        "rec_start": 1786564266, "rec_stop": 1786564366}}
    c = api.candidate_from_payload(single)
    assert (c.video_file, c.rec_start, c.rec_stop) == (
        "DJI_20260812195106_????_D.MP4", 1786564266, 1786564366)
    listed = {"id": 2, "data_zapisu": "2026-08-12 17:52:12", "video_file": VIDEO,
              "rec_start": "1786564266", "rec_stop": None}
    c = api.candidate_from_payload(listed)
    assert (c.video_file, c.rec_start, c.rec_stop) == (VIDEO, 1786564266, 0)
    old = api.candidate_from_payload({"id": 3, "data_zapisu": "2026-08-12 17:52:12"})
    assert (old.video_file, old.rec_start, old.rec_stop) == ("", 0, 0)
    junk = api.candidate_from_payload({"id": 4, "data_zapisu": "2026-08-12 17:52:12",
                                       "wideo": None, "rec_start": "x", "rec_stop": -5})
    assert (junk.rec_start, junk.rec_stop) == (0, 0)


def test_video_file_matches_exact_wildcard_siblings_and_misses():
    assert sm.video_file_matches(VIDEO, "/x/DJI_20260812195106_0035_D.MP4")
    assert sm.video_file_matches("dji_20260812195106_0035_d.mp4", "D:/x/" + VIDEO)
    # proxy LRF i miniatura THM mają ten sam rdzeń co MP4
    assert sm.video_file_matches(VIDEO, "DJI_20260812195106_0035_D.LRF")
    assert sm.video_file_matches("DJI_20260812195106_0035_D.THM", VIDEO)
    # licznik nieznany (predykcja z zegara kamery) — czas musi się zgadzać co do sekundy
    assert sm.video_file_matches("DJI_20260812195106_????_D.MP4", VIDEO)
    assert sm.video_file_matches("DJI_20260812195106_????_D.MP4", "DJI_20260812195106_0099_D.LRF")
    assert not sm.video_file_matches("DJI_20260812195107_????_D.MP4", VIDEO)
    assert not sm.video_file_matches("DJI_20260812195106_0036_D.MP4", VIDEO)
    assert not sm.video_file_matches("DJI_20260812195106_????_D.MP4", "clip.mp4")
    assert not sm.video_file_matches("", VIDEO)


def test_pick_prefers_single_video_file_match_over_time():
    # dwa kandydaci z timera w oknie = normalnie niejednoznaczne; nazwa pliku rozstrzyga
    a = _cand(1, SAVED_326, sess_local=datetime(2026, 8, 12, 19, 51, 37))
    b = _cand(2, SAVED_326, sess_local=datetime(2026, 8, 12, 19, 53, 30),
              video_file="DJI_20260812195106_????_D.MP4")
    matches = sm.match_sessions([a, b], REC, 90.0, t0=32.05, video_path=VIDEO)
    assert matches[0].candidate.id == 2 and matches[0].file_match
    picked = sm.pick(matches)
    assert picked.candidate.id == 2 and picked.reason == "video_file"
    # bez ścieżki nagrania — zachowanie jak dotąd
    assert sm.pick(sm.match_sessions([a, b], REC, 90.0, t0=32.05)) is None


def test_video_file_match_wins_even_outside_time_window():
    # zegar timera uciekł o 10 min — nazwa pliku i tak wskazuje wpis
    drift = _cand(5, SAVED_326 + timedelta(hours=3),
                  sess_local=datetime(2026, 8, 12, 20, 2, 0), video_file=VIDEO)
    (m,) = sm.match_sessions([drift], REC, 90.0, t0=32.05, video_path=VIDEO)
    assert m.in_window and m.file_match
    assert sm.pick((m,)).candidate.id == 5


def test_duplicate_video_file_matches_stay_ambiguous():
    a = _cand(1, SAVED_326, video_file=VIDEO)
    b = _cand(2, SAVED_326 + timedelta(seconds=5), video_file=VIDEO)
    other = _cand(3, SAVED_326 + timedelta(minutes=3))
    matches = sm.match_sessions([a, b, other], REC, 90.0, t0=32.05, video_path=VIDEO)
    assert sm.pick(matches) is None
    assert sm.MatchResult(REC, matches, None).ambiguous


def _win(start_local: datetime, stop_local: datetime) -> dict:
    return {"rec_start": _local_epoch(start_local), "rec_stop": _local_epoch(stop_local)}


def test_recording_window_filter_keeps_and_drops():
    # nagranie 19:51:06 + T0 32,05 s → start sesji ~19:51:38 lokalnie
    inside = _cand(1, SAVED_326, **_win(datetime(2026, 8, 12, 19, 51, 5),
                                        datetime(2026, 8, 12, 19, 52, 30)))
    other = _cand(2, SAVED_326, **_win(datetime(2026, 8, 12, 19, 54, 0),
                                       datetime(2026, 8, 12, 19, 55, 0)))
    edge = _cand(3, SAVED_326, **_win(datetime(2026, 8, 12, 19, 52, 0),     # 22 s po → w TOL
                                      datetime(2026, 8, 12, 19, 53, 0)))
    unknown = _cand(4, SAVED_326, rec_start=_local_epoch(datetime(2026, 8, 12, 10, 0)))
    kept, dropped = sm.filter_by_recording_window([inside, other, edge, unknown], REC,
                                                  90.0, t0=32.05)
    assert [c.id for c in kept] == [1, 3, 4] and dropped == 1
    # bez T0 cały przedział nagrania (19:51:06–19:52:36) — `other` nadal poza
    kept, dropped = sm.filter_by_recording_window([inside, other], REC, 90.0, t0=None)
    assert [c.id for c in kept] == [1] and dropped == 1
    # start nagrania nie z nazwy pliku → bez filtra
    rec_ct = sm.RecordingTime(REC.start, "creation_time")
    assert sm.filter_by_recording_window([other], rec_ct, 90.0, 32.05) == ([other], 0)
    # wskazany nazwą pliku nie jest odrzucany przez okno
    named = _cand(5, SAVED_326, video_file=VIDEO, **_win(datetime(2026, 8, 12, 19, 54, 0),
                                                         datetime(2026, 8, 12, 19, 55, 0)))
    assert sm.filter_by_recording_window([named], REC, 90.0, 32.05, VIDEO) == ([named], 0)
