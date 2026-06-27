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
import struct
import subprocess
from pathlib import Path

import numpy as np

from . import ffmpeg
from .models import AnchorMode

_WINDOW_S = 0.02  # 20 ms okna analizy


# ---------------------------------------------------------------------------
# Warstwa I/O — tylko tutaj trafia FFmpeg + dysk
# ---------------------------------------------------------------------------

def _parse_pcm_wav(data: bytes) -> tuple[np.ndarray, int]:
    """Parsuje bajty WAV PCM (int16) z FFmpega bez libsndfile — tylko numpy.

    FFmpeg z `-f wav -ac 1 -ar N` zawsze generuje standardowy RIFF/PCM WAV.
    Omijamy soundfile/libsndfile, które w PyInstaller wymagają wyciągnięcia DLL
    do %TEMP% i wywołują skanowanie Windows Defender.
    """
    if len(data) < 12 or data[:4] != b'RIFF' or data[8:12] != b'WAVE':
        raise RuntimeError("Nieoczekiwany format audio (oczekiwano RIFF/WAVE)")

    sr = 16000   # fallback — nadpisany z fmt chunk poniżej
    i = 12
    while i + 8 <= len(data):
        chunk_id = data[i:i+4]
        chunk_size = struct.unpack_from('<I', data, i + 4)[0]
        if chunk_id == b'fmt ':
            sr = struct.unpack_from('<I', data, i + 12)[0]
        elif chunk_id == b'data':
            raw = np.frombuffer(data[i+8:i+8+chunk_size], dtype=np.int16)
            return raw.astype(np.float64) / 32768.0, sr
        i += 8 + chunk_size

    raise RuntimeError("Nie znaleziono danych PCM w strumieniu WAV")


def _load_audio(video_path: str | Path) -> tuple[np.ndarray, int]:
    """Ekstrahuje audio z pliku i zwraca (próbki mono float64, sample_rate).

    Dane płyną przez pipe bezpośrednio do RAM; żaden plik tymczasowy nie trafia
    na dysk. WAV parsowany jest przez _parse_pcm_wav (numpy) bez libsndfile,
    co eliminuje wyciąganie DLL przez PyInstaller i skanowanie Windows Defender.
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
            f"Ekstrakcja audio nie powiodła się:\n"
            f"{proc.stderr[-2000:].decode('utf-8', errors='replace')}")
    return _parse_pcm_wav(proc.stdout)


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


_BUZZER_BAND = (2000.0, 4500.0)   # pasmo typowego buzzera shot-timera
_BUZZER_CONC_MIN = 0.7            # min. udział energii w paśmie (tonalność)
_BUZZER_MIN_RUN = 3              # min. liczba okien 50 ms (≥150 ms ciągłego tonu)
_BUZZER_FLOOR_FRAC = 0.02        # próg głośności względem najgłośniejszego okna


def detect_dji_start(video_path: str | Path,
                     start: float | None = None,
                     end: float | None = None) -> float | None:
    """Detekcja bzyczka sygnału startu (shot-timer) — odporna na strzały.

    Bzyczek to **czysty, ciągły ton** w paśmie 2000–4500 Hz: niemal cała jego
    energia leży w tym paśmie (wysoka „koncentracja") i utrzymuje się przez
    setki ms. Strzał to przeciwnie — szerokopasmowy impuls (energia rozłożona
    od basu po wysokie, trwa <100 ms). Dlatego NIE wystarczy szukać
    najgłośniejszego okna w paśmie — donośny strzał potrafi mieć w paśmie
    więcej energii niż buzzer. Rozróżniamy je po:

    1. koncentracji = energia_w_paśmie / energia_całkowita okna (≥ 0.7),
    2. ciągłości — kandydat musi trwać ≥150 ms (3 okna po 50 ms).

    Spośród kwalifikujących się przebiegów wybieramy NAJWCZEŚNIEJSZY — sygnał
    startu poprzedza strzelanie. Zwraca czas narastającego zbocza (T0) lub None.
    """
    samples, sr = _load_audio(video_path)

    lo = int(max(start, 0.0) * sr) if start is not None else 0
    hi = int(end * sr) if end is not None else samples.size
    lo = max(0, min(lo, samples.size))
    hi = max(lo, min(hi, samples.size))
    offset_s = lo / sr
    chunk = samples[lo:hi]

    win = max(1, int(sr * 0.05))  # okno 50 ms
    n_windows = chunk.size // win
    if n_windows == 0:
        return None

    seg = chunk[:n_windows * win].reshape(n_windows, win)
    spec = np.abs(np.fft.rfft(seg * np.hanning(win), axis=1)) ** 2
    freqs = np.fft.rfftfreq(win, 1.0 / sr)
    band = (freqs >= _BUZZER_BAND[0]) & (freqs <= _BUZZER_BAND[1])

    inband = spec[:, band].sum(axis=1)
    total = spec.sum(axis=1) + 1e-12
    conc = inband / total

    floor = inband.max() * _BUZZER_FLOOR_FRAC
    cand = (conc >= _BUZZER_CONC_MIN) & (inband >= floor)

    # Najwcześniejszy ciągły przebieg kandydatów o długości ≥ _BUZZER_MIN_RUN.
    i = 0
    while i < n_windows:
        if cand[i]:
            j = i
            while j + 1 < n_windows and cand[j + 1]:
                j += 1
            if (j - i + 1) >= _BUZZER_MIN_RUN:
                return round(offset_s + i * win / sr, 3)
            i = j + 1
        else:
            i += 1
    return None


def resolve_t0(anchor_time: float, mode: AnchorMode, first_shot_time: float) -> float:
    """Przelicza wykryty/wskazany punkt kotwicy na T0 (czas sygnału startu).

    START_SIGNAL — kotwica jest już sygnałem startu → T0 = anchor_time.
    FIRST_SHOT   — kotwica to pierwszy strzał → T0 = anchor_time − first_shot_time.
    """
    if mode == AnchorMode.START_SIGNAL:
        return anchor_time
    return anchor_time - first_shot_time
