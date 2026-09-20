"""Testy regexów parsujących wyjście FFmpeg (na stałych stringach, bez binarki)."""

from __future__ import annotations

from piro_overlay import ffmpeg

# Reprezentatywne fragmenty rzeczywistego wyjścia `ffmpeg -hide_banner …`.
_ENCODERS_OUT = """\
Encoders:
 V..... = Video
 ------
 V....D libx264              libx264 H.264 / AVC / MPEG-4 AVC
 V....D h264_nvenc           NVIDIA NVENC H.264 encoder (codec h264)
 A....D aac                  AAC (Advanced Audio Coding)
"""

_FILTERS_OUT = """\
Filters:
  T.. = Timeline support
 ... acompressor      A->A       Audio compressor.
 T.C drawtext         V->V       Draw text on top of video frames using libfreetype library.
 ... overlay          VV->V      Overlay a video source on top of the input.
 ... concat           N->N       Concatenate audio and video streams.
"""

_FFMPEG_I_STDERR = """\
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'in.mp4':
  Duration: 00:01:15.48, start: 0.000000, bitrate: 44840 kb/s
  Stream #0:0[0x1](und): Video: hevc (Main) (hvc1 / 0x31637668), yuvj420p(pc, bt709), 3840x2160 [SAR 1:1 DAR 16:9], 44487 kb/s, 29.97 fps, 29.97 tbr, 30k tbn (default)
  Stream #0:1[0x2](und): Audio: aac (LC) (mp4a / 0x6134706D), 48000 Hz, stereo, fltp, 317 kb/s (default)
"""


def test_encoder_regex_finds_nvenc():
    names = set(ffmpeg._ENCODER_RE.findall(_ENCODERS_OUT))
    assert {"libx264", "h264_nvenc", "aac"} <= names


def test_filter_regex_finds_drawtext():
    # Znana pułapka: kolumna flag ma 2–3 znaki — regex nie może zakładać stałych 3,
    # bo wtedy `drawtext` (flagi `T.C`) wypadał z listy → fallback PNG zamiast drawtext.
    names = set(ffmpeg._FILTER_RE.findall(_FILTERS_OUT))
    assert "drawtext" in names
    assert {"acompressor", "overlay", "concat"} <= names


def test_duration_regex():
    h, m, s = ffmpeg._DUR_RE.search(_FFMPEG_I_STDERR).groups()
    assert int(h) * 3600 + int(m) * 60 + float(s) == 75.48


def test_resolution_and_fps_regex_on_video_line():
    video_line = next(ln for ln in _FFMPEG_I_STDERR.splitlines() if "Video:" in ln)
    rm = ffmpeg._RES_RE.search(video_line)
    assert (int(rm.group(1)), int(rm.group(2))) == (3840, 2160)
    fm = ffmpeg._FPS_RE.search(video_line)
    assert float(fm.group(1)) == 29.97


def test_creation_time_regex_on_ffmpeg_stderr():
    from piro_overlay.ffmpeg import _CREATION_RE
    text = ("  Metadata:\n    creation_time   : 2026-07-07T16:06:24.000000Z\n"
            "  Duration: 00:00:33.00, start: 0.000000, bitrate: 66708 kb/s\n"
            "    Stream #0:0: Video: hevc, 3840x2880, 50 fps\n"
            "    Metadata:\n      creation_time   : 2026-07-07T16:06:25.000000Z\n")
    assert _CREATION_RE.search(text).group(1) == "2026-07-07T16:06:24.000000Z"


def test_probe_reports_empty_creation_time_for_synthetic_video(tiny_video):
    from piro_overlay import ffmpeg
    info = ffmpeg.probe(tiny_video)
    assert info.duration > 0
    assert info.creation_time == ""   # lavfi nie zapisuje tagu — pole istnieje i jest puste


def test_rotated_size_and_regexes_swap_portrait_phone_video():
    from piro_overlay.ffmpeg import _DISPLAYMATRIX_RE, _ROTATE_TAG_RE, _rotated_size
    assert _rotated_size(1920, 1080, -90.0) == (1080, 1920)
    assert _rotated_size(1920, 1080, 270) == (1080, 1920)
    assert _rotated_size(1920, 1080, 180) == (1920, 1080)
    assert _rotated_size(1920, 1080, 0) == (1920, 1080)
    text = ("    Stream #0:0[0x1](eng): Video: hevc (Main), yuvj420p, 1920x1080, 29.97 fps\n"
            "      Side data:\n        displaymatrix: rotation of -90.00 degrees\n")
    assert float(_DISPLAYMATRIX_RE.search(text).group(1)) == -90.0
    assert _ROTATE_TAG_RE.search("    Metadata:\n      rotate          : 90\n").group(1) == "90"
