import pytest

from piro_overlay.models import Shot
from piro_overlay.parser import (
    TimelineParseError,
    delete_shot,
    extract_start_delay,
    format_timeline,
    move_shot,
    parse_timeline,
    renumber,
)

SAMPLE_23 = (
    "1: 2.81s | 2: 4.63s (+1.82s) | 3: 6.28s (+1.65s) | 4: 7.81s (+1.53s) | "
    "5: 10.39s (+2.58s) | 6: 13.19s (+2.80s) | 7: 15.28s (+2.09s) | 8: 17.71s (+2.43s) | "
    "9: 19.15s (+1.44s) | 10: 20.87s (+1.72s) | 11: 25.91s (+5.04s) | 12: 28.27s (+2.36s) | "
    "13: 35.19s (+6.92s) | 14: 36.97s (+1.78s) | 15: 39.24s (+2.27s) | 16: 41.03s (+1.79s) | "
    "17: 43.14s (+2.11s) | 18: 44.77s (+1.63s) | 19: 46.37s (+1.60s) | 20: 49.84s (+3.47s) | "
    "21: 51.12s (+1.28s) | 22: 53.60s (+2.48s) | 23: 55.68s (+2.08s)"
)

# Przykład z pola `opis` API (6 strzałów, duży skok +8.16s).
SAMPLE_OPIS = (
    "1: 1.55s | 2: 2.16s (+0.61s) | 3: 2.55s (+0.39s) | 4: 3.08s (+0.53s) | "
    "5: 11.24s (+8.16s) | 6: 12.49s (+1.25s)"
)


def test_parse_full_timeline():
    shots = parse_timeline(SAMPLE_23)
    assert len(shots) == 23
    assert shots[0].numer == 1
    assert shots[0].czas == 2.81
    assert shots[0].split is None  # pierwszy strzał bez splitu
    assert shots[1].split == 1.82
    assert shots[-1].czas == 55.68


def test_parse_opis_with_big_gap():
    shots = parse_timeline(SAMPLE_OPIS)
    assert len(shots) == 6
    assert shots[4].split == 8.16
    assert shots[4].czas == 11.24


def test_empty_raises():
    with pytest.raises(TimelineParseError):
        parse_timeline("   ")


def test_bad_token_raises():
    with pytest.raises(TimelineParseError):
        parse_timeline("1: 2.81s | foo bar")


def test_non_contiguous_numbering_raises():
    with pytest.raises(TimelineParseError):
        parse_timeline("1: 1.0s | 3: 2.0s (+1.0s)")


def test_decreasing_time_raises():
    with pytest.raises(TimelineParseError):
        parse_timeline("1: 5.0s | 2: 3.0s (+1.0s)")


def test_extract_start_delay_strips_prefix():
    rest, delay = extract_start_delay(
        "opoznienie startu 2.1s | 1: 2.28s | 2: 2.76s (+0.48s)")
    assert delay == 2.1
    assert rest == "1: 2.28s | 2: 2.76s (+0.48s)"
    assert parse_timeline(rest)[1].split == 0.48


def test_extract_start_delay_no_prefix_returns_none():
    text = "1: 1.0s | 2: 2.5s (+1.5s)"
    rest, delay = extract_start_delay(text)
    assert delay is None
    assert rest == text


def test_extract_start_delay_empty_text():
    rest, delay = extract_start_delay("")
    assert delay is None
    assert rest == ""


def test_format_timeline_roundtrip():
    text = "1: 2.81s | 2: 4.63s (+1.82s) | 3: 6.28s (+1.65s)"
    shots = parse_timeline(text)
    assert format_timeline(shots) == text
    assert parse_timeline(format_timeline(shots)) == shots


def test_format_timeline_recomputes_splits_and_numbers():
    # Strzał wstawiony w środek: numery i splity liczone od nowa z czasów.
    shots = [Shot(numer=1, czas=1.0), Shot(numer=9, czas=1.5, split=99.0),
             Shot(numer=2, czas=2.25, split=None)]
    assert format_timeline(shots) == "1: 1.00s | 2: 1.50s (+0.50s) | 3: 2.25s (+0.75s)"


def test_format_timeline_single_shot_has_no_split():
    assert format_timeline([Shot(numer=1, czas=0.9)]) == "1: 0.90s"


# --- edycja strzałów na osi (v0.54.0) ---

def test_move_shot_keeps_order_and_recomputes_splits():
    shots = parse_timeline("1: 1.00s | 2: 2.00s (+1.00s) | 3: 3.00s (+1.00s)")
    out = move_shot(shots, 1, 2.5)
    assert [sh.czas for sh in out] == [1.0, 2.5, 3.0]
    assert format_timeline(out) == "1: 1.00s | 2: 2.50s (+1.50s) | 3: 3.00s (+0.50s)"
    assert parse_timeline(format_timeline(out)) == out


def test_move_shot_past_neighbour_resorts_and_renumbers():
    shots = parse_timeline("1: 1.00s | 2: 2.00s (+1.00s) | 3: 3.00s (+1.00s)")
    out = move_shot(shots, 0, 2.5)   # pierwszy strzał przeskakuje drugi
    assert [sh.numer for sh in out] == [1, 2, 3]
    assert [sh.czas for sh in out] == [2.0, 2.5, 3.0]
    assert parse_timeline(format_timeline(out)) == out


def test_move_shot_does_not_mutate_input():
    shots = parse_timeline("1: 1.00s | 2: 2.00s (+1.00s)")
    before = list(shots)
    move_shot(shots, 0, 0.5)
    assert shots == before


def test_move_shot_rejects_negative_time_and_bad_index():
    shots = parse_timeline("1: 1.00s | 2: 2.00s (+1.00s)")
    with pytest.raises(TimelineParseError):
        move_shot(shots, 0, -0.01)
    with pytest.raises(IndexError):
        move_shot(shots, 2, 1.0)


def test_delete_shot_renumbers_rest():
    shots = parse_timeline("1: 1.00s | 2: 2.00s (+1.00s) | 3: 3.50s (+1.50s)")
    out = delete_shot(shots, 1)
    assert format_timeline(out) == "1: 1.00s | 2: 3.50s (+2.50s)"
    assert [sh.numer for sh in out] == [1, 2]
    assert parse_timeline(format_timeline(out)) == out


def test_delete_shot_last_one_gives_empty_list():
    assert delete_shot([Shot(numer=1, czas=1.0)], 0) == []


def test_delete_shot_bad_index():
    with pytest.raises(IndexError):
        delete_shot([Shot(numer=1, czas=1.0)], 1)


def test_renumber_sorts_and_clears_first_split():
    out = renumber([Shot(numer=7, czas=2.0, split=9.0), Shot(numer=3, czas=0.5)])
    assert [(sh.numer, sh.czas, sh.split) for sh in out] == [(1, 0.5, None), (2, 2.0, 1.5)]
