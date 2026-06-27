"""Dostęp do FFmpeg/FFprobe oraz pomocnicze operacje na wideo.

FFmpeg pochodzi z `imageio-ffmpeg` (binarka dostarczana z pakietem), więc nie
wymagamy instalacji FFmpeg w systemie. FFprobe nie jest częścią imageio-ffmpeg,
dlatego metadane (fps, długość, rozdzielczość) czytamy parsując stderr `ffmpeg -i`,
co działa wszędzie tam, gdzie mamy samego ffmpega.
"""

from __future__ import annotations

import functools
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import imageio_ffmpeg

# Na Windows uruchamianie ffmpeg/ffprobe bez tej flagi powoduje miganie okna
# konsoli przy każdym wywołaniu (podgląd, waveform, detekcja). Ukrywamy okno.
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


@dataclass
class VideoInfo:
    duration: float
    fps: float
    width: int
    height: int


def _has_nvenc_binary(path: str) -> bool:
    try:
        return "h264_nvenc" in _run([path, "-hide_banner", "-encoders"]).stdout
    except Exception:  # noqa: BLE001
        return False


@functools.lru_cache(maxsize=1)
def _resolve_ffmpeg() -> str:
    """Wybiera binarkę ffmpeg, unikając wyciągania pliku przez imageio-ffmpeg.

    Kolejność: 1) env PIRO_FFMPEG, 2) pełny ffmpeg dołączony do paczki (assets/bin),
    3) systemowy ffmpeg z PATH, 4) binarka z imageio-ffmpeg (ostateczność — wyciąga
    plik do %TEMP% przy każdym starcie procesu, co na Windows powoduje skan Defendera).
    Obsługa NVENC sprawdzana jest osobno przez has_nvenc() w render.py.
    """
    import os
    from . import resources

    env = os.environ.get("PIRO_FFMPEG")
    if env and Path(env).exists():
        return env

    bundled_full = resources.bundled_ffmpeg_path()
    if bundled_full:
        return bundled_full

    sys_ff = shutil.which("ffmpeg")
    if sys_ff:
        return sys_ff

    # Ostateczność: imageio-ffmpeg wyciąga binarki do %TEMP% przy pierwszym wywołaniu.
    # W .exe (PyInstaller) Defender skanuje plik → wielosekundowe opóźnienie.
    return imageio_ffmpeg.get_ffmpeg_exe()


def ffmpeg_exe() -> str:
    """Ścieżka do binarki ffmpeg (systemowa z NVENC lub dołączona z imageio-ffmpeg)."""
    return _resolve_ffmpeg()


def ffprobe_exe() -> str | None:
    """Ścieżka do ffprobe, jeśli dostępny w PATH (opcjonalny)."""
    return shutil.which("ffprobe")


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True,
                          creationflags=CREATE_NO_WINDOW)


@functools.lru_cache(maxsize=1)
def available_encoders() -> frozenset[str]:
    """Zbiór nazw enkoderów dostępnych w binarce ffmpeg (cache)."""
    res = _run([ffmpeg_exe(), "-hide_banner", "-encoders"])
    names = re.findall(r"^\s*[A-Z.]{6}\s+(\S+)", res.stdout, re.MULTILINE)
    return frozenset(names)


def has_nvenc() -> bool:
    """Czy binarka ffmpeg ma enkoder NVIDIA NVENC (h264_nvenc)."""
    return "h264_nvenc" in available_encoders()


def probe(video_path: str | Path) -> VideoInfo:
    """Zwraca podstawowe metadane wideo. Najpierw próbuje ffprobe, potem ffmpeg."""
    video_path = str(video_path)
    probe_exe = ffprobe_exe()
    if probe_exe:
        info = _probe_with_ffprobe(probe_exe, video_path)
        if info is not None:
            return info
    return _probe_with_ffmpeg(video_path)


