import pytest

from piro_overlay.parser import TimelineParseError, parse_timeline

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
