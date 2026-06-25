"""Detekcja punktu odniesienia T0 na osi czasu wideo.

Strategia: wyznaczamy obwiednię energii audio w krótkich oknach, a następnie
szukamy wyraźnych onsetów (gwałtownych wzrostów energii ponad próg adaptacyjny).
Pierwszy silny onset to zwykle sygnał startu (buzzer); kolejne to strzały.

Funkcja zwraca listę kandydatów (czasy w sekundach) posortowaną wg czasu, aby
GUI mogło zaproponować domyślny T0 i pozwolić użytkownikowi wybrać/poprawić.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from . import ffmpeg
from .models import AnchorMode

_WINDOW_S = 0.02  # 20 ms okna analizy


def detect_onsets(video_path: str | Path,
                  min_gap_s: float = 0.15,
                  start: float | None = None,
                  end: float | None = None) -> list[float]:
    """Zwraca czasy (s) wykrytych głośnych onsetów w audio wideo.

    min_gap_s — minimalny odstęp między onsetami, by nie liczyć jednego
    zdarzenia wielokrotnie.
    start / end — opcjonalne okno (s) ograniczające zakres analizy; onsety poza
    nim są pomijane. Próg energii liczony jest tylko z próbek w oknie, aby cichy
    fragment poza strzelaniem nie zaniżał detekcji.
    """
    with tempfile.TemporaryDirectory() as tmp:
        wav = ffmpeg.extract_audio(video_path, Path(tmp) / "audio.wav")
        samples, sr = sf.read(str(wav))

    if samples.ndim > 1:  # na wszelki wypadek miksuj do mono
        samples = samples.mean(axis=1)
    if samples.size == 0:
        return []

    # Ogranicz analizę do okna [start, end] (jeśli podane).
    lo = int(max(start, 0.0) * sr) if start is not None else 0
    hi = int(end * sr) if end is not None else samples.size
    lo = max(0, min(lo, samples.size))
    hi = max(lo, min(hi, samples.size))
    offset_s = lo / sr
    samples = samples[lo:hi]
    if samples.size == 0:
        return []

    win = max(1, int(sr * _WINDOW_S))
    n_windows = samples.size // win
    if n_windows == 0:
        return []

    trimmed = samples[: n_windows * win].reshape(n_windows, win)
    energy = np.sqrt((trimmed.astype(np.float64) ** 2).mean(axis=1))  # RMS na okno

    # Próg adaptacyjny: mediana + k * odchylenie. Onset = przekroczenie progu
    # przy jednoczesnym wzroście względem poprzedniego okna (zbocze narastające).
    median = np.median(energy)
    mad = np.median(np.abs(energy - median)) + 1e-9
    threshold = median + 6.0 * mad

    onsets: list[float] = []
    last_t = -1e9
    for i in range(1, n_windows):
        if energy[i] >= threshold and energy[i] > energy[i - 1]:
            t = offset_s + i * win / sr  # czas względem całego wideo
            if t - last_t >= min_gap_s:
                onsets.append(round(t, 3))
                last_t = t
    return onsets


def compute_waveform(video_path: str | Path,
                     n_buckets: int | None = None) -> tuple[list[float], float]:
    """Zwraca (obwiednia, długość_s) audio do wizualizacji w GUI.

    Obwiednia to lista wartości 0–1 (znormalizowana amplituda szczytowa w kolejnych
    równych przedziałach czasu). Domyślnie rozdzielczość dobiera się do długości
    (~200 pkt/s, do 20000), żeby zoom pokazywał szczegóły potrzebne do trafienia T0/T1.
    """
    with tempfile.TemporaryDirectory() as tmp:
        wav = ffmpeg.extract_audio(video_path, Path(tmp) / "audio.wav")
        samples, sr = sf.read(str(wav))

    if samples.ndim > 1:
        samples = samples.mean(axis=1)
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


def detect_start(video_path: str | Path,
                 start: float | None = None,
                 end: float | None = None) -> float | None:
    """Zwraca czas pierwszego silnego onsetu (kandydat na sygnał startu).

    Detekcja może być ograniczona do okna [start, end] — przydatne, gdy nagranie
    zawiera dużo materiału poza samym strzelaniem.
    """
    onsets = detect_onsets(video_path, start=start, end=end)
    return onsets[0] if onsets else None


def resolve_t0(anchor_time: float, mode: AnchorMode, first_shot_time: float) -> float:
    """Przelicza wykryty/wskazany punkt kotwicy na T0 (czas sygnału startu).

    START_SIGNAL — kotwica jest już sygnałem startu → T0 = anchor_time.
    FIRST_SHOT   — kotwica to pierwszy strzał → T0 = anchor_time − first_shot_time.
    """
    if mode == AnchorMode.START_SIGNAL:
        return anchor_time
    return anchor_time - first_shot_time