def _probe_with_ffprobe(probe_exe: str, video_path: str) -> VideoInfo | None:
    cmd = [
        probe_exe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,avg_frame_rate:format=duration",
        "-of", "json", video_path,
    ]
    res = _run(cmd)
    if res.returncode != 0:
        return None
    try:
        data = json.loads(res.stdout)
        stream = data["streams"][0]
        num, den = stream["avg_frame_rate"].split("/")
        fps = float(num) / float(den) if float(den) else 0.0
        return VideoInfo(
            duration=float(data["format"]["duration"]),
            fps=fps,
            width=int(stream["width"]),
            height=int(stream["height"]),
        )
    except (KeyError, IndexError, ValueError, ZeroDivisionError):
        return None


_DUR_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)")
_RES_RE = re.compile(r"\b(\d{2,5})x(\d{2,5})\b")
_FPS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*fps")


def _probe_with_ffmpeg(video_path: str) -> VideoInfo:
    # `ffmpeg -i` bez wyjścia kończy się błędem, ale wypisuje metadane na stderr.
    res = _run([ffmpeg_exe(), "-i", video_path])
    text = res.stderr

    dm = _DUR_RE.search(text)
    if dm:
        h, m, s = dm.groups()
        duration = int(h) * 3600 + int(m) * 60 + float(s)
    else:
        duration = 0.0

    # Analizujemy tylko pierwszą linię ze strumieniem wideo, aby uniknąć
    # przypadkowych dopasowań (np. fragmentów innych metadanych).
    video_line = next((ln for ln in text.splitlines() if "Video:" in ln), "")
    width = height = 0
    fps = 0.0
    rm = _RES_RE.search(video_line)
    if rm:
        width, height = int(rm.group(1)), int(rm.group(2))
    fm = _FPS_RE.search(video_line)
    if fm:
        fps = float(fm.group(1))

    return VideoInfo(duration=duration, fps=fps, width=width, height=height)


def extract_audio(video_path: str | Path, out_wav: str | Path,
                  sample_rate: int = 16000) -> Path:
    """Ekstrahuje audio do mono WAV (do detekcji T0)."""
    out_wav = Path(out_wav)
    cmd = [
        ffmpeg_exe(), "-y", "-i", str(video_path),
        "-vn", "-ac", "1", "-ar", str(sample_rate),
        "-f", "wav", str(out_wav),
    ]
    res = _run(cmd)
    if res.returncode != 0:
        raise RuntimeError(f"Ekstrakcja audio nie powiodła się:\n{res.stderr[-2000:]}")
    return out_wav


def find_lrf(video_path: str | Path) -> Path | None:
    """Szuka niskorozdzielczego proxy LRF obok pliku MP4 (DJI Osmo).

    Kamery DJI nagrywają obok każdego MP4 plik .LRF (ten sam obraz i audio,
    ~480p). Jeśli istnieje i ffmpeg może go odczytać, zwraca jego ścieżkę
    — można go użyć do analizy audio zamiast pełnego pliku, co znacznie
    przyspiesza detekcję T0 i generowanie waveformy dla dużych nagrań 4K.
    Zwraca None jeśli plik nie istnieje lub jest nieczytelny dla ffmpeg.
    """
    p = Path(video_path)
    for suffix in (".LRF", ".lrf"):
        candidate = p.with_suffix(suffix)
        if candidate.exists():
            try:
                probe(candidate)
                return candidate
            except Exception:  # noqa: BLE001
                pass
    return None


def extract_frame(video_path: str | Path, timestamp: float, out_png: str | Path,
                  scale_height: int | None = None) -> Path:
    """Zapisuje pojedynczą klatkę wideo w danym czasie (do podglądu w GUI).

    scale_height — opcjonalna wysokość docelowa (px); klatka jest proporcjonalnie
    pomniejszana, co przyspiesza i odciąża podgląd dużych plików.
    """
    out_png = Path(out_png)
    cmd = [
        ffmpeg_exe(), "-y", "-ss", f"{max(timestamp, 0):.3f}",
        "-i", str(video_path), "-frames:v", "1",
    ]
    if scale_height:
        cmd += ["-vf", f"scale=-2:{int(scale_height)}"]
    cmd.append(str(out_png))
    res = _run(cmd)
    if res.returncode != 0:
        raise RuntimeError(f"Pobranie klatki nie powiodło się:\n{res.stderr[-2000:]}")
    return out_png
