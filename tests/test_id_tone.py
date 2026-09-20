"""Testy dekodera sygnału tonowego ID (`audio_sync.decode_id_tone`, protokół v3).

Audio budowane FFmpeg-iem (lavfi `aevalsrc`, jak `tiny_video` w conftest.py) —
bez mockowania FFmpeg, zgodnie z AGENTS.md. Numeracja slotów jak w protokole:
slot 0 = kanał, sloty 1-4 = wartość, slot 5 = cyfra kontrolna.
"""

from __future__ import annotations

import subprocess

import pytest

from piro_overlay import ffmpeg
from piro_overlay.audio_sync import (
    _ID_TONE_SLOT,
    _ID_TONE_TONE_DUR,
    IdToneCode,
    decode_id_tone,
)

from conftest import id_tone_expr as _id_tone_expr


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
    code = decode_id_tone(wav)
    assert code == IdToneCode(channel=0, value=4821)
    assert code.is_db_id and code.entry_id == 4821 and code.temp_id is None


def test_decode_id_tone_temp_code(tmp_path):
    # Kanał 3 (stanowisko 3) + wartość 147 = kod tymczasowy „30147" / „3-0147".
    expr, dur = _id_tone_expr(147, channel=3)
    wav = _render_wav(tmp_path, expr, dur + 0.3)
    code = decode_id_tone(wav)
    assert code == IdToneCode(channel=3, value=147)
    assert not code.is_db_id and code.entry_id is None
    assert code.temp_id == "30147" and code.label == "3-0147"


def test_decode_id_tone_leading_zero(tmp_path):
    expr, dur = _id_tone_expr(37)  # -> "0037"
    wav = _render_wav(tmp_path, expr, dur + 0.3)
    assert decode_id_tone(wav) == IdToneCode(0, 37)


def test_decode_id_tone_single_pass_still_decodes(tmp_path):
    expr, dur = _id_tone_expr(9999, repeats=1)
    wav = _render_wav(tmp_path, expr, dur + 0.3)
    assert decode_id_tone(wav) == IdToneCode(0, 9999)


def test_decode_id_tone_no_marker_returns_none(tmp_path):
    # Cisza — brak jakiegokolwiek markera.
    wav = _render_wav(tmp_path, "0", 2.0)
    assert decode_id_tone(wav) is None


def test_decode_id_tone_weak_digit_relative_dominance(tmp_path):
    # Cicha cyfra + równoczesny ton zakłócający 6100 Hz — WEWNĄTRZ pasma
    # protokołu (podbija mianownik lokalnego SNR), ale poza pasmami wszystkich
    # kandydatów (6100 leży dokładnie między cyfrą 4=6000 a 5=6200, on-bin dla
    # FFT 20 Hz → zero przecieku do sąsiadów). Poziom cyfry ~0.45 < próg 0.55,
    # pozostałe pasma ~0 — musi przejść dominacją względną.
    expr, dur = _id_tone_expr(4821, repeats=1, slot_amps={4: 0.3})
    start = _ID_TONE_SLOT * 5
    hum = (f"+if(between(t,{start:.3f},{start + _ID_TONE_TONE_DUR:.3f}),"
           f"0.33*sin(2*PI*6100*t),0)")
    wav = _render_wav(tmp_path, expr + hum, dur + 0.3)
    assert decode_id_tone(wav) == IdToneCode(0, 4821)


def test_decode_id_tone_out_of_band_noise_ignored(tmp_path):
    # Głośny hałas POZA pasmem protokołu (przydźwięk 300 Hz przez cały czas,
    # głośniejszy od tonów) nie może psuć odczytu — metryka „lokalny SNR"
    # dzieli przez energię pasma 4900–7100 Hz, nie całego widma. Stara metryka
    # (energia/total) dawała tu ~0.15 i odrzucała wszystko łącznie z markerem.
    # amp tonów + amp szumu < 1.0, żeby suma nie clipowała w WAV (clipping
    # dodałby zniekształcenia szerokopasmowe, także wewnątrz pasma protokołu).
    expr, dur = _id_tone_expr(4821, repeats=1, amp=0.25)
    noisy = f"({expr})+0.7*sin(2*PI*300*t)"
    wav = _render_wav(tmp_path, noisy, dur + 0.3)
    assert decode_id_tone(wav) == IdToneCode(0, 4821)


