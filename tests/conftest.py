"""Wspólne fixture'y testów.

`tiny_video` — realny, 3-sekundowy plik MP4 generowany FFmpeg-iem (lavfi):
obraz testsrc + ton 2700 Hz w oknie 0.5–0.9 s udający bzyczek shot-timera
(pozwala testować detekcję T0 end-to-end, bez mockowania FFmpeg — AGENTS.md).
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
