"""Automatyczne wiązanie ujęć z wpisami (`matching.py`, `DOPASOWANIE-WIDEO.md` §3, ADR-063).

Dane syntetyczne w konwencji ESP: ujęcie DJI zaczyna się `true_start`, bzyczek jest
w pliku w `t0`, ESP widzi start nagrania 0,6 s później (push 0x1D/0x02 z całkowitym
`record_time_s`), więc `rec_start = floor(true_start + 0,6)`, `preroll_ms = beep −
rec_start` (dokładny), `video_file` = predykcja z `rec_start` z licznikiem `????`.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from piro_overlay import api, assignment_store, matching, pipeline
from piro_overlay import matching_score as S
from piro_overlay.api import SessionCandidate
from piro_overlay.audio_sync import IdToneCode

TZ = timezone(timedelta(hours=2))            # CEST — deterministycznie, bez strefy hosta
BASE = matching.wall_of(datetime(2026, 9, 24, 10, 0, 0), TZ)   # 10:00:00 czasu ściennego
ESP_LAG = 0.6


def _name(wall: float) -> str:
    return (datetime(1970, 1, 1) + timedelta(seconds=math.floor(wall))).strftime("%Y%m%d%H%M%S")


def entry(eid: int, true_start: float, t0: float, duration: float, *, fields: bool = True,
          timer_sn: str = "SG-1", temp_id: str = "", opis: str = "",
          idtone_after_stop: float | None = None, **kw) -> SessionCandidate:
    """Wpis tak, jak wysłałoby go ESP dla ujęcia (true_start, t0, duration)."""
    beep = true_start + t0
    rec_start_precise = true_start + ESP_LAG
    rec_start = math.floor(rec_start_precise)
    saved = matching.wall_to_datetime(beep + 60, TZ).astimezone(timezone.utc)
    if not fields:     # stary serwer / wpis z timera bez ESP
        return SessionCandidate(id=eid, data_zapisu=saved, timer_sn=timer_sn,
                                timer_sess_id=int(beep), temp_id=temp_id, opis=opis, **kw)
    rec_stop = rec_start + duration
    extra = {}
    if idtone_after_stop is not None:
        extra = dict(idtone_played="db", idtone_value=f"{eid:04d}",
                     idtone_at_ms=int((rec_start + idtone_after_stop) * 1000))
    return SessionCandidate(
        id=eid, data_zapisu=saved, timer_sn=timer_sn, timer_sess_id=int(beep) + 3,
        temp_id=temp_id, opis=opis,
        video_file=f"DJI_{_name(rec_start)}_????_D.MP4",
        rec_start=rec_start, rec_stop=int(rec_stop),
        video_duration_s=round(duration), video_preroll_ms=round((beep - rec_start_precise) * 1000),
        video_status="ok", video_cam="FF33-3fa91c02", t_beep_ms=round(beep * 1000),
        clock_ok=True, station_no=1, **{**extra, **kw})


def dji_take(true_start: float, t0: float | None, duration: float, *, cam_offset: float = 0.0,
             tone: IdToneCode | None = None, counter: int = 1, folder: str = "/card") -> matching.Take:
    name_wall = math.floor(true_start + cam_offset)
    stem = f"DJI_{_name(name_wall)}_{counter:04d}_D"
    path = Path(folder) / f"{stem}.MP4"
    return matching.Take(stem, path, "dji", "dji", float(name_wall), "filename", duration, t0,
                         tone, (path,))


def pixel_take(true_start: float, t0: float | None, duration: float, *,
               tone: IdToneCode | None = None) -> matching.Take:
    utc = matching.wall_to_datetime(true_start, TZ).astimezone(timezone.utc)
    stem = "PXL_" + utc.strftime("%Y%m%d_%H%M%S") + "123"
    path = Path("/phone") / f"{stem}.mp4"
    return matching.Take(stem, path, "pixel", "pxl", true_start, "filename", duration, t0,
                         tone, (path,))


def kinds(ps: matching.PairScore) -> dict[str, int]:
    return {e.kind: e.points for e in ps.evidence}


def score(take, c, **kw) -> matching.PairScore:
    return matching.score_pair(take, c, tz=TZ, **kw)


# --- sygnały osobno ---------------------------------------------------------

def test_signal_tone_db_match_and_other_entry():
    c = entry(101, BASE, 5.5, 25)
    assert kinds(score(dji_take(BASE, None, 0, tone=IdToneCode(0, 101)), c))["tone"] == 100
    other = score(dji_take(BASE, None, 0, tone=IdToneCode(0, 999)), c)
    ev = [e for e in other.evidence if e.kind == "tone"][0]
    assert ev.points == S.TONE_DB_OTHER and ev.contradiction


def test_signal_tone_temp_window_and_other_code():
    c = entry(101, BASE, 5.5, 25, temp_id="30147")
    tone = IdToneCode(3, 147)
    assert kinds(score(dji_take(BASE, 5.5, 25, tone=tone), c))["tone"] == S.TONE_TEMP_MATCH
    old = score(dji_take(BASE + 13 * 3600, 5.5, 25, tone=tone), c)
    assert kinds(old)["tone"] == 0 and any("stary kod" in e.reason for e in old.evidence)
    other = score(dji_take(BASE, 5.5, 25, tone=IdToneCode(3, 148)), c)
    assert kinds(other)["tone"] == S.TONE_TEMP_OTHER


def test_signal_tone_position():
    c = entry(101, BASE, 5.5, 25, idtone_after_stop=26.0)
    expected = c.idtone_at_ms / 1000 - c.rec_start
    near = score(dji_take(BASE, None, 0, tone=IdToneCode(0, 101, pos_s=expected + 0.4)), c)
    far = score(dji_take(BASE, None, 0, tone=IdToneCode(0, 101, pos_s=expected + 2.0)), c)
    assert kinds(near)["tone_pos"] == S.TONE_POS_MATCH and "tone_pos" not in kinds(far)


@pytest.mark.parametrize("t0,points", [(5.5, 10), (5.2, 25), (5.85, 10), (6.5, 0), (7.9, 0), (9.5, -25)])
def test_signal_preroll_tiers(t0, points):
    c = entry(101, BASE, 5.5, 25)                  # preroll_ms = 4900 (5.5 − 0.6)
    got = kinds(score(dji_take(BASE, t0, 25), c)).get("preroll", 0)
    assert got == points


def test_signal_preroll_skipped_for_partial_and_late_rec():
    c = entry(101, BASE, 5.5, 25)
    assert "preroll" not in kinds(score(dji_take(BASE, 12.0, 25), replace(c, video_status="partial")))
    assert "preroll" not in kinds(score(dji_take(BASE, 12.0, 25), replace(c, video_preroll_ms=-800)))


@pytest.mark.parametrize("dur,points", [(26.0, 15), (31.0, 0), (40.0, -15)])
def test_signal_duration_tiers(dur, points):
    c = entry(101, BASE, 5.5, 25)
    assert kinds(score(dji_take(BASE, None, dur), c)).get("duration", 0) == points


@pytest.mark.parametrize("shift,points", [(0, 40), (-2, 40), (1, 40), (5, 20), (25, 5),
                                          (60, 0)])
def test_signal_name_tiers(shift, points):
    # shift = przesunięcie nazwy pliku względem prawdziwego startu (zegar kamery)
    c = entry(101, BASE, 5.5, 25)
    take = dji_take(BASE, None, 25, cam_offset=shift)
    assert kinds(score(take, c)).get("name", 0) == points


def test_signal_name_far_off_is_contradiction_only_with_trusted_clock():
    c = entry(101, BASE, 5.5, 25)
    take = dji_take(BASE, None, 25, cam_offset=600)
    untrusted = [e for e in score(take, c).evidence if e.kind == "name"][0]
    assert untrusted.points == round(S.NAME_BAD * S.UNTRUSTED_PENALTY) and not untrusted.contradiction
    trusted = [e for e in score(take, c, offset_known=True).evidence if e.kind == "name"][0]
    assert trusted.points == S.NAME_BAD and trusted.contradiction


@pytest.mark.parametrize("shift,points", [(1, 30), (8, 15), (100, 5), (200, 0), (400, -30)])
def test_signal_beep_esp_tiers_on_phone(shift, points):
    c = entry(101, BASE, 5.5, 25)
    take = pixel_take(BASE + shift, 5.5, 25)
    assert kinds(score(take, c)).get("beep", 0) == points


def test_signal_beep_timer_clock_half_points_wider_tiers():
    c = entry(101, BASE, 5.5, 25, fields=False)     # tylko timer_sess_id (zegar T)
    assert kinds(score(pixel_take(BASE + 20, 5.5, 25), c))["beep"] == 8     # ≤ 30 s → 15/2
    far = [e for e in score(pixel_take(BASE + 2000, 5.5, 25), c).evidence if e.kind == "beep"][0]
    assert far.points < 0 and not far.contradiction   # dryf timera nie wetuje


def test_signal_saved_for_manual_entry():
    beep = BASE + 5.5
    saved = matching.wall_to_datetime(beep + 30 + 40, TZ).astimezone(timezone.utc)
    c = SessionCandidate(id=7, data_zapisu=saved, czas_bazowy=30.0)
    assert kinds(score(pixel_take(BASE, 5.5, 60), c))["saved"] == S.SAVE_MATCH


def test_signal_station_and_shots():
    c = entry(101, BASE, 5.5, 25, timer_sn="SG-7")
    assert kinds(score(dji_take(BASE, 5.5, 25), c, stations={"SG-7"}))["station"] == 10
    ev = matching.shot_evidence({1: 4.0, 2: 1.5, 3: 1.05})
    assert ev[1].points == S.SHOT_MATCH and 2 not in ev and ev[3].points == S.SHOT_BACKGROUND
    assert 1 not in matching.shot_evidence({1: 4.0, 2: 3.5})      # < 1,3× — bez premii


def test_old_entry_without_new_fields_only_old_signals():
    c = entry(101, BASE, 5.5, 25, fields=False)
    ps = score(dji_take(BASE, 5.5, 25), c)
    assert set(kinds(ps)) == {"beep"}


# --- decyzja ------------------------------------------------------------------

def test_decide_tone_alone_is_enough():
    cands = [entry(100 + k, BASE + 120 * k, 5.5, 25, fields=False) for k in range(3)]
    take = dji_take(BASE + 120, None, 0, tone=IdToneCode(0, 101))
    a = matching.decide(take, [score(take, c) for c in cands])
    assert a.state == "picked" and a.entry_id == 101


def test_decide_veto_tone_contradicted_by_preroll():
    # A6: ton ch0 = #101, ale T0 w pliku o > 3 s od pre-rollu #101
    c = entry(101, BASE, 5.5, 25)
    take = dji_take(BASE, 10.0, 25, tone=IdToneCode(0, 101))
    a = matching.decide(take, [score(take, c)])
    assert a.state == "ambiguous" and a.entry_id is None
    assert a.label.startswith("do decyzji: ID-tone #101, ale") and "pre-roll" in a.label


def test_decide_ambiguous_when_margin_below_30():
    # duplikat wpisu: dwie identyczne sesje → remis
    a1 = entry(101, BASE, 5.5, 25)
    a2 = replace(a1, id=102)
    take = dji_take(BASE, 5.5, 25)
    d = matching.decide(take, [score(take, a1), score(take, a2)])
    assert d.state == "ambiguous" and "przewaga 0 pkt" in d.label
    # przewaga dokładnie 30 wystarcza, 29 nie
    base = matching.PairScore(a1, (matching.Evidence("name", 90, "x"),))
    assert matching.decide(take, [base, matching.PairScore(a2, (matching.Evidence("name", 60, "y"),))]).state == "picked"
    assert matching.decide(take, [base, matching.PairScore(a2, (matching.Evidence("name", 61, "y"),))]).state == "ambiguous"


def test_decide_single_clock_signal_is_not_enough():
    c = entry(101, BASE, 5.5, 25)
    take = pixel_take(BASE, 5.5, 25)              # tylko beep +30
    assert matching.decide(take, [score(take, c)]).state == "ambiguous"


def test_decide_none_without_positive_evidence():
    c = entry(101, BASE + 5000, 5.5, 25)
    take = pixel_take(BASE, 5.5, 25)
    assert matching.decide(take, [score(take, c)]).state == "none"


# --- przebieg wsadowy -----------------------------------------------------------

def _session(n=5, cam_offset=0.0, tones=(0, 1, 2)):
    t0s = [5.1, 6.7, 5.6, 6.2, 5.3]
    durs = [25.0, 31.0, 38.0, 44.0, 52.0]
    entries, takes = [], []
    for k in range(n):
        start = BASE + 120 * k
        entries.append(entry(101 + k, start, t0s[k], durs[k]))
        tone = IdToneCode(0, 101 + k) if k in tones else None
        takes.append(dji_take(start, t0s[k], durs[k], cam_offset=cam_offset, tone=tone,
                              counter=k + 1))
    return takes, entries


def test_batch_all_dji_picked_with_synced_clock():
    takes, entries = _session(tones=())
    rep = matching.match_takes(takes, entries, tz=TZ)
    assert [(a.state, a.entry_id) for a in rep.assignments] == [("picked", 101 + k) for k in range(5)]


def test_batch_offset_estimated_from_anchors():
    # A2: nazwy DJI przesunięte o +69 s (zegar kamery przed Mimo), 3 kotwice ch0
    takes, entries = _session(cam_offset=69)
    rep = matching.match_takes(takes, entries, tz=TZ)
    off = rep.offsets["dji"]
    assert off.known and off.anchors == 3 and off.delta_s == pytest.approx(69, abs=1)
    assert [(a.state, a.entry_id) for a in rep.assignments] == [("picked", 101 + k) for k in range(5)]
    # bez kotwic offset nieznany → ujęcia bez tonu nie są pewne (nie zgadujemy)
    rep2 = matching.match_takes([replace(t, tone=None) for t in takes], entries, tz=TZ)
    assert not rep2.offsets["dji"].known
    assert all(a.state != "picked" or a.entry_id == 101 + i
               for i, a in enumerate(rep2.assignments))


def test_batch_two_anchors_not_enough_for_offset():
    takes, entries = _session(cam_offset=69, tones=(0, 1))
    rep = matching.match_takes(takes, entries, tz=TZ)
    assert not rep.offsets["dji"].known


def test_batch_dji_and_pixel_on_same_entry():
    # A3: DJI i telefon nagrały ten sam przebieg → oba picked na ten sam wpis
    c = entry(101, BASE, 5.5, 25, idtone_after_stop=26.0)
    others = [entry(102, BASE + 120, 6.0, 30), entry(103, BASE + 240, 6.5, 35)]
    dji = dji_take(BASE, 5.5, 25, tone=IdToneCode(0, 101))
    pxl = pixel_take(BASE - 3, 8.5, 40, tone=IdToneCode(0, 101))
    rep = matching.match_takes([dji, pxl], [c, *others], tz=TZ)
    assert [(a.state, a.entry_id) for a in rep.assignments] == [("picked", 101), ("picked", 101)]


def test_batch_two_dji_files_one_entry_conflict():
    # A4: dwa pliki DJI z tonem tego samego wpisu → słabszy „konflikt"
    c = entry(101, BASE, 5.5, 25)
    strong = dji_take(BASE, 5.5, 25, tone=IdToneCode(0, 101), counter=1)
    weak = dji_take(BASE + 400, None, 90, tone=IdToneCode(0, 101), counter=2)
    rep = matching.match_takes([strong, weak], [c], tz=TZ)
    a, b = rep.assignments
    assert a.state == "picked" and a.entry_id == 101
    assert b.state == "ambiguous" and "konflikt z " + strong.path.name in b.label


def test_batch_conflict_without_clear_winner_both_ambiguous():
    c = entry(101, BASE, 5.5, 25, fields=False)
    t1 = dji_take(BASE, None, 0, tone=IdToneCode(0, 101), counter=1)
    t2 = dji_take(BASE + 30, None, 0, tone=IdToneCode(0, 101), counter=2)
    rep = matching.match_takes([t1, t2], [c], tz=TZ)
    assert [a.state for a in rep.assignments] == ["ambiguous", "ambiguous"]
    assert all("konflikt" in a.label for a in rep.assignments)


def test_batch_locked_assignment_reserves_entry():
    takes, entries = _session(n=2, tones=())
    locked = {takes[0].key: matching.Assignment(takes[0], 102, "picked", source="manual")}
    rep = matching.match_takes(takes, entries, tz=TZ, locked=locked)
    a, b = rep.assignments
    assert a.locked and a.entry_id == 102
    assert b.state == "ambiguous" and "konflikt" in b.label


def test_batch_shot_scorer_breaks_tie():
    shots = "1: 1.00s | 2: 2.00s (+1.00s)"
    c1 = replace(entry(101, BASE, 5.5, 25, fields=False), opis=shots)
    c2 = replace(c1, id=102, opis="1: 3.00s | 2: 7.00s (+4.00s)")
    take = pixel_take(BASE, 5.5, 25)
    seen = {}

    def scorer(t, timelines):
        seen.update(timelines)
        return {101: 4.0, 102: 1.1}

    rep = matching.match_takes([take], [c1, c2], tz=TZ, shot_scorer=scorer)
    assert set(seen) == {101, 102}
    a = rep.assignments[0]
    # beep z zegara timera (połowa punktów) + odcisk 30 — nadal < PICK_MIN
    assert a.state == "ambiguous" and a.top[0][0] == 101


# --- API (O7) -------------------------------------------------------------------

def test_candidate_from_payload_p5_fields_nested_flat_and_old():
    nested = api.candidate_from_payload({
        "id": 1247, "data_zapisu": "2026-09-24 08:21:40",
        "wideo": {"plik": "DJI_20260924102133_????_D.MP4", "rec_start": 1790245293,
                  "rec_stop": 1790245312, "duration_s": 19, "preroll_ms": 5412,
                  "status": "ok", "cam": "FF33-3fa91c02"},
        "idtone": {"played": "db", "value": "1247", "at_ms": 1790245317400},
        "t_beep_ms": 1790245298712, "clock_ok": True, "station_no": 1})
    assert (nested.video_duration_s, nested.video_preroll_ms, nested.video_status,
            nested.video_cam) == (19, 5412, "ok", "FF33-3fa91c02")
    assert (nested.idtone_played, nested.idtone_value, nested.idtone_at_ms) == \
        ("db", "1247", 1790245317400)
    assert (nested.t_beep_ms, nested.clock_ok, nested.station_no) == (1790245298712, True, 1)
    flat = api.candidate_from_payload({
        "id": 5, "data_zapisu": "2026-09-24 08:21:40", "video_duration_s": 19,
        "video_preroll_ms": 0, "video_status": "partial", "video_cam": "FF33-00000000",
        "t_beep_ms": 1790245298712, "clock_ok": 0, "idtone_played": "temp",
        "idtone_value": "30147", "idtone_at_ms": 1, "station_no": 3})
    assert flat.video_preroll_ms == 0 and flat.clock_ok is False and flat.station_no == 3
    old = api.candidate_from_payload({"id": 3, "data_zapisu": "2026-08-12 17:52:12"})
    assert (old.video_duration_s, old.video_preroll_ms, old.t_beep_ms, old.clock_ok,
            old.idtone_played, old.station_no) == (0, None, 0, None, "", 0)
    junk = api.candidate_from_payload({"id": 4, "data_zapisu": "2026-08-12 17:52:12",
                                       "video_preroll_ms": "x", "station_no": 42,
                                       "clock_ok": "maybe", "wideo": None, "idtone": 5})
    assert (junk.video_preroll_ms, junk.station_no, junk.clock_ok) == (None, 0, None)


# --- trwały zapis (O8) ----------------------------------------------------------

def test_assignment_store_sidecar_roundtrip_and_lock(tmp_path):
    video = tmp_path / "DJI_20260924100000_0001_D.MP4"
    video.write_bytes(b"x")
    assert assignment_store.load(video) is None
    assignment_store.save(video, assignment_store.StoredAssignment(None, "ambiguous", "auto", 40,
                                                                   ("przewaga",)))
    rec = assignment_store.load(video)
    assert rec.state == "ambiguous" and not rec.locked
    assert assignment_store.sidecar_path(video).name == "DJI_20260924100000_0001_D.piro-match.json"
    assignment_store.save_manual(video, 1247)
    rec = assignment_store.load(video)
    assert rec.locked and rec.entry_id == 1247 and rec.source == "manual"


def test_assignment_store_falls_back_to_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(assignment_store.config, "config_dir", lambda: tmp_path)
    video = tmp_path / "brak_katalogu" / "clip.mp4"      # katalogu nie ma → zapis nie przejdzie
    where = assignment_store.save(video, assignment_store.StoredAssignment(7, "picked"))
    assert where.parent == tmp_path and assignment_store.load(video).entry_id == 7


def test_match_folders_saves_and_keeps_locked(tmp_path, monkeypatch):
    card, phone = tmp_path / "card", tmp_path / "phone"
    card.mkdir(); phone.mkdir()
    takes, entries = _session(n=2, tones=(0,))
    files = {}
    for t in takes:
        p = card / t.path.name
        p.write_bytes(b"x")
        (card / (t.stem + ".LRF")).write_bytes(b"x")
        files[p.name] = replace(t, path=p, files=(p,))
    pxl = pixel_take(BASE + 120 - 2, 8.7, 45)
    pp = phone / pxl.path.name
    pp.write_bytes(b"x")
    files[pp.name] = replace(pxl, path=pp, files=(pp,))
    calls = []

    def fake_extract(path, group=(), *, tz=None):
        calls.append(Path(path).name)
        return replace(files[Path(path).name], files=tuple(group))

    monkeypatch.setattr(pipeline, "extract_take", fake_extract)
    monkeypatch.setattr(pipeline, "take_for_video",
                        lambda path, **k: replace(files[Path(path).name], tone=None, t0=None))
    rep = pipeline.match_folders([card, phone], tz=TZ, entries=entries)
    by_name = {a.take.path.name: a for a in rep.assignments}
    assert len(rep.assignments) == 3                          # LRF nie jest osobnym ujęciem
    first = by_name[takes[0].path.name]
    assert first.state == "picked" and first.entry_id == 101
    assert len(first.take.files) == 2
    assert assignment_store.load(first.take.path).locked
    # drugi przebieg: zablokowane ujęcia bez ponownej analizy audio
    calls.clear()
    rep2 = pipeline.match_folders([card, phone], tz=TZ, entries=entries)
    assert takes[0].path.name not in calls
    again = {a.take.path.name: a for a in rep2.assignments}[takes[0].path.name]
    assert again.locked and again.entry_id == 101
