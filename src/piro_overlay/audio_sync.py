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
        ffmpeg.ffmpeg_exe(), "-y", *ffmpeg.UNTRUSTED_INPUT_ARGS, "-i", str(video_path),
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


_BUZZER_BAND = (2000.0, 4800.0)   # pasmo buzzerów shot-timerów: ~2.7 kHz (typowy)
                                  # do 4.6 kHz (timer z sesji 2026-07-19); sufit 4800
                                  # zostawia odstęp od protokołu ID (≥4900 Hz)
_BUZZER_CONC_MIN = 0.7            # min. udział energii w paśmie (tonalność)
_BUZZER_MIN_RUN = 3              # min. liczba okien 50 ms (≥150 ms ciągłego tonu)
_BUZZER_FLOOR_FRAC = 0.02        # próg głośności względem najgłośniejszego okna
_BUZZER_FREQ_TOL = 150.0         # tolerancja stałości częstotliwości tonu (Hz)


def detect_dji_start(video_path: str | Path,
                     start: float | None = None,
                     end: float | None = None) -> float | None:
    """Detekcja bzyczka sygnału startu (shot-timer) — odporna na strzały.

    Bzyczek to **czysty, ciągły ton** w paśmie 2000–4800 Hz: niemal cała jego
    energia leży w tym paśmie (wysoka „koncentracja") i utrzymuje się przez
    setki ms. Strzał to przeciwnie — szerokopasmowy impuls (energia rozłożona
    od basu po wysokie, trwa <100 ms). Dlatego NIE wystarczy szukać
    najgłośniejszego okna w paśmie — donośny strzał potrafi mieć w paśmie
    więcej energii niż buzzer. Rozróżniamy je po:

    1. koncentracji = energia_w_paśmie / energia_całkowita okna (≥ 0.7),
    2. ciągłości — kandydat musi trwać ≥150 ms (3 okna po 50 ms).

    Spośród kwalifikujących się przebiegów wybieramy NAJWCZEŚNIEJSZY — sygnał
    startu poprzedza strzelanie.

    Gdy główny test nic nie znajdzie (bzyczek krótki/zagłuszony tłem — tylko
    pojedyncze okno przebija próg koncentracji), uruchamiamy łagodniejszy
    FALLBACK: szukamy okna o wysokiej koncentracji, którego **dominująca
    częstotliwość** jest stabilna (±150 Hz) przez ≥150 ms. Stabilność tonu
    odróżnia bzyczek (jedna częstotliwość) od strzału (częstotliwość błądzi),
    nawet gdy hałas tła obniża koncentrację w sąsiednich oknach.

    Zwraca czas narastającego zbocza (T0) lub None.
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
    band_freqs = freqs[band]

    inband = spec[:, band].sum(axis=1)
    total = spec.sum(axis=1) + 1e-12
    conc = inband / total
    dom_hz = band_freqs[np.argmax(spec[:, band], axis=1)]

    floor = inband.max() * _BUZZER_FLOOR_FRAC

    # --- Główny test: najwcześniejszy ciągły przebieg okien o conc ≥ próg. ---
    cand = (conc >= _BUZZER_CONC_MIN) & (inband >= floor)
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

    # --- Fallback: najwcześniejszy ton o stabilnej częstotliwości ≥150 ms. ---
    for c in np.flatnonzero(conc >= _BUZZER_CONC_MIN):
        f0 = dom_hz[c]
        edge_floor = inband[c] * _BUZZER_FLOOR_FRAC
        left = c
        while (left > 0 and abs(dom_hz[left - 1] - f0) <= _BUZZER_FREQ_TOL
               and inband[left - 1] >= edge_floor):
            left -= 1
        right = c
        while (right + 1 < n_windows and abs(dom_hz[right + 1] - f0) <= _BUZZER_FREQ_TOL
               and inband[right + 1] >= edge_floor):
            right += 1
        if (right - left + 1) >= _BUZZER_MIN_RUN:
            return round(offset_s + left * win / sr, 3)
    return None


# Protokół v2 (v0.33.0, BEZ kompatybilności z v1 — timer i kalkulator grają v2):
# pasmo cyfr obniżone do 5200–7000 Hz (odstęp 200 Hz) — pomiar na realnym
# nagraniu DJI pokazał, że 7250/7500 Hz zanikały (głośnik/mikrofon/AAC tną
# ciche wysokie tony); ton wydłużony do 300 ms (odporność na zjadanie ogona
# przez AAC); 5. slot to cyfra kontrolna (suma ważona) — błędny odczyt jest
# odrzucany zamiast pobrać cudzą sesję z API.
_ID_TONE_MARKER_FREQ = 5000.0                                  # start kodu ID
_ID_TONE_DIGIT_FREQS = [5200.0 + 200.0 * d for d in range(10)]  # cyfry 0-9
_ID_TONE_BAND_HALFWIDTH = 70.0    # Hz — przy odstępie 200 Hz zostaje 60 Hz marginesu
_ID_TONE_TONE_DUR = 0.30          # s — czas trwania jednego tonu (marker/cyfra)
_ID_TONE_GAP = 0.05               # s — cisza między tonami
_ID_TONE_SLOT = _ID_TONE_TONE_DUR + _ID_TONE_GAP
_ID_TONE_DIGITS = 4               # "IDxxxx" — 0-9999, timer wysyła zero-padded
_ID_TONE_SLOTS = _ID_TONE_DIGITS + 1  # + cyfra kontrolna na końcu
_ID_TONE_CONC_MIN = 0.55          # próg koncentracji energii w paśmie tonu
_ID_TONE_MARKER_MIN_RUN = 3       # ≥150 ms ciągłości markera (okna 50 ms)
_ID_TONE_DOM_MIN = 0.30           # dominacja względna: min. poziom słabego tonu
_ID_TONE_DOM_RATIO = 4.0          # …i wymagana przewaga nad drugim kandydatem
_ID_TONE_RANGE = (4900.0, 7100.0)  # pasmo protokołu — mianownik metryki „lokalny SNR"
_ID_TONE_MARKER_EDGE = 0.35       # miękki próg kontynuacji runu markera (edge floor)
_ID_TONE_REPEAT_GAP = 0.3         # s — przerwa między powtórzeniami (jak w playerach JS)
_ID_TONE_RESCUE_MIN = 0.10        # odzysk z checksumy: min energia zwycięskiego kandydata
_ID_TONE_RESCUE_RATIO = 2.0       # …i wymagana przewaga nad drugim kandydatem
_ID_TONE_ENERGY_FLOOR = 0.01      # min energia okna (ułamek mediany okien markera) —
                                  # metryki względne nie mają sensu w niemal-ciszy
_ID_TONE_MARKER_ENERGY_FRAC = 0.02  # run markera wielokrotnie cichszy od najgłośniejszego
                                    # to nie powtórzenie, tylko pisk tła (fałszywy marker)


def _id_tone_checksum(digits: list[int]) -> int:
    """Cyfra kontrolna protokołu ID: suma ważona pozycją (1-4) mod 10.

    Wagi wykrywają każdy błąd pojedynczej cyfry i większość podwójnych.
    MUSI być identyczna z `idToneChecksum` w timerze i kalkulatorze.
    """
    return sum((i + 1) * d for i, d in enumerate(digits)) % 10


def decode_id_tone(video_path: str | Path,
                   start: float | None = None,
                   end: float | None = None) -> int | None:
    """Dekoduje 4-cyfrowe ID sesji z sygnału tonowego nagranego przez kamerę.

    Protokół v2: timer (www.timer.pifpaf.fun) i kalkulator po zapisaniu sesji
    mogą odtworzyć ID jako sekwencję czystych tonów: marker (5000 Hz, „tu
    zaczyna się kod") + 4 cyfry + cyfra kontrolna (`_id_tone_checksum`), każda
    jako jeden z 10 tonów 5200–7000 Hz (co 200 Hz), ton 300 ms + 50 ms ciszy,
    sekwencja powtórzona dwukrotnie. Pasmo leży bezpiecznie powyżej bzyczka
    startu (2000–4800 Hz, `detect_dji_start`) i poniżej Nyquista tej ekstrakcji
    audio (16 kHz → 8 kHz); górna granica obniżona z 7500 Hz (v1), bo pomiar na
    realnym nagraniu DJI pokazał zanik cichych tonów >7 kHz w łańcuchu głośnik
    telefonu → mikrofon kamery → AAC.

    Dekodowanie jest slot-owe: znajdujemy każdy marker (próg + ciągłość
    ≥150 ms, z miękkim progiem kontynuacji `_ID_TONE_MARKER_EDGE` jak przy
    bzyczku — jedno słabsze okno nie rozcina runu), a każdą cyfrę odczytujemy
    w jej z góry znanym slocie czasowym. Metryka tonu to „lokalny SNR":
    energia pasma kandydata / energia pasma protokołu `_ID_TONE_RANGE`
    (NIE całego widma — szerokopasmowy hałas strzelnicy poza pasmem nie może
    zaniżać oceny czystego tonu). Odczyt slotu = najlepsze OKNO slotu (max,
    nie średnia — odporność na chwilowe zaniki amplitudy w środku tonu).
    Okno przechodzi progiem bezwzględnym `_ID_TONE_CONC_MIN` ALBO dominacją
    względną (≥`_ID_TONE_DOM_MIN` i ≥`_ID_TONE_DOM_RATIO`× drugi kandydat).

    Powtórzenia składamy głosowaniem per-slot: każdy marker wnosi odczytane
    cyfry (ważone poziomem) do wspólnej puli. Odstęp powtórzeń jest znany,
    więc wykryty marker dodaje też „ducha" sąsiedniego powtórzenia — jego
    sloty są czytane nawet, gdy tamten marker nie zrobił własnego runu.
    Złożony wynik przechodzi walidację cyfrą kontrolną — niezgodność = None
    (lepiej nie podpowiedzieć ID wcale niż podpowiedzieć cudzy). Dokładnie
    jeden nieczytelny slot DANYCH jest odzyskiwany z checksumy (erasure
    recovery); przy dwuznaczności (wagi 2/4 mod 10) rozstrzyga energia pasm
    kandydatów, a bez wyraźnego zwycięzcy odczyt jest odrzucany. Nieczytelna
    sama checksuma = None (bez niej nie ma jak zweryfikować odczytu).

    Zwraca dekodowane ID albo None.
    """
    samples, sr = _load_audio(video_path)

    lo = int(max(start, 0.0) * sr) if start is not None else 0
    hi = int(end * sr) if end is not None else samples.size
    lo = max(0, min(lo, samples.size))
    hi = max(lo, min(hi, samples.size))
    offset_s = lo / sr
    chunk = samples[lo:hi]

    win = max(1, int(sr * 0.05))  # okno 50 ms — jak detect_dji_start
    n_windows = chunk.size // win
    if n_windows == 0:
        return None

    seg = chunk[:n_windows * win].reshape(n_windows, win)
    spec = np.abs(np.fft.rfft(seg * np.hanning(win), axis=1)) ** 2
    freqs = np.fft.rfftfreq(win, 1.0 / sr)
    range_mask = (freqs >= _ID_TONE_RANGE[0]) & (freqs <= _ID_TONE_RANGE[1])
    in_range = spec[:, range_mask].sum(axis=1) + 1e-12

    def band_snr(center: float) -> np.ndarray:
        band = (freqs >= center - _ID_TONE_BAND_HALFWIDTH) & (freqs <= center + _ID_TONE_BAND_HALFWIDTH)
        return spec[:, band].sum(axis=1) / in_range

    marker_snr = band_snr(_ID_TONE_MARKER_FREQ)
    soft = marker_snr >= _ID_TONE_MARKER_EDGE
    runs: list[tuple[int, int, float]] = []  # (okno_startu_twardego, koniec, mediana energii)
    i = 0
    while i < n_windows:
        if soft[i]:
            j = i
            while j + 1 < n_windows and soft[j + 1]:
                j += 1
            hard = [k for k in range(i, j + 1) if marker_snr[k] >= _ID_TONE_CONC_MIN]
            if (j - i + 1) >= _ID_TONE_MARKER_MIN_RUN and hard:
                # Onset = pierwsze TWARDE okno: miękki próg służy mostkowaniu
                # dziur w środku runu, ale nie może przesuwać startu (pre-echo/
                # pogłos przed markerem przesuwał siatkę slotów o okno-dwa,
                # przez co okno slotu łapało ogon poprzedniej cyfry).
                runs.append((hard[0], j, float(np.median(in_range[i:j + 1]))))
            i = j + 1
        else:
            i += 1
    if not runs:
        return None

    # Fałszywe markery: cichy pisk ~5 kHz w tle potrafi mieć wysoki LOKALNY
    # SNR (w prawie-ciszy), zrobić run i wnosić śmieciowe głosy przez swoje
    # sloty i duchy. Realne powtórzenia grają na zbliżonym poziomie — run
    # wielokrotnie cichszy od najgłośniejszego odpada.
    e_max = max(r[2] for r in runs)
    runs = [r for r in runs if r[2] >= _ID_TONE_MARKER_ENERGY_FRAC * e_max]
    marker_starts = [offset_s + r[0] * win / sr for r in runs]
    marker_windows = [k for r in runs for k in range(r[0], r[1] + 1)]

    # Metryki względne (udział pasma) nie rozróżniają realnego tonu od śladów
    # w niemal-ciszy (kwantyzacja, pre-ringing resamplera) — okna słabsze niż
    # ułamek energii okien markera (= poziomu sygnału TEJ sekwencji) odpadają.
    energy_floor = _ID_TONE_ENERGY_FLOOR * float(np.median(in_range[marker_windows]))

    # „Duchy" powtórzeń: odstęp powtórzeń jest znany, więc każdy wykryty marker
    # wskazuje też pozycję sąsiedniego powtórzenia — czytamy jego sloty nawet,
    # gdy TAMTEN marker nie zrobił własnego runu (głosowanie i checksum bronią
    # przed śmieciowymi głosami z pustych miejsc).
    period = _ID_TONE_SLOT * (_ID_TONE_SLOTS + 1) + _ID_TONE_REPEAT_GAP
    starts = sorted(marker_starts)
    for t_marker in marker_starts:
        for ghost in (t_marker - period, t_marker + period):
            if all(abs(ghost - s) > _ID_TONE_SLOT / 2 for s in starts):
                starts.append(ghost)

    digit_snr = [band_snr(f) for f in _ID_TONE_DIGIT_FREQS]
    win_s = win / sr

    def slot_window_range(t_start: float) -> tuple[int, int]:
        i0 = int((t_start - offset_s) / win_s)
        i1 = int((t_start + _ID_TONE_TONE_DUR - offset_s) / win_s) + 1
        return max(0, i0), min(n_windows, i1)

    def read_slot(t_start: float) -> tuple[int, float] | None:
        """Najlepsze OKNO slotu (max, nie średnia) — odporne na dziury amplitudy."""
        lo_i, hi_i = slot_window_range(t_start)
        best: tuple[int, float] | None = None
        for i in range(lo_i, hi_i):
            if in_range[i] < energy_floor:
                continue
            levels = [float(digit_snr[d][i]) for d in range(10)]
            order = np.argsort(levels)
            d, lvl = int(order[-1]), levels[int(order[-1])]
            passes = lvl >= _ID_TONE_CONC_MIN or (
                lvl >= _ID_TONE_DOM_MIN
                and lvl >= _ID_TONE_DOM_RATIO * levels[int(order[-2])])
            if passes and (best is None or lvl > best[1]):
                best = (d, lvl)
        return best

    def slot_start(t_marker: float, slot: int) -> float:
        return t_marker + _ID_TONE_SLOT * (slot + 1)

    slot_votes: list[dict[int, float]] = [{} for _ in range(_ID_TONE_SLOTS)]
    slot_peak: list[dict[int, float]] = [{} for _ in range(_ID_TONE_SLOTS)]
    slot_real: list[set[int]] = [set() for _ in range(_ID_TONE_SLOTS)]
    real_starts = set(marker_starts)
    for t_marker in starts:
        for slot in range(_ID_TONE_SLOTS):
            reading = read_slot(slot_start(t_marker, slot))
            if reading is not None:
                d, lvl = reading
                slot_votes[slot][d] = slot_votes[slot].get(d, 0.0) + lvl
                slot_peak[slot][d] = max(slot_peak[slot].get(d, 0.0), lvl)
                if t_marker in real_starts:
                    slot_real[slot].add(d)

    empty = [s for s in range(_ID_TONE_SLOTS) if not slot_votes[s]]
    decoded = [max(votes, key=votes.get) if votes else -1 for votes in slot_votes]

    # Duchy mogą UZUPEŁNIAĆ odczyt, ale nie zastępować go w całości: gdy żaden
    # zwycięski slot nie ma głosu z REALNEGO markera, "sekwencję" złożyły
    # przypadkowe dźwięki tła wokół fałszywych markerów (realny przypadek:
    # nagranie bez sygnału ID, pisk 5 kHz jako marker + obcy ton w slotach
    # ducha → ID przechodzące checksumę). Prawdziwy sygnał zawsze niesie
    # własne cyfry przy własnym markerze.
    if not any(decoded[s] in slot_real[s] for s in range(_ID_TONE_SLOTS) if s not in empty):
        return None

    if not empty:
        if _id_tone_checksum(decoded[:_ID_TONE_DIGITS]) != decoded[_ID_TONE_DIGITS]:
            return None
        return int("".join(str(d) for d in decoded[:_ID_TONE_DIGITS]))

    # Odzysk z checksumy (erasure recovery): dokładnie JEDEN nieczytelny slot
    # DANYCH da się odtworzyć z sumy kontrolnej. Wagi 1 i 3 są odwracalne
    # mod 10 (jednoznaczna cyfra); wagi 2 i 4 zostawiają dwóch kandydatów
    # (d oraz d+5) — rozstrzyga energia pasm kandydatów w oknach tego slotu,
    # ale tylko przy wyraźnym zwycięzcy (inaczej zgadywanie dałoby ID
    # przechodzące checksumę mimo braku dowodu w audio). Nieczytelna sama
    # checksuma = None (bez niej nie ma jak zweryfikować pozostałych cyfr).
    if len(empty) != 1 or empty[0] >= _ID_TONE_DIGITS:
        return None
    # Rescue tylko na mocnych podstawach: każdy ODCZYTANY slot musi mieć co
    # najmniej jeden odczyt pełnej jakości. Bez tego fałszywe markery + szum
    # tła potrafią złożyć 4 słabe sloty, a odzyskana cyfra przechodzi
    # checksumę Z KONSTRUKCJI — czyli rescue produkowałby wiarygodnie
    # wyglądające, błędne ID (realny przypadek z nagrania bez sygnału).
    if any(slot_peak[s][decoded[s]] < _ID_TONE_CONC_MIN
           for s in range(_ID_TONE_SLOTS) if s not in empty):
        return None
    gap_slot = empty[0]
    weight = gap_slot + 1
    known = sum((i + 1) * decoded[i] for i in range(_ID_TONE_DIGITS) if i != gap_slot)
    residual = (decoded[_ID_TONE_DIGITS] - known) % 10
    candidates = [d for d in range(10) if (weight * d) % 10 == residual]
    if not candidates:
        return None
    if len(candidates) == 1:
        decoded[gap_slot] = candidates[0]
    else:
        strength = {d: 0.0 for d in candidates}
        for t_marker in starts:
            lo_i, hi_i = slot_window_range(slot_start(t_marker, gap_slot))
            for i in range(lo_i, hi_i):
                if in_range[i] < energy_floor:
                    continue
                for d in candidates:
                    strength[d] = max(strength[d], float(digit_snr[d][i]))
        ranked = sorted(candidates, key=lambda d: strength[d], reverse=True)
        if (strength[ranked[0]] < _ID_TONE_RESCUE_MIN
                or strength[ranked[0]] < _ID_TONE_RESCUE_RATIO * strength[ranked[1]]):
            return None
        decoded[gap_slot] = ranked[0]
    return int("".join(str(d) for d in decoded[:_ID_TONE_DIGITS]))


def resolve_t0(anchor_time: float, mode: AnchorMode, first_shot_time: float) -> float:
    """Przelicza wykryty/wskazany punkt kotwicy na T0 (czas sygnału startu).

    START_SIGNAL — kotwica jest już sygnałem startu → T0 = anchor_time.
    FIRST_SHOT   — kotwica to pierwszy strzał → T0 = anchor_time − first_shot_time.
    """
    if mode == AnchorMode.START_SIGNAL:
        return anchor_time
    return anchor_time - first_shot_time