def test_decode_id_tone_amplitude_dip(tmp_path):
    # „Dziurawa" amplituda z realnych nagrań DJI: ton cyfry zanika na 150 ms
    # w SAMYM ŚRODKU slotu (a właśnie tam czytała średnia z 3 okien wokół
    # środka). Odczyt „najlepsze okno slotu" musi złapać zdrowe brzegi tonu.
    expr, dur = _id_tone_expr(4821, repeats=1, skip_slots=((0, 1),))
    d1_freq = 5200 + 200 * 4  # slot 1 wartości 4821 to cyfra 4
    start = _ID_TONE_SLOT * 2
    mid = start + _ID_TONE_TONE_DUR / 2
    parts = (f"+if(between(t,{start:.3f},{mid - 0.075:.3f}),"
             f"0.8*sin(2*PI*{d1_freq}*t),0)"
             f"+if(between(t,{mid + 0.075:.3f},{start + _ID_TONE_TONE_DUR:.3f}),"
             f"0.8*sin(2*PI*{d1_freq}*t),0)")
    wav = _render_wav(tmp_path, expr + parts, dur + 0.3)
    assert decode_id_tone(wav) == IdToneCode(0, 4821)


def test_decode_id_tone_ghost_repetition(tmp_path):
    # Powtórzenie 1: marker jest, ale 2 sloty wycięte (odzysk z checksumy
    # ratuje najwyżej jeden). Powtórzenie 2: komplet cyfr, ale BEZ markera.
    # Dekoder musi doczytać brakujące sloty z „ducha" powtórzenia 2
    # (pozycja znana z odstępu powtórzeń), mimo braku tamtejszego markera.
    expr, dur = _id_tone_expr(4821, repeats=2,
                              skip_slots=((0, 1), (0, 3)), skip_markers=(1,))
    wav = _render_wav(tmp_path, expr, dur + 0.3)
    assert decode_id_tone(wav) == IdToneCode(0, 4821)


def test_decode_id_tone_checksum_recovers_missing_digit(tmp_path):
    # Slot 2 (waga 3, odwracalna mod 10) wycięty we WSZYSTKICH powtórzeniach —
    # cyfra musi zostać jednoznacznie odzyskana z sumy kontrolnej.
    expr, dur = _id_tone_expr(4821, repeats=2, skip_slots=((0, 2), (1, 2)))
    wav = _render_wav(tmp_path, expr, dur + 0.3)
    assert decode_id_tone(wav) == IdToneCode(0, 4821)


def test_decode_id_tone_checksum_recovers_missing_channel(tmp_path):
    # Slot 0 (kanał, waga 1 — odwracalna) wycięty wszędzie: kanał musi zostać
    # odzyskany z checksumy, inaczej kod tymczasowy trafiłby do złego kanału.
    expr, dur = _id_tone_expr(147, channel=3, repeats=2,
                              skip_slots=((0, 0), (1, 0)))
    wav = _render_wav(tmp_path, expr, dur + 0.3)
    assert decode_id_tone(wav) == IdToneCode(3, 147)


def test_decode_id_tone_ghost_only_sequence_rejected(tmp_path):
    # Marker bez ŻADNEJ czytelnej cyfry przy sobie + komplet cyfr w pozycji
    # ducha (2.8 s dalej, bez markera) — wszystkie zwycięskie sloty pochodzą
    # wyłącznie z duchów. Taki układ w praktyce oznacza pisk tła jako marker
    # i obce tony jako "cyfry" (realny przypadek fałszywego ID przechodzącego
    # checksumę), więc dekoder musi odmówić.
    expr, dur = _id_tone_expr(
        4821, repeats=2, skip_markers=(1,),
        skip_slots=tuple((0, s) for s in range(6)))
    wav = _render_wav(tmp_path, expr, dur + 0.3)
    assert decode_id_tone(wav) is None


