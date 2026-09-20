"""Wspólne fixture'y testów.

`tiny_video` — realny, 3-sekundowy plik MP4 generowany FFmpeg-iem (lavfi):
obraz testsrc + ton 2700 Hz w oknie 0.5–0.9 s udający bzyczek shot-timera
(pozwala testować detekcję T0 end-to-end, bez mockowania FFmpeg — AGENTS.md).

`id_tone_video` — jak wyżej, ale z sygnałem tonowym ID (marker + kanał + 4 cyfry,
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
    _ID_TONE_REPEAT_GAP,
    _ID_TONE_SLOT,
    _ID_TONE_TONE_DUR,
    _id_tone_checksum,
)

ID_TONE_TEST_ID = 4821


def id_tone_expr(session_id: int, repeats: int = 2, amp: float = 0.8,
                 skip_slots: tuple[tuple[int, int], ...] = (),
                 slot_amps: dict[int, float] | None = None,
                 checksum_offset: int = 0,
                 skip_markers: tuple[int, ...] = (),
                 t_start: float = 0.0,
                 channel: int = 0) -> tuple[str, float]:
    """Wyrażenie `aevalsrc` grające ramkę protokołu decode_id_tone (v3).

    Zwraca (wyrażenie, czas_trwania_s) — harmonogram MUSI się zgadzać ze
    stałymi `_ID_TONE_*` w `audio_sync.py` (marker + slot kanału + 4 cyfry
    wartości + cyfra kontrolna, ten sam slot). `channel` — cyfra kanału
    (0 = ID wpisu w bazie, 1-9 = kod tymczasowy stanowiska), a numery slotów
    w `skip_slots`/`slot_amps` liczą się OD KANAŁU (slot 0 = kanał).
    `skip_slots` — pary (nr_powtórzenia, nr_slotu)
    do wyciszenia (test głosowania per-slot); `slot_amps` — nadpisanie
    amplitudy cyfry w danym slocie we WSZYSTKICH powtórzeniach (test dominacji
    względnej); `checksum_offset` — celowe zepsucie cyfry kontrolnej (mod 10)
    do testu odrzucania błędnego odczytu; `skip_markers` — numery powtórzeń
    z wyciszonym markerem (test „duchów" powtórzeń); `t_start` — przesunięcie
    całej sekwencji w czasie (nakładanie kilku sekwencji w jednym pliku).
    Zwracany czas trwania jest absolutny (uwzględnia `t_start`).
    """
    data_digits = [channel] + [int(ch) for ch in f"{session_id:04d}"]
    checksum = (_id_tone_checksum(data_digits) + checksum_offset) % 10
    digits = data_digits + [checksum]
    terms = []
    t0 = t_start
    for rep in range(repeats):
        if rep not in skip_markers:
            terms.append(f"if(between(t,{t0:.3f},{t0 + _ID_TONE_TONE_DUR:.3f}),"
                         f"{amp}*sin(2*PI*{_ID_TONE_MARKER_FREQ}*t),0)")
        for slot, d in enumerate(digits):
            if (rep, slot) in skip_slots:
                continue
            freq = _ID_TONE_DIGIT_FREQS[d]
            slot_amp = (slot_amps or {}).get(slot, amp)
            start = t0 + _ID_TONE_SLOT * (slot + 1)
            terms.append(f"if(between(t,{start:.3f},{start + _ID_TONE_TONE_DUR:.3f}),"
                         f"{slot_amp}*sin(2*PI*{freq}*t),0)")
        t0 += _ID_TONE_SLOT * (len(digits) + 1) + _ID_TONE_REPEAT_GAP
    return "+".join(terms), t0


def _make_tone_video(out: Path, expr: str, dur: float = 3.0) -> Path:
    """Buduje MP4 z audio z wyrażenia aevalsrc (testowe bzyczki/klingi)."""
    # Apostrofy chronią przecinki wyrażenia przed parserem filtergraphu.
    tone = f"aevalsrc='{expr}':s=44100:d={dur}"
    cmd = [
        ffmpeg.ffmpeg_exe(), "-y",
        "-f", "lavfi", "-i", f"testsrc=duration={dur}:size=320x240:rate=30",
        "-f", "lavfi", "-i", tone,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-shortest", str(out),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        pytest.skip(f"FFmpeg nie zbudował pliku testowego: {res.stderr[-500:]}")
    return out


def _make_buzzer_video(out: Path, freq: int) -> Path:
    """Buduje 3-sekundowy MP4 z tonem `freq` Hz w oknie 0.5–0.9 s (bzyczek)."""
    return _make_tone_video(out, f"if(between(t,0.5,0.9),0.8*sin(2*PI*{freq}*t),0)")


@pytest.fixture(scope="session")
def tiny_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _make_buzzer_video(tmp_path_factory.mktemp("video") / "tiny.mp4", 2700)


@pytest.fixture(scope="session")
def impact_then_buzzer_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Metaliczny kling (głośny atak 50 ms + cichsze wybrzmiewanie 4.1 kHz)
    1.5 s przed bzyczkiem 2.7 kHz — model zrzutu zamka pistoletu z sesji
    2026-08-12 (energia spada ~13× między atakiem a wybrzmiewaniem, ale ton
    jest czysty i trwa >150 ms, więc koncentracja i ciągłość go przepuszczą)."""
    expr = ("if(between(t,0.5,0.55),0.9*sin(2*PI*4100*t),0)"
            "+if(between(t,0.55,0.7),0.25*sin(2*PI*4100*t),0)"
            "+if(between(t,2.0,2.4),0.6*sin(2*PI*2700*t),0)")
    return _make_tone_video(tmp_path_factory.mktemp("video") / "impact.mp4", expr)


@pytest.fixture(scope="session")
def marginal_then_buzzer_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Marginalny kandydat (150 ms, koncentracja ~0.78: ton 4 kHz + zakłócenie
    1 kHz POZA pasmem buzzera, amplituda PŁASKA — guard obwiedni go nie łapie)
    1.5 s przed solidnym bzyczkiem — scoring musi wybrać bzyczek."""
    expr = ("if(between(t,0.5,0.65),0.35*sin(2*PI*4000*t)+0.186*sin(2*PI*1000*t),0)"
            "+if(between(t,2.0,2.4),0.6*sin(2*PI*2700*t),0)")
    return _make_tone_video(tmp_path_factory.mktemp("video") / "marginal.mp4", expr)


@pytest.fixture(scope="session")
def tiny_video_4600hz(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Buzzer 4.6 kHz — timer z sesji polowej 2026-07-19 (nie Shooters Global);
    grał 100 Hz ponad dawnym sufitem pasma 4500 Hz i był niewykrywalny."""
    return _make_buzzer_video(tmp_path_factory.mktemp("video") / "tiny4600.mp4", 4600)


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
