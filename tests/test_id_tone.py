"""Testy dekodera sygnału tonowego ID (`audio_sync.decode_id_tone`).

Audio budowane FFmpeg-iem (lavfi `aevalsrc`, jak `tiny_video` w conftest.py) —
bez mockowania FFmpeg, zgodnie z AGENTS.md.
"""

from __future__ import annotations

import subprocess

import pytest

from piro_overlay import ffmpeg
from piro_overlay.audio_sync import (
    _ID_TONE_DIGIT_FREQS,
    _ID_TONE_MARKER_FREQ,
    _ID_TONE_SLOT,
    _ID_TONE_TONE_DUR,
    decode_id_tone,
)

_REPEAT_GAP = 0.3


def _id_tone_expr(session_id: int, repeats: int = 2, amp: float = 0.8) -> str:
    digits = f"{session_id:04d}"
    terms = []
    t0 = 0.0
    for _ in range(repeats):
        terms.append(f"if(between(t,{t0:.3f},{t0 + _ID_TONE_TONE_DUR:.3f}),"
                     f"{amp}*sin(2*PI*{_ID_TONE_MARKER_FREQ}*t),0)")
        for slot, ch in enumerate(digits):
            freq = _ID_TONE_DIGIT_FREQS[int(ch)]
            start = t0 + _ID_TONE_SLOT * (slot + 1)
            terms.append(f"if(between(t,{start:.3f},{start + _ID_TONE_TONE_DUR:.3f}),"
                         f"{amp}*sin(2*PI*{freq}*t),0)")
        t0 += _ID_TONE_SLOT * (len(digits) + 1) + _REPEAT_GAP
    return "+".join(terms), t0


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