def test_decode_id_tone_quiet_false_marker_filtered(tmp_path):
    # Cichy pisk tła układający się w KOMPLETNĄ, poprawną sekwencję innego ID
    # (2 powtórzenia = 2 głosy/slot, kontra 1 głos prawdziwego ID) — metryka
    # lokalnego SNR daje mu pełne poziomy, więc bez filtra energetycznego
    # markerów przegłosowałby prawdziwy, głośny sygnał. Run markera ~400×
    # cichszy energetycznie musi odpaść razem ze swoimi głosami.
    expr_real, dur_real = _id_tone_expr(4821, repeats=1)
    expr_fake, dur = _id_tone_expr(9999, repeats=2, amp=0.04,
                                   t_start=dur_real + 0.5)
    wav = _render_wav(tmp_path, f"{expr_real}+{expr_fake}", dur + 0.3)
    assert decode_id_tone(wav) == IdToneCode(0, 4821)


def test_decode_id_tone_ambiguous_recovery_rejected(tmp_path):
    # Slot 1 (waga 2, NIEodwracalna mod 10) wycięty wszędzie → dwóch
    # kandydatów (d i d+5), a w audio zero energii któregokolwiek z nich —
    # dekoder MUSI odmówić zamiast zgadywać (zgadnięte ID przechodziłoby
    # checksumę, mimo braku dowodu w nagraniu).
    expr, dur = _id_tone_expr(4821, repeats=2, skip_slots=((0, 1), (1, 1)))
    wav = _render_wav(tmp_path, expr, dur + 0.3)
    assert decode_id_tone(wav) is None


def test_decode_id_tone_weight5_recovery_refused(tmp_path):
    # Slot 4 (ostatnia cyfra wartości, waga 5) wycięty wszędzie → aż PIĘCIU
    # kandydatów z checksumy (5·d mod 10 ma tylko dwie wartości). Odzysk jest
    # tam odrzucany z zasady, nawet gdyby energia pasm coś sugerowała.
    expr, dur = _id_tone_expr(4821, repeats=2, skip_slots=((0, 4), (1, 4)))
    wav = _render_wav(tmp_path, expr, dur + 0.3)
    assert decode_id_tone(wav) is None


def test_decode_id_tone_per_slot_voting(tmp_path):
    # Żadne powtórzenie nie jest kompletne (w każdym wycięty inny slot),
    # więc pojedynczy marker nie da pełnego odczytu — głosowanie per-slot
    # musi złożyć kod z obu powtórzeń.
    expr, dur = _id_tone_expr(4821, repeats=2, skip_slots=((0, 2), (1, 0)))
    wav = _render_wav(tmp_path, expr, dur + 0.3)
    assert decode_id_tone(wav) == IdToneCode(0, 4821)


def test_decode_id_tone_bad_checksum_rejected(tmp_path):
    # Sygnał czysty i w pełni czytelny, ale cyfra kontrolna celowo błędna —
    # dekoder MUSI odrzucić odczyt (błędne ID pobrałoby cudzą sesję z API).
    expr, dur = _id_tone_expr(4821, checksum_offset=3)
    wav = _render_wav(tmp_path, expr, dur + 0.3)
    assert decode_id_tone(wav) is None


def test_decode_id_tone_missing_checksum_slot_rejected(tmp_path):
    # Brak odczytu w slocie cyfry kontrolnej (wyciszony w obu powtórzeniach)
    # = brak weryfikacji = None, nawet gdy sloty danych czytają się czysto.
    expr, dur = _id_tone_expr(4821, repeats=2, skip_slots=((0, 5), (1, 5)))
    wav = _render_wav(tmp_path, expr, dur + 0.3)
    assert decode_id_tone(wav) is None
