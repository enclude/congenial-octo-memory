"""Detekcja punktu odniesienia T0 na osi czasu wideo.

Strategia: wyznaczamy obwiednię energii audio w krótkich oknach, a następnie
szukamy wyraźnych onsetów (gwałtownych wzrostów energii ponad próg adaptacyjny).
Pierwszy silny onset to zwykle sygnał startu (buzzer); kolejne to strzały.

Funkcja zwraca listę kandydatów (czasy w sekundach) posortowaną wg czasu, aby
GUI mogło zaproponować domyślny T0 i pozwolić użytkownikowi wybrać/poprawić.

Kluczowa zasada wydajności: audio jest ekstrahowane z pliku (FFmpeg) dokładnie
RAZ przez _load_audio(). Wszystkie dalsze operacje (waveform, onset detection)
pracują na załadowanych próbkach w pamięci — bez ponownego odczytu dysku.
"""

from __future__ import annotations

import io
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from . import ffmpeg
from .models import AnchorMode

_WINDOW_S = 0.02  # 20 ms okna analizy


# ---------------------------------------------------------------------------
# Warstwa I/O — tylko tutaj trafia FFmpeg + dysk
# ---------------------------------------------------------------------------

def _load_audio(video_path: str | Path) -> tuple[np.ndarray, int]:
    """Ekstrahuje audio z pliku i zwraca (próbki mono float64, sample_rate).

    Jedyne miejsce w module, które wywołuje FFmpeg. Audio trafia przez pipe
    bezpośrednio do pamięci — żaden plik tymczasowy nie jest zapisywany na dysk,
    co eliminuje opóźnienia Windows Defender skanującego pliki w %TEMP%.
    """
    cmd = [
        ffmpeg.ffmpeg_exe(), "-y", "-i", str(video_path),
        "-vn", "-ac", "1", "-ar", "16000",
        "-f", "wav", "pipe:1",
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          creationflags=ffmpeg.CREATE_NO_WINDOW)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Ekstrakcja audio nie powiodła się:\n{proc.stderr[-2000:].decode('utf-8', errors='replace')}")
    samples, sr = sf.read(io.BytesIO(proc.stdout))
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    return samples, int(sr)


# ---------------------------------------------------------------------------
# Obliczenia na próbkach (bez I/O)
# ---------------------------------------------------------------------------

def _waveform_from_samples(samples: np.ndarray, sr: int,
                            n_buckets: int | None = None) -> tuple[list[float], float]:
    """Obwiednia + długość z już załadowanych próbek (bez FFmpeg)."""
    if samples.size == 0:
        return [], 0.0
    duration = samples.size / sr
    if n_buckets is None:
        n_buckets = min(20000, max(2000, int(duration * 200)))
    n = min(n_buckets, samples.size)
    bucket = samples.size // n
    trimmed = np.abs(samples[: n * bucket]).reshape(n, bucket)
    env = trimmed.max(axis=1)
    peak = float(env.max()) or 1.0
    return (env / peak).tolist(), duration


def _onsets_from_samples(samples: np.ndarray, sr: int,
                          min_gap_s: float = 0.15,
                          start: float | None = None,
                          end: float | None = None) -> list[float]:
    """Lista onsetów z już załadowanych próbek (bez FFmpeg)."""
    if samples.size == 0:
        return []

    lo = int(max(start, 0.0) * sr) if start is not None else 0
    hi = int(end * sr) if end is not None else samples.size
    lo = max(0, min(lo, samples.size))
    hi = max(lo, min(hi, samples.size))
    offset_s = lo / sr
    chunk = samples[lo:hi]
    if chunk.size == 0:
        return []

    win = max(1, int(sr * _WINDOW_S))
    n_windows = chunk.size // win
    if n_windows == 0:
        return []

    trimmed = chunk[: n_windows * win].reshape(n_windows, win)
    energy = np.sqrt((trimmed.astype(np.float64) ** 2).mean(axis=1))

    median = np.median(energy)
    mad = np.median(np.abs(energy - median)) + 1e-9
    threshold = median + 6.0 * mad

    onsets: list[float] = []
    last_t = -1e9
    for i in range(1, n_windows):
        if energy[i] >= threshold and energy[i] > energy[i - 1]:
            t = offset_s + i * win / sr
            if t - last_t >= min_gap_s:
                onsets.append(round(t, 3))
                last_t = t
    return onsets


