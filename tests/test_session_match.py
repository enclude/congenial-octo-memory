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


def test_pick_two_timer_hits_need_margin_too():
    a = _cand(1, SAVED_326, sess_local=datetime(2026, 8, 12, 19, 51, 37))
    b = _cand(2, SAVED_326, sess_local=datetime(2026, 8, 12, 19, 51, 57))
    assert sm.pick(sm.match_sessions([a, b], REC, 90.0, t0=32.05)) is None
    far = _cand(3, SAVED_326, sess_local=datetime(2026, 8, 12, 19, 53, 0))
    m = sm.pick(sm.match_sessions([far, a], REC, 90.0, t0=None))   # bez T0: oba w oknie
    assert m is not None and m.candidate.id == 1                    # a bliżej o >60 s


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
