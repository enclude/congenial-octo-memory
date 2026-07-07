"""Wspólne fixture'y testów.

`tiny_video` — realny, 3-sekundowy plik MP4 generowany FFmpeg-iem (lavfi):
obraz testsrc + ton 2700 Hz w oknie 0.5–0.9 s udający bzyczek shot-timera
(pozwala testować detekcję T0 end-to-end, bez mockowania FFmpeg — AGENTS.md).

`id_tone_video` — jak wyżej, ale z sygnałem tonowym ID (marker + 4 cyfry,
patrz `audio_sync.decode_id_tone`) w ścieżce audio — do testów end-to-end
dekodowania ID z audio (endpoint `/detect-id`, GUI „Wykryj ID z audio”).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# Repo-root na sys.path — testy web importują pakiet `web` (obok `src`).
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from piro_overlay import ffmpeg  # noqa: E402
from piro_overlay.audio_sync import (  # noqa: E402
    _ID_TONE_DIGIT_FREQS,
    _ID_TONE_MARKER_FREQ,
    _ID_TONE_SLOT,
    _ID_TONE_TONE_DUR,
)

ID_TONE_TEST_ID = 4821
_ID_TONE_REPEAT_GAP = 0.3


def id_tone_expr(session_id: int, repeats: int = 2, amp: float = 0.8) -> tuple[str, float]:
    """Wyrażenie `aevalsrc` grające `session_id` protokołem decode_id_tone.

    Zwraca (wyrażenie, czas_trwania_s) — harmonogram MUSI się zgadzać ze
    stałymi `_ID_TONE_*` w `audio_sync.py` (marker + N cyfr, ten sam slot).
    """
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
        t0 += _ID_TONE_SLOT * (len(digits) + 1) + _ID_TONE_REPEAT_GAP
    return "+".join(terms), t0


@pytest.fixture(scope="session")
def tiny_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("video") / "tiny.mp4"
    # Apostrofy chronią przecinki wyrażenia przed parserem filtergraphu.
    tone = "aevalsrc='if(between(t,0.5,0.9),0.8*sin(2*PI*2700*t),0)':s=44100:d=3"
    cmd = [
        ffmpeg.ffmpeg_exe(), "-y",
        "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=30",
        "-f", "lavfi", "-i", tone,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-shortest", str(out),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        pytest.skip(f"FFmpeg nie zbudował pliku testowego: {res.stderr[-500:]}")
    return out


@pytest.fixture(scope="session")
def id_tone_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("video") / "id_tone.mp4"
    expr, dur = id_tone_expr(ID_TONE_TEST_ID)
    tone = f"aevalsrc='{expr}':s=44100:d={dur + 0.3:.2f}"
    cmd = [
        ffmpeg.ffmpeg_exe(), "-y",
        "-f", "lavfi", "-i", f"testsrc=duration={dur + 0.3:.2f}:size=320x240:rate=30",
        "-f", "lavfi", "-i", tone,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-shortest", str(out),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        pytest.skip(f"FFmpeg nie zbudował pliku testowego: {res.stderr[-500:]}")
    return out
