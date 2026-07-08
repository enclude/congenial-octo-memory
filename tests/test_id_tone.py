"""Testy dekodera sygnału tonowego ID (`audio_sync.decode_id_tone`).

Audio budowane FFmpeg-iem (lavfi `aevalsrc`, jak `tiny_video` w conftest.py) —
bez mockowania FFmpeg, zgodnie z AGENTS.md.
"""

from __future__ import annotations

import subprocess

import pytest

from piro_overlay import ffmpeg
from piro_overlay.audio_sync import _ID_TONE_SLOT, _ID_TONE_TONE_DUR, decode_id_tone

from conftest import id_tone_expr as _id_tone_expr


def _render_wav(tmp_path, expr: str, duration: float):
    out = tmp_path / "id_tone.wav"
    cmd = [
        ffmpeg.ffmpeg_exe(), "-y",
        "-f", "lavfi", "-i", f"aevalsrc='{expr}':s=44100:d={duration:.2f}",
        str(out),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        pytest.skip(f"FFmpeg nie zbudował pliku testowego: {res.stderr[-500:]}")
    return out


def test_decode_id_tone_roundtrip(tmp_path):
    expr, dur = _id_tone_expr(4821)
    wav = _render_wav(tmp_path, expr, dur + 0.3)
    assert decode_id_tone(wav) == 4821


def test_decode_id_tone_leading_zero(tmp_path):
    expr, dur = _id_tone_expr(37)  # -> "0037"
    wav = _render_wav(tmp_path, expr, dur + 0.3)
    assert decode_id_tone(wav) == 37


def test_decode_id_tone_single_pass_still_decodes(tmp_path):
    expr, dur = _id_tone_expr(9999, repeats=1)
    wav = _render_wav(tmp_path, expr, dur + 0.3)
    assert decode_id_tone(wav) == 9999


def test_decode_id_tone_no_marker_returns_none(tmp_path):
    # Cisza — brak jakiegokolwiek markera.
    wav = _render_wav(tmp_path, "0", 2.0)
    assert decode_id_tone(wav) is None


def test_decode_id_tone_weak_digit_relative_dominance(tmp_path):
    # Cicha cyfra + równoczesny przydźwięk 300 Hz (poza wszystkimi pasmami
    # kandydatów) podbija energię całkowitą okna → koncentracja ~0.45, poniżej
    # progu bezwzględnego 0.55 — jak realne nagranie z odległego telefonu.
    # Dominacja względna musi ją mimo to odczytać (pozostałe pasma mają ~0).
    expr, dur = _id_tone_expr(4821, repeats=1, slot_amps={3: 0.3})
    start = _ID_TONE_SLOT * 4
    hum = (f"+if(between(t,{start:.3f},{start + _ID_TONE_TONE_DUR:.3f}),"
           f"0.33*sin(2*PI*300*t),0)")
    wav = _render_wav(tmp_path, expr + hum, dur + 0.3)
    assert decode_id_tone(wav) == 4821


def test_decode_id_tone_per_slot_voting(tmp_path):
    # Żadne powtórzenie nie jest kompletne (w każdym wycięty inny slot),
    # więc pojedynczy marker nie da pełnego odczytu — głosowanie per-slot
    # musi złożyć ID z obu powtórzeń.
    expr, dur = _id_tone_expr(4821, repeats=2, skip_slots=((0, 2), (1, 0)))
    wav = _render_wav(tmp_path, expr, dur + 0.3)
    assert decode_id_tone(wav) == 4821


def test_decode_id_tone_bad_checksum_rejected(tmp_path):
    # Sygnał czysty i w pełni czytelny, ale cyfra kontrolna celowo błędna —
    # dekoder MUSI odrzucić odczyt (błędne ID pobrałoby cudzą sesję z API).
    expr, dur = _id_tone_expr(4821, checksum_offset=3)
    wav = _render_wav(tmp_path, expr, dur + 0.3)
    assert decode_id_tone(wav) is None


def test_decode_id_tone_missing_checksum_slot_rejected(tmp_path):
    # Brak odczytu w slocie cyfry kontrolnej (wyciszony w obu powtórzeniach)
    # = brak weryfikacji = None, nawet gdy 4 cyfry danych czytają się czysto.
    expr, dur = _id_tone_expr(4821, repeats=2, skip_slots=((0, 4), (1, 4)))
    wav = _render_wav(tmp_path, expr, dur + 0.3)
    assert decode_id_tone(wav) is None