# ---------------------------------------------------------------------------
# Publiczne API
# ---------------------------------------------------------------------------

def analyze_audio(video_path: str | Path) -> tuple[list[float], float, list[float]]:
    """Ładuje audio RAZ i zwraca (obwiednia, długość_s, onsety).

    Używaj tej funkcji w WaveformWorker zamiast oddzielnych compute_waveform
    + detect_onsets — FFmpeg odpala się tylko raz, co dwukrotnie skraca czas
    na Windows (brak ponownego odczytu dysku + brak skanowania AV pliku tmp).
    """
    samples, sr = _load_audio(video_path)
    env, dur = _waveform_from_samples(samples, sr)
    onsets = _onsets_from_samples(samples, sr)
    return env, dur, onsets


def compute_waveform(video_path: str | Path,
                     n_buckets: int | None = None) -> tuple[list[float], float]:
    """Zwraca (obwiednia, długość_s) audio do wizualizacji w GUI."""
    samples, sr = _load_audio(video_path)
    return _waveform_from_samples(samples, sr, n_buckets)


def detect_onsets(video_path: str | Path,
                  min_gap_s: float = 0.15,
                  start: float | None = None,
                  end: float | None = None) -> list[float]:
    """Zwraca czasy (s) wykrytych głośnych onsetów w audio wideo."""
    samples, sr = _load_audio(video_path)
    return _onsets_from_samples(samples, sr, min_gap_s, start, end)


def detect_start(video_path: str | Path,
                 start: float | None = None,
                 end: float | None = None) -> float | None:
    """Zwraca czas pierwszego silnego onsetu (kandydat na sygnał startu)."""
    samples, sr = _load_audio(video_path)
    onsets = _onsets_from_samples(samples, sr, start=start, end=end)
    return onsets[0] if onsets else None


def _bandpass_fft(samples: np.ndarray, sr: int, f_low: float, f_high: float) -> np.ndarray:
    """Zero-phase filtr pasmowy przez FFT. Nie wymaga scipy."""
    n = samples.size
    spec = np.fft.rfft(samples.astype(np.float64))
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    mask = (freqs >= f_low) & (freqs <= f_high)
    spec[~mask] = 0.0
    return np.fft.irfft(spec, n)


def detect_dji_start(video_path: str | Path,
                     start: float | None = None,
                     end: float | None = None) -> float | None:
    """Detekcja bzyczka startu zoptymalizowana pod nagrania DJI.

    Stosuje filtr pasmowy 2000–4500 Hz (pasmo typowego buzzera shot-timera),
    co odrzuca strzały (szeroki spektrum, dużo basu) i szumy tła.
    """
    samples, sr = _load_audio(video_path)

    lo = int(max(start, 0.0) * sr) if start is not None else 0
    hi = int(end * sr) if end is not None else samples.size
    lo = max(0, min(lo, samples.size))
    hi = max(lo, min(hi, samples.size))
    offset_s = lo / sr
    chunk = samples[lo:hi]
    if chunk.size == 0:
        return None

    chunk = _bandpass_fft(chunk, sr, 2000, 4500)

    # Dłuższe okno (50 ms) — bzyczek to sygnał ciągły, nie impuls.
    win = max(1, int(sr * 0.05))
    n_windows = chunk.size // win
    if n_windows == 0:
        return None

    trimmed = chunk[:n_windows * win].reshape(n_windows, win)
    energy = np.sqrt((trimmed.astype(np.float64) ** 2).mean(axis=1))

    median = np.median(energy)
    mad = np.median(np.abs(energy - median)) + 1e-9
    threshold = median + 5.0 * mad

    for i in range(1, n_windows):
        if energy[i] >= threshold and energy[i] > energy[i - 1]:
            return round(offset_s + i * win / sr, 3)
    return None


def resolve_t0(anchor_time: float, mode: AnchorMode, first_shot_time: float) -> float:
    """Przelicza wykryty/wskazany punkt kotwicy na T0 (czas sygnału startu).

    START_SIGNAL — kotwica jest już sygnałem startu → T0 = anchor_time.
    FIRST_SHOT   — kotwica to pierwszy strzał → T0 = anchor_time − first_shot_time.
    """
    if mode == AnchorMode.START_SIGNAL:
        return anchor_time
    return anchor_time - first_shot_time
