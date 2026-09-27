"""Punktacja i progi automatycznego wiązania ujęć wideo z wpisami kalkulatora.

WARTOŚCI STARTOWE DO KALIBRACJI. Pochodzą z analizy `DOPASOWANIE-WIDEO.md` §3.2/§3.3
(repo `esp32-timer-camera-control`, ADR-063) i NIE są jeszcze dostrojone na danych:
do pomiaru na sprzęcie są m.in. rozrzut `duration(pliku) − video_duration_s`,
`t0(pliku) − video_preroll_ms` i `pos_s(tonu) − (idtone_at − rec_start)` (≥ 10 sesji,
checklista `docs/TESTY.md` ESP) oraz walidacja na nagraniach z Krotoszyna (A1: 0 błędnych
`picked`, ≥ 23 `picked`). Wszystkie stałe są w tym jednym module — kalibracja nie
powinna dotykać logiki w `matching.py`.

Zasada nadrzędna: żaden pojedynczy sygnał poza ID-tone nie wystarcza do `picked`;
ID-tone wystarcza, dopóki nic mu nie przeczy. Błędne powiązanie jest gorsze niż brak.
"""

from __future__ import annotations

# --- decyzja (§3.3) ---
PICK_MIN = 60          # sam kanał 0 (100) przechodzi; sama nazwa (40) + T0 (25) też
PICK_MARGIN = 30       # przewaga najlepszego nad drugim
HARD_NEG = -40         # pojedynczy dowód ≤ tego = sprzeczność → ambiguous

# --- ID-tone ---
TONE_DB_MATCH = 100    # kanał 0: wartość == ID wpisu
TONE_DB_OTHER = -100   # kanał 0 czytelny, wskazuje INNY wpis
TONE_TEMP_MATCH = 60   # kod tymczasowy równy `temp_id` wpisu i czas ≤ TEMP_MAX_AGE_S
TONE_TEMP_OTHER = -60  # kod tymczasowy czytelny, wpis ma inny kod
TEMP_MAX_AGE_S = 12 * 3600.0   # licznik kodów zawija się po 9999 — stary kod = nie dowód

# pozycja ramki w pliku DJI vs `idtone_at_ms − rec_start`
TONE_POS_TOL_S = 1.0
TONE_POS_MATCH = 15

# --- T0 w pliku vs `video_preroll_ms` (DJI; niezależne od zegarów) ---
PREROLL_TIERS = ((0.3, 25), (1.0, 10))     # (|Δ| ≤ s, punkty)
PREROLL_BAD_S = 3.0
PREROLL_BAD = -25

# --- czas trwania pliku vs `video_duration_s` (DJI) ---
DURATION_TOL_S = 3.0
DURATION_MATCH = 15
DURATION_BAD_S = 10.0
DURATION_BAD = -15

# --- nazwa DJI vs `video_file` (Δ = czas_nazwy − δ_D − czas(video_file)) ---
NAME_DELTA_MIN_S = -2.0   # G1: predykcja ESP jest 0–1 s (+BLE) PÓŹNIEJ niż prawdziwy start
NAME_DELTA_MAX_S = 1.0
NAME_EXACT = 40
NAME_TIERS = ((10.0, 20), (30.0, 5))       # (|Δ| ≤ s, punkty)
NAME_BAD_S = 120.0
NAME_BAD = -40

# --- beep na osi urządzenia (Δb = start_skor + t0 − t_beep) ---
BEEP_TIERS = ((2.0, 30), (10.0, 15), (150.0, 5))
BEEP_BAD_S = 300.0
BEEP_BAD = -30
# wpis bez `t_beep_ms` (stary): `timer_sess_id + start_delay` (zegar TIMERA, dryf do
# ~110 s) — progi × BEEP_TIMER_SCALE, połowa punktów
BEEP_TIMER_SCALE = 3.0
BEEP_TIMER_POINTS = 0.5
# `clock_ok == False` (zegar ESP bez NTP) albo start pliku tylko z mtime — progi × 3
UNSYNCED_SCALE = 3.0
# bez T0 w pliku: beep musi wpaść w przedział nagrania ± tyle
BEEP_NO_T0_TOL_S = 10.0
BEEP_NO_T0 = 5

# kara zależna od zegara, któremu nie ufamy (kamera bez kotwic, timer, ESP bez NTP):
# mnożnik punktów ujemnych; taka kara nie jest sprzecznością (nie wetuje ID-tone)
UNTRUSTED_PENALTY = 0.5

# --- wpis ręczny (bez t_beep i bez timer_sess_id) ---
SAVE_MIN_S = -15.0
SAVE_MAX_S = 300.0
SAVE_MATCH = 5

# --- odcisk strzałów (audio_sync.shot_alignment_score) ---
SHOT_RATIO = 1.3          # najlepszy ≥ 1,3× drugiego
SHOT_MATCH = 30
SHOT_BACKGROUND_MAX = 1.2  # wynik ≈ 1 = strzały w tle, zła oś
SHOT_BACKGROUND = -20
SHOT_TOP_K = 6            # odcisk liczymy tylko dla tylu najlepszych kandydatów ujęcia

# --- kolejność / stanowisko (przydział globalny per `device_key`) ---
ORDER_OK = 10             # przydział zachowuje monotoniczność i ma sąsiada na osi
STATION_MATCH = 10        # `timer_sn` jak w pewnych przypisaniach tego urządzenia

# --- offset zegara urządzenia z kotwic (§3.4 krok 2, wzorem ADR-047) ---
OFFSET_MIN_ANCHORS = 3
OFFSET_MAX_IQR_S = 5.0

# --- zapytania do API przy wsadzie ---
BATCH_QUERY_MARGIN_S = 3600.0   # okno wszystkich ujęć ± 1 h
BATCH_CLUSTER_GAP_S = 6 * 3600.0  # przerwa, po której ujęcia to osobny dzień/zapytanie
