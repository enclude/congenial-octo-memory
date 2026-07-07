"""Testy dekodera sygnału tonowego ID (`audio_sync.decode_id_tone`).

Audio budowane FFmpeg-iem (lavfi `aevalsrc`, jak `tiny_video` w conftest.py) —
bez mockowania FFmpeg, zgodnie z AGENTS.md.
"""

from __future__ import annotations

import subprocess

import pytest

from piro_overlay import ffmpeg
from piro_overlay.audio_sync import decode_id_tone

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
