# CLAUDE.md — kontekst projektu Piro Overlay

Kontekst dla przyszłych sesji Claude Code. Aplikacja nakłada na wideo ze strzelania
informacje o strzałach (split/czas/„x z yy"/podsumowanie) i renderuje gotowy film.

> **OBOWIĄZEK:** Przed każdą sesją roboczą przeczytaj także `AGENTS.md` — zawiera zasady
> pracy z kodem, styl, przepływ pracy i szczegółowe reguły wersjonowania obowiązujące
> wszystkich agentów AI (Claude Code, Codex, Copilot, Cursor itp.).

## Architektura — kluczowa zasada

**Logika domenowa jest oddzielona od UI.** Moduły poniżej NIE importują PySide6:
`models`, `parser`, `api`, `i18n`, `audio_sync`, `overlay`, `render`, `ffmpeg`, `resources`.
Warstwy wejścia to tylko `gui.py` (PySide6) i `cli.py`. Trzymaj ten podział — dzięki niemu
przyszły wariant WWW doda jedynie `web/` (backend + frontend) i zaimportuje istniejące moduły.

## Mapa modułów (`src/piro_overlay/`)

- `models.py` — dataclassy: `Shot`, `Session`, `OverlayStyle`; enumy `AnchorMode`
  (`START_SIGNAL` / `FIRST_SHOT`), `Lang` (`PL` / `EN`).
- `parser.py` — `parse_timeline(text)`; format `"N: czas s (+split s)"` (split opcjonalny).
  Wspólny dla tekstu i pola `opis` z API.
- `pipeline.py` — WSPÓLNA orkiestracja CLI+WWW (bez Qt/argparse/print): `build_session`,
  `audio_source` (proxy LRF), `detect_start_signal` (bzyczek=T0), `detect_anchor`,
  `compute_t0`, `compute_trim` (+`DEFAULT_AUTO_WINDOW`, `PipelineError`). Helpery w `cli.py`
  są cienkimi wrapperami (zachowują printy i `SystemExit`); `tests/test_cli.py` pilnuje
  równoważności. NOWĄ logikę przepływu dodawaj TU, nie w cli/gui/web.
- `preview.py` — domenowa kompozycja podglądu klatki (Pillow): `compose_preview(frame,
  session, t, t0, style, duration, video_h)` = panel aktywny dla t + zegar (zamrożony na
  ostatnim strzale, jak w renderze); `scaled_style` skaluje offsety do rozdzielczości
  podglądu (WYSIWYG). Odtwarza `gui._on_scrubber_frame_ready` — gui.py celowo NIE został
  przepięty (świadoma duplikacja, zero ryzyka regresji .exe).
- `api.py` — `fetch_session(id)` + `session_from_payload(payload)`. Oś czasu czytana z
  `data.opis`; metadane z `nazwa_toru`, `uczestnik`, `czasy.*`, `hit_factor`. Opcjonalny
  prefiks `opis` ("opoznienie startu Xs") jest odcinany `parser.extract_start_delay`
  PRZED `parse_timeline` — patrz `Session.start_delay` w sekcji „Funkcje po MVP".
- `i18n.py` — `Translator` z fallbackiem (wybrany język → EN → `[klucz]`). Etykiety dla
  nakładki i GUI w jednym miejscu (`_STRINGS`).
- `audio_sync.py` — `detect_onsets` / `detect_start` (RMS + próg adaptacyjny);
  `resolve_t0(anchor, mode, first_shot_time)` przelicza kotwicę na T0.
- `overlay.py` — render paneli PNG (Pillow): `render_shot_panel`, `render_summary_panel`,
  `render_start_banner`, `panel_origin`. Deterministyczny (umożliwia snapshoty).
  **Stały rozmiar panelu (v0.18.0):** `_render_panel(..., fixed_size)` wymusza min. rozmiar
  tła/obramowania; `shot_panel_max_size(session, style, vs)` i `clock_panel_max_size(style,
  vs, max_elapsed)` liczą max przez `_panel_size` (bez rysowania). Dzięki temu **panel strzału**
  (= „panel z informacjami o strzale", `render_shot_panel`/`_shot_lines`) ma stałą szerokość
  dla wszystkich strzałów (np. „Strzał 6 z 18" i „18 z 18" — to samo tło), a panel zegara nie
  pulsuje przy 9.9→10.0. WAŻNE: snapshoty wołają render_*_panel BEZ `fixed_size` (None) →
  rozmiary bez zmian; `fixed_size` używa tylko render.py/gui (podgląd WYSIWYG).
- `render.py` — `build_events` (rozłączne okna czasowe) + `render_video` (filtergraph FFmpeg
  `overlay=...:enable='between(t,a,b)'`, jeden przebieg, audio zachowane, raport postępu).
- `ffmpeg.py` — `probe` (ffprobe albo parse `ffmpeg -i`), `extract_audio`, `extract_frame`.
  FFmpeg z `imageio-ffmpeg` (bez zależności systemowej).
- `resources.py` — ścieżki do fontów; obsługuje `sys._MEIPASS` (tryb .exe) i tryb dev.

## Model czasu

Wszystkie czasy strzałów są względem **T0 = sygnał startu**. Panel strzału *i* widoczny w
`[T0+czas_i, T0+czas_(i+1))`; ostatni przez `_LAST_SHOT_HOLD` (2 s), potem podsumowanie do
końca. Plansza START tylko gdy `AnchorMode.START_SIGNAL`.

## Wersjonowanie (OBOWIĄZEK)

Jedyne źródło prawdy: `src/piro_overlay/__init__.py` → `__version__`.
`pyproject.toml` musi być zawsze w sync z `__init__.py`.
GUI czyta wersję przez `from . import __version__` i pokazuje ją w tytule okna.
CLI: `piro-overlay --version`.

**Schemat: MAJOR.MINOR.PATCH**
- PATCH (+0.0.1) — naprawa buga, kosmetyka, małe poprawki.
- MINOR (+0.1.0) — nowa funkcja, zmiana zachowania, nowy moduł.
- MAJOR (+1.0.0) — przełomowa zmiana architektury lub API.

**Zasada:** przy każdej sesji z wprowadzonymi zmianami funkcjonalnymi lub naprawionymi bugami
Claude Code **musi** zaproponować i wykonać bump wersji przed zakończeniem pracy.
Nie odkładaj bumpów na „potem" — każdy build powinien mieć unikalną wersję.

## Uruchamianie

```bash
# testy
PYTHONPATH=src pytest
# regeneracja snapshotów paneli
PIRO_UPDATE_SNAPSHOTS=1 PYTHONPATH=src pytest tests/test_overlay.py
# CLI (test end-to-end)
PYTHONPATH=src python -m piro_overlay.cli --video in.mp4 --timeline "1: 1.0s | 2: 2.5s (+1.5s)" --t0 0.5 -o out.mp4
# GUI
PYTHONPATH=src python -m piro_overlay.gui
```

## Build .exe (Windows) — DZIAŁAJĄCA KONFIGURACJA

PyInstaller **nie robi cross-compile** — `.exe` buduj na Windows (to repo bywa pod WSL/Linux).
Newralgiczne: imageio-ffmpeg nie pakuje binarki FFmpeg automatycznie. `build_exe.spec`
rozwiązuje to, dokładając binarkę do `imageio_ffmpeg/binaries` oraz fonty do `assets/fonts`.

Sprawdzona komenda:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e .
pip install pyinstaller
pyinstaller build_exe.spec
# wynik: dist\PiroOverlay.exe
```

Jeśli po uruchomieniu `.exe` pojawi się błąd o braku FFmpeg, sprawdź czy binarka faktycznie
trafiła do bundla (`imageio_ffmpeg/binaries/`). Alternatywa awaryjna: ustaw zmienną
`IMAGEIO_FFMPEG_EXE` na ścieżkę do binarki obok `.exe`.

## Funkcje wprowadzone po MVP

- **Punkt wejścia .exe:** `app.py` (importuje `piro_overlay.gui`) — NIE pakuj `gui.py` jako
  entry, bo importy względne padną (`__main__` bez pakietu).
- **Brak migającej konsoli (Windows):** `ffmpeg.CREATE_NO_WINDOW` w każdym `subprocess`
  (`ffmpeg._run` i `render._run_with_progress`).
- **Przycinanie:** `render.render_video(..., trim_start, trim_end)` — `-ss`/`-t` + przesunięcie
  okien nakładki o `trim_start` (oś wyjścia startuje od 0). `audio_sync.detect_*` przyjmują
  okno `[start, end]`.
- **Auto-przycięcie:** `render.auto_trim_window(t0, last_shot_time, tail, lead_in, duration)`
  — czyste, testowane (`tests/test_render.py`). GUI/CLI liczą okno i podają jako trim.
- **GPU (NVENC):** `render.render_video(..., encoder="auto"/"gpu"/"cpu", on_encoder=cb)`;
  `_resolve_encoder` + fallback na x264 przy błędzie; `on_encoder` raportuje faktyczny enkoder
  (GUI pokazuje go po renderze + status NVENC w grupie „Wyjście"). Wybór binarki w
  `ffmpeg._resolve_ffmpeg()`: env `PIRO_FFMPEG` → wbudowany pełny ffmpeg (`assets/bin`,
  dokładany przez `build.ps1 -WithFfmpeg`) → systemowy z NVENC → imageio-ffmpeg (CPU).
  Binarka imageio-ffmpeg NIE ma NVENC.
- **Waveform:** `audio_sync.compute_waveform` → `gui.WaveformWidget` (klik=kotwica,
  uchwyty=trim, znaczniki=onsety). Ctrl+klik = podgląd klatki z nakładką (scrubber).
- **Wykrywanie sygnału startu (bzyczek):** `audio_sync.detect_dji_start` rozpoznaje buzzer
  shot-timera po DWÓCH cechach (okna 50 ms, FFT): (1) **koncentracji** energii w paśmie
  2000–4800 Hz = `energia_w_paśmie/energia_całkowita ≥ 0.7` (bzyczek to czysty ton —
  niemal cała energia w paśmie; typowy timer gra ~2.7 kHz, ale timer z sesji
  2026-07-19 grał 4.6 kHz i sufit 4500 go odrzucał — stąd 4800, z odstępem od
  protokołu ID ≥4900 Hz; guard: `test_detect_dji_start_ignores_id_tones`)
  oraz (2) **ciągłości** ≥150 ms (3 okna). Wybiera
  NAJWCZEŚNIEJSZY taki przebieg (start poprzedza strzelanie), zwraca narastające zbocze.
  WAŻNE — czego NIE robić: samo „najgłośniejsze okno w paśmie" zawodzi, bo donośny strzał
  (szerokopasmowy) potrafi mieć w paśmie więcej energii niż buzzer; rozróżnia je dopiero
  koncentracja (strzał: energia od basu po wysokie → niska koncentracja) + ciągłość (strzał
  <100 ms). FALLBACK gdy główny test nic nie znajdzie (bzyczek krótki/zagłuszony — tylko 1
  okno przebija próg koncentracji): bierze najwcześniejsze okno o conc≥0.7, którego
  **dominująca częstotliwość jest stabilna ±150 Hz przez ≥150 ms** (ton ma stałą częstotl.,
  strzał błądzi). Fallback odpala się tylko gdy główny zwróciłby None — zero regresji.
  GUI: przycisk „Wykryj sygnał startu" (obok „Wykryj kotwicę") wymusza
  `AnchorMode.START_SIGNAL` i ustawia wynik jako T0; zwykłe „Wykryj kotwicę" używa
  `detect_start` (bez filtra, pierwszy onset).
- **Dekodowanie ID sesji z sygnału tonowego (v0.27.0, protokół v2 od v0.33.0):**
  `audio_sync.decode_id_tone` odczytuje 4-cyfrowe ID sesji z pary timer↔kamera — timer
  (www.timer.pifpaf.fun) i kalkulator (www.piro-kalkulator.pifpaf.fun, `id_tone.js`)
  po zapisaniu sesji odtwarzają kod przez głośnik telefonu: marker 5000 Hz („tu zaczyna
  się kod") + 4 cyfry + cyfra kontrolna (`_id_tone_checksum` = suma ważona pozycją 1–4
  mod 10 — odczyt niezgodny z checksumą jest ODRZUCANY, żeby nie pobrać cudzej sesji),
  każda jako jeden z 10 tonów 5200–7000 Hz (co 200 Hz), ton 300 ms + 50 ms ciszy,
  sekwencja powtórzona 2× dla odporności. **Protokół v2 (v0.33.0) NIE jest kompatybilny
  z v1 (5250–7500 Hz co 250 Hz, 200 ms, bez checksumy)** — nagrania sprzed zmiany nie
  dekodują się nową wersją; wydawać RAZEM z aktualizacją timera i kalkulatora (stałe
  `ID_TONE_*` + `idToneChecksum` muszą się zgadzać po obu stronach). Sufit pasma obniżony
  z 7500 Hz, bo pomiar realnego nagrania DJI (odległy telefon) pokazał zanik tonów >7 kHz
  w łańcuchu głośnik → mikrofon → AAC; dłuższy ton przeżywa zjadanie ogona przez AAC.
  Mikrofon kamery nagrywa to razem z obrazem. Dekodowanie jest SLOT-owe (nie
  continuity-owe jak bzyczek): marker daje kotwicę w czasie, więc każda cyfra jest
  odczytywana w z góry znanym oknie jako ton o najwyższej koncentracji energii wśród
  10 kandydatów — nie trzeba szukać ciągłości per cyfra. **Odporność na ciche nagrania (v0.32.0),** wynik analizy realnego pliku DJI,
  gdzie telefon grał daleko od kamery i AAC ścinał ciche wysokie tony (7250/7500 Hz były
  ~2× krótsze niż nominalne 200 ms → koncentracja ~0.36 < próg 0.55): (1) **dominacja
  względna** — cyfra przechodzi też, gdy `conc ≥ 0.30` I `≥ 4×` drugi kandydat (słaby,
  ale jednoznaczny ton; pozostałe pasma ~0, więc brak ryzyka pomyłki); (2) **głosowanie
  per-slot** — każdy wykryty marker wnosi odczytane cyfry (ważone koncentracją) do
  wspólnej puli per slot, NIE wymagamy kompletnego odczytu z jednego markera
  (powtórzenia uzupełniają się nawzajem; wcześniej: najczęstszy PEŁNY odczyt).
  **Dekoder „polowy" (v0.34.0)** — pakiet zmian po pierwszej sesji polowej v2
  (35 nagrań DJI z 2026-07-15: 28/35 → po zmianach 33/35 = 100% plików, w których
  sygnał fizycznie jest w audio; 2 pozostałe to brak sygnału, marker_max 0.09–0.16):
  (1) metryka **„lokalny SNR"** = energia pasma kandydata / energia pasma protokołu
  `_ID_TONE_RANGE` 4900–7100 Hz (NIE całego widma — strzały/wiatr/mowa poza pasmem
  zaniżały starą koncentrację); (2) odczyt slotu = **najlepsze OKNO slotu (max)**, nie
  średnia 3 okien wokół środka (ton z „dziurą" amplitudy w środku padał, choć brzegi
  były czyste); (3) **duchy powtórzeń** — odstęp powtórzeń jest znany (2.4 s), więc
  wykryty marker czyta też sloty sąsiedniego powtórzenia, którego marker nie zrobił
  własnego runu; (4) **erasure recovery z checksumy** — dokładnie 1 nieczytelny slot
  danych jest odzyskiwany (wagi 1/3 jednoznacznie; wagi 2/4 → 2 kandydatów, rozstrzyga
  energia pasm, bez wyraźnego zwycięzcy → None); (5) **marker z edge-floor**
  (`_ID_TONE_MARKER_EDGE`) — miękki próg mostkuje dziury w runie, ale onset = pierwsze
  TWARDE okno (miękki onset z pre-echa przesuwał siatkę slotów → okno łapało ogon
  POPRZEDNIEJ cyfry). GUARDY przeciw fałszywym ID (każdy z realnego przypadku!):
  `_ID_TONE_ENERGY_FLOOR` (okna słabsze niż 1% mediany energii okien markera odpadają —
  metryki względne kłamią w prawie-ciszy: pre-ringing resamplera dawał snr 0.19 na
  energii 1e-9); `_ID_TONE_MARKER_ENERGY_FRAC` (run markera <2% energii najgłośniejszego
  = pisk tła, nie powtórzenie — jego śmieciowe głosy 0.3–0.5 potrafiły przegłosować
  dwa pełne odczyty); rescue wymaga odczytów pełnej jakości (≥`_ID_TONE_CONC_MIN`)
  we wszystkich czytelnych slotach; **reguła „duchy uzupełniają, nie zastępują"** —
  gdy żaden zwycięski slot nie ma głosu z REALNEGO markera → None (nagranie BEZ sygnału
  złożyło raz ID 3111 przechodzące checksumę: pisk 5 kHz jako marker + obcy ton
  w slotach ducha).
  Testy: `tests/test_id_tone.py` (dominacja = cicha cyfra + ton zakłócający W pasmie
  protokołu; szum poza pasmem ignorowany; dziura amplitudy w środku tonu; duchy;
  odzysk z checksumy + odmowa przy dwuznaczności; cichy fałszywy marker odfiltrowany;
  sekwencja tylko-z-duchów odrzucona; głosowanie per-slot; checksum błędna/wyciszona →
  None); `conftest.id_tone_expr` ma parametry `skip_slots`/`slot_amps`/`checksum_offset`/
  `skip_markers`/`t_start` i sam dolicza cyfrę kontrolną.
  Pasmo 5000–7000 Hz wybrano tak, by (1) NIE kolidować z pasmem bzyczka 2000–4800 Hz i
  (2) zmieścić się pod Nyquistem tej samej ekstrakcji audio 16 kHz (`_load_audio`, Nyquist
  8000 Hz) — bez potrzeby osobnej ścieżki ekstrakcji o wyższym sample rate; sufit 7000 Hz
  (nie 7500 jak w v1) wynika z pomiaru realnego nagrania — patrz uzasadnienie v2 wyżej.
  GUI: przycisk „Wykryj ID z audio" (grupa źródła danych, pod polem ID) woła
  `decode_id_tone` NA `self.video_path` (świadomie NIE na proxy LRF — sygnał ID gra pod
  koniec nagrania, poza oknem na które LRF było dotąd używane) i wpisuje wynik do
  `id_spin`; nie robi auto-fetch — użytkownik klika „Pobierz" sam, jak przy T0.
- **Płynący zegar od T0:** `OverlayStyle.show_running_clock` (checkbox „Płynący czas od T0").
  Nad nakładką ze strzałami tyka „T+x.xs" liczone od sygnału startu, widoczne od STARTU
  (t ≥ T0). `render.prepare_clock(style)` zwraca bool: `_clock_drawtext_seg` (filtr `drawtext`,
  gładkie dziesiąte s, tani, bez plików) gdy drawtext REALNIE koduje (`_drawtext_usable()` —
  test 1 klatki, cache), inaczej fallback SEKWENCJA PNG. Integrację robi `_append_clock`
  (wspólne dla render_video/webm/gif): drawtext→1 seg, inaczej `_write_clock_sequence` →
  JEDNO wejście `-framerate {fps} -f image2 -i clk_%05d.png` + JEDEN `overlay=…:eof_action=repeat`.
  WAŻNE: NIE wracać do „panel PNG na każdy tick = osobne wejście+overlay" — przy 0.1 s to
  setki wejść i przepełnienie linii poleceń Windows (~32 KB). Sekwencja daje dziesiąte
  s na KAŻDEJ binarce (image2 jest zawsze; imageio-ffmpeg NIE ma drawtext).
  **PŁYNNOŚĆ (v0.16.0):** fps sekwencji = fps wideo (`info.fps`), a nie stałe 10 — bo 10 fps
  na wideo NTSC (29.97/59.94) dawało DUDNIENIE (nierówna kadencja = „zacinanie"). Teraz 1:1:
  jedna klatka zegara na klatkę wyjścia → równo. Gdy klatek za dużo, fps redukujemy
  CAŁKOWITYM dzielnikiem `base_fps/k` (nadal dzieli fps wideo bez dudnienia), nie dowolnym
  ułamkiem. Treść i tak zaokrąglona do dziesiątych (cyfra zmienia się co 0.1 s).
  **ZAMROŻENIE (v0.16.0):** zegar płynie tylko do `last_shot_time` (= `session.shots[-1].czas`,
  czas od T0), potem ZAMARZA — sekwencja kończy się na ostatnim strzale (krótsza!), a
  `overlay=…:eof_action=repeat` (NIE `pass` — pass = zegar znika!) powtarza ostatnią
  (zamrożoną) klatkę do końca. drawtext: analogicznie `elapsed = min(t-c, last_shot_time)`.
  Klatki przed STARTEM przezroczyste; każdy panel renderowany z `fixed_size =
  clock_panel_max_size(...)` (rozmiar przy elapsed ostatniego strzału = najwięcej cyfr),
  więc WSZYSTKIE klatki są identycznego rozmiaru i klejone w (0,0) → krawędzie (w tym DOLNA)
  nie skaczą przy 9.9→10.0, `xy` stałe (v0.18.0; wcześniej panel zmiennej wielkości klejony
  top-align na płótnie → dolna krawędź skakała). Limit `_CLOCK_SEQ_MAX_FRAMES=1800`. W GIF
  paleta to kolejne wejście: `pal_idx = inputs.count("-i")` (NIE `used+1` — sekwencja zegara
  też zajmuje wejście). Pozycja zegara `_clock_xy`/`_max_panel_h` wg rogu kotwicy. Podgląd
  rysuje zegar przez `overlay.render_clock_panel`. WAŻNE (drawtext): dwukropki w `%{eif\:…\:d}`
  MUSZĄ być eskejpowane `\:` (przecinek w `%{…}`, np. `min(a,b)`/`mod(x,10)`, jest OK bez
  eskejpu), a wartości opcji (text/x/y/enable) w apostrofach; eif daje tylko int, więc
  sekundy i dziesiąte liczone osobno przez `trunc`.
- **Auto-detekcja T0 + przycięcie:** `gui.StartDetectWorker` (QThread) odpala
  `detect_dji_start` w tle. Po wczytaniu pliku (`_on_wave_done` → `_auto_detect_t0()`):
  T0 + przycięcie 5 s przed → max 75 s po T0. Przycisk „Pobierz i przytnij"
  (`_fetch_id_and_trim`): pobranie z API + T0 + przycięcie 5 s przed → ostatni strzał + 5 s.
  Zwykły „Pobierz" (`_fetch_id`) tylko pobiera dane (bez detekcji i przycięcia).
  WAŻNE: „Pobierz i przytnij" (`_fetch_id_and_trim`) działa SYNCHRONICZNIE — używa
  T0 już wykrytego przy imporcie (`t0_spin`), a gdy go brak, wykrywa raz na LRF; zawsze
  daje widoczny wynik/komunikat (asynchroniczna detekcja w tle bywała „cicho pusta" =
  wyglądała jak brak działania). Detekcja po imporcie nadal w tle: token pokolenia
  (`_detect_gen`) w `_on_autodetect_t0` odrzuca przestarzałe wyniki; workery trzymane
  w `_detect_workers` do `finished` (inaczej QThread niszczony w trakcie = crash).
- **Przeciąganie pozycji w podglądzie:** `gui.PreviewLabel` (QLabel) w trybie edycji
  (`edit_pos_btn`) mapuje mysz → piksele klatki (uwzględnia wyśrodkowany pixmap z letterboxem)
  i emituje `grabbed/dragged/dropped`. `MainWindow` trafia w `_preview_rects` ('panel'/'clock',
  zegar ma priorytet), a `_invert_offset` (odwrotność `overlay.panel_origin`) liczy offset z
  nowego lewego-górnego rogu wg rogu kotwicy. WAŻNE: podgląd renderuje z `_scaled_style`
  (offsety × `frame_h/video_h`), więc podgląd ≈ render (WYSIWYG); drag dzieli deltę przez ten
  sam współczynnik → offsety w pikselach WYJŚCIA. `_video_size` z `probe` przy wczytaniu.
  Zegar w trybie „auto" przy przeciąganiu przełącza się na konkretny róg (róg panelu).
- **Tryb bezgłowy (.exe = GUI + CLI):** `app.py` rozgałęzia: bez argumentów → GUI, z
  argumentami → `cli.main()`. Na Windows `_attach_parent_console()` podpina konsolę rodzica
  (`AttachConsole(-1)` + reopen `CONOUT$`), bo exe budujemy jako GUI (`console=False`) i bez
  tego CLI byłby „niemy". CLI: `--auto` (wykryj T0=bzyczek `detect_dji_start`, wymusza
  START_SIGNAL, + auto-przytnij), `--auto-window N` (stałe okno N s po T0 zamiast „ostatni
  strzał + tail"; gdy brak osi → domyślnie 75 s), `--lead-in` (s przed T0), `--no-overlay`
  (`trim_video`), `--clock` + `--clock-position`/`--clock-offset-x/y`. Grupa `--timeline/--id`
  jest opcjonalna (wymagana tylko dla nakładki). Detekcja używa proxy LRF (`_audio_src`).
- **Zatrzymanie renderu:** przycisk „Zatrzymaj" → `RenderWorker.cancel()` ustawia flagę;
  `render._run_with_progress(..., cancel_check)` sprawdza ją przy każdej linii postępu,
  ubija proces FFmpeg (`proc.kill()`) i podnosi `render.RenderCancelled`. `RenderWorker`
  łapie ten wyjątek, usuwa niedokończony plik i emituje `cancelled` (nie `failed`).
  `cancel_check` przewleczony przez `render_video`/`render_webm`/`render_gif`/`trim_video`.
  `closeEvent` też woła `cancel()` + `wait()`, by nie zniszczyć żywego QThread.
- **Przetwarzanie wsadowe (auto + ID):** przycisk „Wsadowo…" (obok „Kolejka") → `BatchDialog`.
  Dodajesz wiele plików, podajesz ID per plik, „Przygotuj wszystkie" odpala `BatchPrepWorker`
  (QThread/plik): `api.fetch_session(id)` → `detect_dji_start` (na LRF jeśli jest) →
  `auto_trim_window(t0, ostatni_strzał, tail=5, lead_in=5, dur)`. Dwufazowy cykl: faza
  PRZYGOTOWANIA (fetch+T0, statusy `BatchRowStatus`) jest ODDZIELNA od renderu — gotowe wiersze
  „Wyślij gotowe do kolejki" buduje z nich `RenderJob` (kwargs jak `_collect_render_kwargs`,
  `mode=START_SIGNAL`) i dokłada do WSPÓLNEGO `RenderQueueRunner`/`RenderQueueWindow` (render
  bez zmian). Tryb wymuszony: źródło=ID, kotwica=START_SIGNAL. Wspólne dla partii: styl
  (kopia `current_style()`, tylko toggle zegara), katalog docelowy, sufiks nazwy
  (`stem+suffix+ext`), format, GPU, nakładka on/off. Per-wiersz przycisk „▶" =
  `QDesktopServices.openUrl` na pliku ŹRÓDŁOWYM. PUŁAPKI QThread (jak reszta): pola NIE
  `start`/`end`; workery trzymane w `_workers` do `finished`; `closeEvent` (główne+dialog)
  czeka na żywe workery. Zmiana ID unieważnia przygotowanie wiersza.
  **Wykrywanie ID z audio we wsadzie (v0.31.0):** przycisk „Wykryj ID z audio" (górny
  pasek, obok importu ze schowka) dla wierszy bez ID (`NEEDS_ID`) odpala
  `BatchIdDetectWorker` (QThread/plik) z `audio_sync.decode_id_tone` na ORYGINALNYM
  pliku (nie LRF — jak `_detect_id_tone` w głównym oknie; sygnał ID gra pod koniec
  nagrania). Wynik wpisywany do spinboxa wiersza (`set_session_id` → `_on_id_changed`
  → status PENDING) — BEZ auto-fetch: użytkownik weryfikuje ID przed „Przygotuj
  wszystkie" (błędnie zdekodowane ID pobrałoby cudzą sesję z API). Brak sygnału to
  nie błąd — wiersz wraca do `NEEDS_ID` z info „nie wykryto ID — podaj ręcznie"
  (`row.error`, czyszczone przy ręcznej zmianie ID). Nowy status
  `BatchRowStatus.DETECTING`; wszystkie guardy zajętości (usuwanie/czyszczenie/zmiana
  ID/refresh/closeEvent) używają wspólnej krotki `_BATCH_BUSY` (DETECTING+PREPARING).
  W `_on_id_detected` status wraca na `NEEDS_ID` PRZED `set_session_id` — inaczej
  guard `_BATCH_BUSY` w `_on_id_changed` odrzuciłby wpisywaną wartość.
  **Eksport/import schowka:** „Eksport → schowek" zrzuca listę jako wiersze
  `<ścieżka>;<ID>` (`QApplication.clipboard().setText`); „Import ze schowka" parsuje to samo
  (`rpartition(';')` — ID zawsze po OSTATNIM średniku, ścieżka Windows bezpieczna). Istniejąca
  ścieżka → aktualizacja ID (`BatchRowWidget.set_session_id` przez spinbox), nowa → `_add_row`.
- **Kolejka renderów — współbieżność (v0.35.0):** `RenderQueueRunner` renderuje do
  `_parallel` zadań NARAZ (`_fill_slots` dosypuje do wolnych slotów, też przy `add_job`
  w trakcie); spinner „Równoległe" w oknie kolejki (1–4, `config.save/load_queue_parallel`,
  `ui_settings.json` w AppData, domyślnie 2). POWÓD (pomiar Task Managera przy renderze
  4K NVENC): Video Encode ~45%, Decode 12%, CPU 44% — nic nie jest wysycone, bo łańcuch
  `overlay` w FFmpeg jest częściowo jednowątkowy i wszystko czeka na wszystko; dwa
  równoległe pliki ≈ 2× przepustowość partii (NVENC ma 5–8 sesji na współczesnych
  sterownikach). „Zatrzymaj" anuluje WSZYSTKIE biegnące workery (każdy wraca do PENDING);
  finalizacja (queue_stopped/finished) dopiero gdy OSTATNI worker realnie skończy —
  `_finish_worker(job_id)` robi `wait()` przed zwolnieniem referencji (ta sama pułapka
  QThread co niżej, przy wielu workerach podwójnie krytyczna). Busy-flaga główna zdejmowana
  dopiero, gdy pula pusta. Łączny % w pasku stanu = suma postępów wszystkich biegnących
  (`RenderQueueWindow._progress` per job). Dalszy potencjał (świadomie NIE zrobione):
  pełny potok GPU `overlay_cuda` + `-hwaccel_output_format cuda` — wymaga weryfikacji
  obsługi `enable`/alfy na docelowej binarce FFmpeg, patrz dyskusja przy v0.34.0.
- **Kolejka renderów — zapis/odczyt + % postępu:** `RenderQueueWindow` ma „Zapisz/Wczytaj
  kolejkę" (plik `render_queue.json` w AppData; `config.save_queue`/`load_queue`). Zapis (też
  AUTO przy każdej zmianie statusu i `add_job` — odzysk po awarii) pomija zadania `DONE`
  (`_queue_payload`) → w pliku zostają tylko niewykonane/`FAILED` (do ponowienia). Wczytanie
  zeruje status do `PENDING`. Serializacja: `_job_to_dict`/`_job_from_dict` (Session/OverlayStyle
  przez `to_dict`/`from_dict`, `AnchorMode` przez `.value`). Pasek postępu wiersza jest teraz
  ZAWSZE wyznaczony (0–100, `setTextVisible`+`%p%`) — koniec „barber pole" bez liczb; postęp
  realny z `render._run_with_progress`. Pasek stanu pokazuje łączny %: `_update_overall`
  (`(done+bieżący)/total`). Przycisk „Zatrzymaj" (`RenderQueueRunner.stop`): `_stopping=True`
  + `cancel()` bieżącego workera → przerwane zadanie wraca do `PENDING`, kolejka pauzuje
  (sygnał `queue_stopped`), „Start kolejki" wznawia. `RenderWorker.cancelled` jest TERAZ
  podłączony w runnerze (`_on_job_cancelled`) — bez tego cancel zawieszał kolejkę.
  **KRYTYCZNY FIX CRASHU (v0.21.0):** `_on_job_done/_failed/_cancelled` wołają `_finish_active`,
  które robi `worker.wait()` PRZED zwolnieniem referencji. Sygnały kończące lecą z OSTATNIEJ
  linii `run()` (wątek jeszcze żyje); wcześniejsze `self._active_worker = None` niszczyło
  QThread „w trakcie" → twardy crash (po renderze GPU pierwszego pliku, gdy startował kolejny).
  To ten sam pułap co przy detekcji T0 — workery muszą dożyć realnego końca wątku.
- **Postęp przez `-progress`, „Zatrzymaj" ubija proces, dzienniki w AppData (v0.21.1):**
  `render._run_with_progress` dokłada `-progress pipe:2 -nostats` → FFmpeg wypisuje postęp
  REGULARNIE (parsowane `out_time_ms/us=`, `_OUT_TIME_MS_RE`), nawet przy ciężkim filtergrafie,
  który wcześniej nie wypisywał NIC przez dziesiątki sekund (→ brak %, a pętla czytająca stderr
  blokowała się, więc `cancel_check` nie miał kiedy zadziałać — „Zatrzymaj" wisiało na „kończę
  klatkę"). `RenderWorker.cancel()` TERAZ od razu `proc.kill()` (uchwyt dostarcza `on_process`
  przewleczony przez render_video/webm/gif/trim_video → `_run_with_progress`); zabicie procesu
  odblokowuje czytanie stderr (EOF). DIAGNOSTYKA: `_log_render` pisze komendę FFmpeg + wynik do
  `render_log.txt`; `gui._install_crash_logging` włącza `faulthandler` (zrzut stosów wszystkich
  wątków przy NATYWNYM crashu — segfault/`abort()`) + `sys/threading.excepthook` → `crash_log.txt`
  (oba w AppData). To jedyny ślad, gdy aplikacja pada twardo. UWAGA: `render.py` importuje teraz
  `config` (do ścieżki AppData) — bez cyklu (`config`→`models`).
- **Ogon błędu bez spamu postępu + kod wyjścia (v0.23.1):** wiersze bloków `-progress pipe:2`
  (`frame=`/`out_time=`/`speed=`/… — `_PROGRESS_LINE_RE`) NIE trafiają do `tail` błędu —
  zalewały 80-liniowy ogon tak, że „Błąd renderu" pokazywał SAM postęp, a faktyczny błąd
  FFmpeg (albo jego BRAK) ginął. RuntimeError niesie teraz kod wyjścia + ostatnie
  `out_time=` („gdzie padło"); kod UJEMNY = proces ubity sygnałem (typowo OOM killer —
  render 4K na x264 potrafi przekroczyć `mem_limit: 4g` z web/docker-compose.yml).
  Web `workers.py` przy ucinaniu do 800 znaków zachowuje PIERWSZĄ linię (kod/pozycja).
- **DJI = drugi strumień wideo (miniatura MJPEG) → `0:v:0`, nie `0:v` (v0.21.2):** pliki DJI
  (np. Osmo Nano) mają OPRÓCZ głównego HEVC jeszcze `Video: mjpeg ... (attached pic)` 640x480.
  `-map 0:v` (trim) i `[0:v]` (filtergraph) łapały OBA → FFmpeg próbował wepchnąć miniaturę jako
  drugi strumień H.264 do mp4 → „Could not write header / Nothing was written / Conversion
  failed!" → **plik 0 B za każdym razem** (objaw zgłaszany jako „crash kolejki"). Fix: WSZĘDZIE
  bierzemy tylko pierwszy strumień: `cur = "0:v:0"` (render_video/webm/gif) i `-map 0:v:0`
  (trim_video). Diagnoza wyszła z `render_log.txt` (patrz wpis o `-progress`/dziennikach).
- **Kolejka: „Start" ponawia FAILED, stop bez deadlocku (v0.21.2):** `RenderQueueWindow._on_start`
  woła `runner.retry_failed()` (FAILED→PENDING) przed startem — inaczej po serii błędów kolejka
  miała same FAILED i „Start" nie miał czego uruchomić (objaw: „po wznowieniu nie działa").
  `_refresh_start_btn` aktywuje Start także przy FAILED. `RenderQueueRunner.stop()` gdy NIE ma
  aktywnego workera (między zadaniami) kończy od razu (`_running=False`+`queue_stopped`), inaczej
  `_running` zostawało True i wznowienie było zablokowane.
- **Format wyjściowy:** `format_combo` w GUI → `render.render_video` (MP4/H.264) /
  `render_webm` (VP9) / `render_gif`. CLI renderuje tylko MP4.
- **Presety wyglądu:** zapisz/wczytaj JSON z pliku; auto-zapis ostatnich ustawień i
  katalogu do `AppData` (przywracane przy starcie).
- **Pamięć ustawień per-plik:** `config.save_file_settings(path, dict)` /
  `load_file_settings(path)` trzymają komplet parametrów w `file_settings.json` (AppData),
  keyed po `Path(path).resolve()`, LRU z limitem `_MAX_FILE_ENTRIES=100`. GUI zapisuje przy
  `_start_render` i `_add_to_queue` (`_collect_file_settings`: styl + źródło/ID + timeline +
  kotwica + T0 + przycięcie + margines + GPU + no_overlay + format + output). Przy
  `_set_video` ładuje wpis do `self._pending_file_settings`; `_on_wave_done` (po analizie
  audio, gdy spiny czasu mają już `setMaximum(dur)`) stosuje go przez `_apply_file_settings`
  i POMIJA auto-detekcję T0 (zapisany T0/trim ma pierwszeństwo). WAŻNE: stosować PO
  `_on_wave_done`, nie w `_set_video` — inaczej `setMaximum` przytnie wczytane wartości.
  `self.session` (dane API) NIE jest zapisywana — przy źródle „ID" user klika „Pobierz".
- **Komenda CLI z GUI:** przycisk „Pokaż komendę CLI" (grupa „Wyjście") →
  `gui._build_cli_command()` składa równoważne wywołanie `PiroOverlay.exe …` z bieżących
  widgetów (wideo, `--id`/`--timeline`, `--anchor` gdy ≠START_SIGNAL, `--t0`, `--lang` gdy
  ≠PL, `--trim-start/-end`, `--encoder cpu` gdy GPU off, `--no-overlay`, `--clock`
  +`--clock-position/-offset-x/y`, `-o`). Pomija domyślne wartości (krótsza komenda).
  `_show_cli_command` pokazuje ją w `QDialog` (read-only `QPlainTextEdit`) z „Kopiuj do
  schowka". WAŻNE: CLI nie obsługuje szczegółów wyglądu (kolory/skala/pozycja panelu/offsety/
  plansza START) — builder je pomija, a nota w oknie o tym informuje. Helpery
  `_cli_quote` (cudzysłów przy spacji) i `_fmt_num` (bez zer końcowych).
- **Ikona:** `assets/icon.png` (okno) + `assets/icon.ico` (.exe, w `build_exe.spec`),
  `resources.icon_path()`.
- **Szybkie iterowanie:** do testów zmian NIE buduj .exe — uruchom ze źródła
  (`python app.py`). Build .exe rób tylko do dystrybucji; nie używaj `-Clean` bez potrzeby
  (cache `build/` przyspiesza kolejne buildy), UPX wyłączony (`upx=False`).
- **Proxy LRF (DJI Osmo):** `ffmpeg.find_lrf(mp4_path)` szuka pliku `.LRF`/`.lrf` obok
  MP4, weryfikuje go przez `probe` i zwraca `Path | None`. `gui._set_video` ustawia
  `self.lrf_path` i przekazuje go do `WaveformWorker` oraz `audio_sync.detect_start` —
  analiza audio chodzi na małym pliku, render zawsze na oryginalnym `video_path`.
- **`Session.start_delay` — opóźnienie startu z API (v0.29.0):** piro-kalkulator dokłada
  teraz opcjonalny prefiks w `data.opis`, PRZED listą strzałów: `"opoznienie startu 2.1s |
  1: 2.28s | ..."` (opóźnienie od naciśnięcia „Start" na timerze do faktycznego początku
  sesji — patrz też CLAUDE.md `www.timer.pifpaf.fun`, `SESSION_STARTED`/`startDelay`, skąd
  ta wartość pochodzi). `parser.extract_start_delay(text)` odcina ten prefiks REGEXEM
  (`^opoznienie startu Xs \|?`) i zwraca `(reszta, delay|None)` — reszta idzie bez zmian do
  `parse_timeline` (BEZ tego prefiksu `parse_timeline` rzuciłby `TimelineParseError` na
  pierwszym tokenie — realna regresja, nie tylko kosmetyka). `api.session_from_payload`
  woła to PRZED `parse_timeline` i ustawia wynik na `Session.start_delay` (nowe pole,
  wliczone w `to_dict`/`from_dict` — przetrwa zapis/odczyt kolejki renderów w AppData).
  ŚWIADOMIE trzymane, ale NIEUŻYWANE jeszcze w żadnej logice (T0/przycięcie/render) — GUI
  (`self.session.start_delay`) i web (`job.session.start_delay`, patrz `session_meta` w
  sekcji webowej) mają do niego dostęp, ale nic nie zmienia się w zachowaniu. Manualne
  wklejanie tekstu (bez prefiksu) działa jak dotychczas — `extract_start_delay` na tekście
  bez prefiksu zwraca `(tekst_bez_zmian, None)`.

## Wersja webowa (`web/`) — v0.24.0

Backend FastAPI + statyczny frontend (vanilla JS, PL) — importuje WYŁĄCZNIE domenę
(`pipeline`, `preview`, `render`, `ffmpeg`, `api`, `models`). ZERO zmian w `gui.py`/
`app.py`/`build_exe.spec`; PySide6 zostaje twardą zależnością pyproject (build .exe bez
zmian), web ma extra `[web]` (dev) i `web/requirements.txt` (Docker, bez Qt).

- **Moduły:** `web/backend/{app,settings,sessions,jobs,workers,api,ratelimit,cleanup}.py`,
  frontend `web/static/{index.html,app.js,style.css}` (kreator 5 kroków).
- **Przepływ:** `POST /api/jobs` (upload surowym strumieniem, nagłówek `X-Filename`,
  licznik bajtów → 413; probe → 422 przy nie-wideo) → `/session` (ID z API lub timeline)
  → `/analyze` (`pipeline.detect_start_signal` + `compute_trim`; brak bzyczka → `t0:null`)
  → `/preview` (PNG: `ffmpeg.extract_frame` + `preview.compose_preview`, cache klatki per
  job) → `/render` (202; pula wątków) → `/events` (SSE: state/progress/encoder/done/error,
  snapshot na wejście, heartbeat 15 s) → `/download`. Anulowanie: `/cancel` = `cancel.set()`
  + `proc.kill()` (uchwyt z `on_process` — jak w GUI).
- **Multi-user:** cookie `piro_sid` (HttpOnly); cudzy/nieznany job → 404 (bez enumeracji);
  katalogi `DATA_DIR/<sid>/<job_id>/` (nazwa klienta NIGDY w ścieżce — `source.<ext>`);
  limity env `PIRO_WEB_*` (upload MB, joby/sesję, rate/min, rendery/h — patrz
  `web/backend/settings.py`); token bucket in-memory; sprzątanie TTL co 10 min +
  osierocone katalogi przy starcie.
- **PUŁAPKA — magazyn in-memory:** uvicorn MUSI mieć `--workers 1` (wpisane w Dockerfile);
  równoległość tylko przez pule wątków (`RENDER_WORKERS`, default 1 — x264 saturuje CPU).
- **PUŁAPKA — FFmpeg w Dockerze:** `_resolve_ffmpeg` bierze systemową binarkę tylko z NVENC,
  więc obraz ustawia `PIRO_FFMPEG=/usr/bin/ffmpeg` JAWNIE (apt ffmpeg = drawtext dla zegara);
  encoder domyślnie `cpu`. `XDG_CONFIG_HOME=/data/config` przekierowuje logi render/config.
- **Deploy:** `docker compose -f web/docker-compose.yml up -d --build`; SSL terminuje
  nginx proxy manager na OSOBNYM hoście — w NPM (Advanced) wymagane:
  `client_max_body_size >= limit uploadu`, `proxy_buffering off` (SSE),
  `proxy_request_buffering off` (upload), `proxy_read_timeout 3600s`.
- **Testy web:** `tests/test_web_api.py`, `tests/test_web_limits.py` —
  `pytest.importorskip("fastapi")` (środowisko builda .exe bez extras zostaje zielone);
  fixture `tiny_video` (`tests/conftest.py`) generuje realny MP4 przez lavfi
  (testsrc + ton 2700 Hz w 0.5–0.9 s = sztuczny bzyczek dla testu `analyze`).
- **Dev lokalny:** `pip install -e .[web]`, potem
  `PYTHONPATH=src uvicorn web.backend.app:create_app --factory --reload`.
- **„Bez nakładki" — przycięcie bez wypalania grafiki (v0.24.0):** checkbox w kroku 02
  (`#no-overlay-check`) wyłącza render nakładki; oś czasu (ID/tekst) NIE jest chowana —
  zostaje opcjonalna, bo gdy jest podana, auto-przycięcie i tak z niej korzysta (ostatni
  strzał + margines, przez `pipeline.compute_trim(session=...)` — działa niezależnie od
  nakładki). WAŻNE: nie chować kroku „Oś czasu" przy tym checkboksie — ktoś może chcieć
  przycięcie zsynchronizowane z ID z API, ale bez wypalonej grafiki. Odblokowanie kroku
  render nie wymaga sesji: `refreshRenderReady` sprawdza `job.noOverlay || job.hasSession`
  (krok „Sygnał startu" jest odblokowany od razu po uploadzie niezależnie od sesji — flow
  już był rozłączony). `/api/jobs/{id}/analyze` działał tu BEZ zmian: `pipeline.compute_trim`
  z `session=None` spada na `DEFAULT_AUTO_WINDOW` (75 s po T0, jak CLI bez osi), a z sesją
  liczy jak zwykle. W kroku 04 pole „Przytnij do (s)" jest zastępowane polem „Długość od
  T0 (s)" (`#duration-input` — czysty JS, `syncTrimEndFromDuration()` przelicza
  `trim-end = t0 + duration` przy każdej zmianie T0/długości; backend zawsze dostaje
  `trim_start`/`trim_end` absolutne, jak dotychczas — `/analyze`/`/render` NIE wiedzą o
  „długości"). Backend: `RenderBody.no_overlay` (bool) — gdy `True`, `/render` NIE wymaga
  sesji/T0 (ale sesja, jeśli jest, i tak trafia do `pipeline.compute_trim` przez `/analyze`)
  i wymusza `format == "mp4"` (422 inaczej — `trim_video` koduje audio jako AAC+faststart,
  niekompatybilne z WebM/GIF); `workers.run_render` dostaje `no_overlay` i woła
  `render.trim_video` zamiast `render_video`/`_webm`/`_gif` (ten sam `common` dict
  progress/cancel/on_process — sygnatury się zgadzają; `trim_video` NIE dostaje `session`,
  więc podana oś i tak nigdy nie trafia na obraz). `/preview` i `compose_preview` nie
  wymagały zmian: `session is None` już zwracał czystą klatkę bez nakładki.
- **Stopka: wersja + link do repo (v0.24.0):** `GET /api/version` (`web/backend/api.py`)
  zwraca `{version: __version__, repo: _REPO_URL}` — jedno źródło prawdy, jak GUI
  (`from . import __version__`). Frontend (`app.js`, ładowane na starcie strony) uzupełnia
  `#app-version`/`#repo-link` w stopce; statyczny href w `index.html` jest fallbackiem,
  gdyby fetch padł (np. offline podgląd pliku).
- **„Zatrzymaj" aktywny tylko w trakcie renderu (v0.24.1):** `setRenderActive(active)`
  (`app.js`) łączy w jednym miejscu `hidden`+`disabled` przycisku (podwójna blokada, jak
  `setEnabled` w GUI) — wcześniej sam `hidden` wystarczał do zablokowania kliknięcia, ale
  handler `state` w SSE synchronizował przyciski tylko dla `cancelled`/`done`; snapshot na
  wejście (np. po odświeżeniu karty w trakcie renderu) dla `queued`/`rendering` NIE ustawiał
  `render-btn`/`cancel-btn` z powrotem — teraz oba stany też wołają `setRenderActive(true)`.
  Przycisk „Pobierz gotowe wideo" (dawniej „Pobierz wynik") jest jawnie chowany też w
  handlerze `error` SSE — błąd renderu nie może zostawić klikalnego linku do pliku, którego
  nie ma (poprzedni render mógł go zostawić widocznym).
- **Pamięć plik → ID w SQLite (v0.25.0):** `web/backend/filedb.py` — tabela
  `file_ids(filename PRIMARY KEY, result_id, updated_at)`, jedna baza per `sid`
  (`DATA_DIR/<sid>/file_ids.db`, jak katalogi zadań — celowo NIE globalna, żeby nazwa
  pliku jednego użytkownika nie podsuwała ID innemu na publicznym hostingu). Zapis
  (`filedb.remember`) dopiero w `start_render`, i TYLKO gdy `job.session_source_id` jest
  ustawione — ustawia je `set_session` przy `source="id"` (przy `"timeline"` czyści na
  `None`), więc same przymiarki (fetch bez kliknięcia „Renderuj") nic nie zapisują.
  `INSERT OR REPLACE` po `filename` (PRIMARY KEY) = trzyma tylko NAJNOWSZE ID dla danej
  nazwy pliku (pomyłka poprawiona kolejnym renderem nadpisuje, nie duplikuje). Odczyt
  (`filedb.lookup`) w `create_job` — odpowiedź uploadu niesie `suggested_id` (`None` gdy
  brak dopasowania); `app.js` w handlerze uploadu auto-wywołuje `setSession({source:"id",
  id: suggested_id})` i pokazuje toast, żeby użytkownik mógł to łatwo poprawić (wpisać
  inne ID i kliknąć „Pobierz" ponownie). Zapis owinięty w `try/except Exception: pass` —
  błąd SQLite (np. brak miejsca na dysku) NIE może zablokować renderu, to funkcja
  pomocnicza, nie krytyczna ścieżka. WAŻNE: dopasowanie po nazwie pliku (nie hashu/treści)
  — inny plik o tej samej nazwie dostanie tę samą podpowiedź (akceptowalne, bo tylko
  auto-wypełnia pole, użytkownik i tak widzi/koryguje ID przed renderem).
- **ETA przy postępie renderu (v0.26.0):** czysto frontendowe (`app.js`) — backend nie
  liczy/nie wysyła ETA, tylko `p` (0–1) jak dotychczas. `updateEta(p)` liczy tempo postępu
  względem punktu odniesienia `etaBase` (czas + `p` z poprzedniej próbki), NIE od zera przy
  każdym evencie — jedna próbka byłaby zbyt szumiąca (FFmpeg nie postępuje liniowo, zwłaszcza
  na starcie). `resetEta()` zeruje punkt odniesienia na nowy render (`render-btn` click) i po
  zakończeniu (`renderFinished`); `updateEta` sam resetuje punkt, gdy `p` spadnie poniżej niego
  (reconnect SSE na starszy stan zadania — inaczej `dp` byłoby ujemne). Wymaga ≥1 s i dodatniego
  `dp` między próbkami, inaczej nic nie wypisuje (unika dzielenia przez ~0 i wyświetlania
  absurdalnych wartości na starcie). Snapshot SSE (`state` przy `queued`/`rendering`, np. po
  odświeżeniu karty w trakcie renderu) teraz też woła `setProgress`/`updateEta` z `data.progress`
  — wcześniej ten branch nie odświeżał wcale paska postępu po reconnect.
- **Wykrywanie ID z sygnału tonowego (v0.28.0):** `POST /api/jobs/{id}/detect-id` woła
  `pipeline.detect_id_tone` (patrz sekcja o `audio_sync.decode_id_tone` wyżej — timer
  odtwarza ID jako marker 5000 Hz + 4 cyfry + cyfrę kontrolną, tony 5200–7000 Hz,
  po zapisie sesji w bazie kalkulatora; protokół v2 od v0.33.0)
  i zwraca `{id: int|None}` — brak sygnału to NIE błąd (jak `/analyze` dla T0), frontend
  prosi o ręczne ID. Guard identyczny jak `/analyze`: 409 gdy zadanie `QUEUED`/`RENDERING`.
  Frontend: przycisk „🔎 Wykryj z audio" w kroku 02 (`pane-id`, obok „Pobierz") woła endpoint,
  wpisuje wynik do `#session-id` i AUTO-WOŁA `setSession()` (v0.29.2 — pierwotnie świadomie
  NIE auto-wołało, żeby błędnie zdekodowane ID nie ustawiło sesji bez potwierdzenia, ale to
  zostawiało „Renderuj" zablokowane (wymaga `job.hasSession`) mimo wypełnionego pola ID i
  wykrytego T0 — wyglądało na ukończony krok, a nie było; realny bug report). GUI nie miało
  tego problemu — `_build_session()` i tak odpytuje `api.fetch_session(id_spin.value())` na
  żądanie renderu, bez pośredniego stanu „sesja ustawiona".
- **`session_meta.start_delay` (v0.29.1):** `Job.to_dict()` dokłada `start_delay` do
  `session_meta` (obok `nazwa_toru`/`uczestnik`) — patrz `Session.start_delay` w sekcji
  desktopowej wyżej. Czysto ekspozycyjne: frontend NIE wyświetla jeszcze tej wartości
  (`app.js` czyta z `session_meta` tylko `nazwa_toru`/`uczestnik` do linii `shots-meta`) —
  dane po prostu docierają do odpowiedzi API, gdyby przyszła funkcja chciała je pokazać.
- **Hardening formularza uploadu i DoS (v0.30.0):**
  - **`ffmpeg.UNTRUSTED_INPUT_ARGS` (`-protocol_whitelist file`) — SSRF/LFI przez spreparowane
    „wideo":** FFmpeg autodetekuje demuxer po ZAWARTOŚCI pliku, nie po rozszerzeniu — plik z
    rozszerzeniem `.mp4`, ale wewnątrz będący playlistą HLS/m3u8 albo listą `concat`, może
    kazać FFmpeg otworzyć DOWOLNY protokół (`http://`, `subfile,file:`, `concat:...`), czyli
    żądania do sieci wewnętrznej hosta (SSRF) albo odczyt dowolnego pliku z dysku serwera. To
    znany, wielokrotnie zgłaszany wzorzec ataku na usługi „upload wideo → `ffmpeg -i`".
    Poprawka dołożona PRZED każdym `-i`, który otwiera plik od użytkownika: `ffmpeg.py`
    (`probe`/`_probe_with_ffprobe`/`_probe_with_ffmpeg`, `extract_audio`, `extract_frame`),
    `audio_sync._load_audio`, `render.py` (`render_video`/`render_webm`/`render_gif`/
    `trim_video` — główne wejście wideo). NIE dotyka własnych wejść (PNG paneli, `-f lavfi`,
    sekwencja zegara `image2`) — te i tak zawsze używają protokołu `file`, więc whitelist
    niczego legalnego nie psuje. Whitelist walidowany testami (`tests/test_ffmpeg.py`,
    `tests/test_render.py`, `tests/test_audio_sync.py` — 141/141 zielone po zmianie).
  - **`X-Forwarded-For` jest spoofowalny — rate limit nie może mu ufać domyślnie:**
    `ratelimit.client_key` (gdy brak cookie `piro_sid`) do v0.29.2 brał PIERWSZY wpis XFF —
    to pole w pełni kontrolowane przez klienta, dopóki między nim a aplikacją nie ma
    zaufanego reverse proxy, który je nadpisuje/dokłada na podstawie realnego adresu
    gniazda. Bez takiego proxy (albo gdy port aplikacji jest też osiągalny bezpośrednio,
    z pominięciem NPM — patrz `docker-compose.yml`, `ports: 8000:8000`) atak mógł ustawiać
    dowolny/losowy XFF na każde żądanie i całkowicie obchodzić `general_rate`/`render_rate`
    (nielimitowane uploady/rendery = DoS na CPU i dysk). Fix: `settings.trust_proxy_headers`
    (env `PIRO_WEB_TRUST_PROXY_HEADERS`, **domyślnie `False`**) — XFF jest ignorowany, dopóki
    ktoś jawnie nie potwierdzi, że stoi za zaufanym proxy; gdy włączone, bierzemy OSTATNI wpis
    (dokładany przez najbliższy hop), nie pierwszy. WAŻNE: samo włączenie tej flagi bez
    odcięcia bezpośredniego dostępu do portu 8000 (firewall / bind tylko dla hosta NPM)
    NIE chroni — atakujący łączący się z pominięciem proxy nadal w pełni kontroluje XFF,
    włącznie z jego ostatnim wpisem.
  - **Globalny sufit zadań niezależny od `sid` (`JobStore.count_active_total`,
    `settings.max_jobs_total`, domyślnie 60):** limit `max_jobs_per_session` sam w sobie nie
    chroni przed nadużyciem, bo `sid` to zwykłe cookie — klient, który go nie odsyła (nie
    przeglądarka, tylko np. skrypt), dostaje przy KAŻDYM żądaniu nowy sid w odpowiedzi i
    per-sesyjny limit nigdy się nie wypełnia. Sprawdzenie w `api.create_job` DODATKOWO do
    `count_active` (per-sid) — niezależny bezpiecznik na dysk/CPU całego serwera.
  - **Nagłówki bezpieczeństwa (`app.py`, middleware `_security_headers`):**
    `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
    ciasny `Content-Security-Policy` (`default-src 'self'`, brak inline script/style — frontend
    już tak działa, `index.html`/`app.js` nie mają inline JS/CSS). Obrona w głąb — aplikacja
    nie osadza treści zewnętrznej ani nie musi być osadzana w cudzych ramkach.
  - **Kontener non-root (`web/Dockerfile`):** obraz tworzył proces jako root (domyślne dla
    `python:3.12-slim` bez `USER`). Skoro FFmpeg parsuje treść uploadowaną przez anonimowych
    userów z internetu, luka w FFmpeg (albo w zależnościach Pythona) nie powinna dawać roota
    w kontenerze. Użytkownik `piroweb` (uid 10001) tworzony PRZED `COPY`/`chown`; `/data`
    tworzone i `chown`-owane w obrazie PRZED przejściem na non-root, żeby Docker skopiował te
    uprawnienia do nazwanego wolumenu (`piro-data:/data`) przy jego pierwszym montowaniu.
  - **NIEZAŁATWIONE świadomie (do rozważenia osobno, poza zakresem tej zmiany):** brak tokenu
    anty-CSRF (obrona dziś to wyłącznie `SameSite=Lax` na cookie `piro_sid`); brak skanowania
    antywirusowego uploadów; port 8000 kontenera nadal wystawiony bezpośrednio w
    `docker-compose.yml` — zalecane odcięcie firewallem do samego hosta NPM, dopiero wtedy
    ma sens włączanie `PIRO_WEB_TRUST_PROXY_HEADERS`.

## Uwagi / pułapki

- **`Lang` to `(str, Enum)` → QComboBox gubi typ:** `lang_combo.addItem("Polski", Lang.PL)`
  + `currentData()` zwraca CZYSTY str `"pl"` (Qt spłaszcza str-enum w QVariant), nie `Lang.PL`.
  Dlatego `OverlayStyle.__post_init__` NORMALIZUJE `lang` do `Lang` (`Lang(self.lang)`).
  Bez tego `to_dict()` (`self.lang.value`) wybuchał i — bo `save_*` łapią wyjątki CICHO —
  blokował zapis stylu i ustawień pliku; objaw: `last_style.json` = 0 B i brak
  `file_settings.json`. Lekcja: nie polegać na typie `currentData()` dla str-enumów.
- **QThread: nie nazywaj pól `start`/`end`** — przesłaniają `QThread.start()`. `StartDetectWorker`
  miał `self.start = start` → `worker.start()` leciało jako `None()` → `TypeError`, a że to
  było w handlerze sygnału, detekcja T0 po imporcie CICHO padała. Pola nazwane `win_start`/
  `win_end`.
- **`ffmpeg.available_filters()` — szerokość kolumny flag:** wiersz `-filters` ma flagi
  2–3 znaki (` T. drawtext   V->V   …`). Regex NIE może zakładać 3 znaków (`[A-Z.]{3}`),
  bo wtedy `drawtext` nie pasuje → `has_filter("drawtext")` zwraca False → płynący zegar
  leci awaryjnym fallbackiem PNG (całe sekundy) zamiast `drawtext` (dziesiąte). Kotwiczymy
  na sygnaturze `wej->wyj`. (Enkodery to inny format — 6 znaków, `available_encoders`.)
- `ffmpeg.probe` parsuje stderr `ffmpeg -i` tylko z linii zawierającej `Video:` (wcześniejsza
  wersja łapała przypadkowe liczby — patrz `_RES_RE`/`_FPS_RE`).
- Snapshoty (`tests/snapshots/*.png`) zależą od bundlowanego fontu DejaVu i wersji Pillow;
  porównanie ma tolerancję `MAX_MEAN_DIFF`. Przy zmianie fontu/renderu — regeneruj.
- Detekcja onsetów jest prosta (RMS); przy hałaśliwym audio użyj ręcznej korekty T0 w GUI.
- **Podgląd vs. render — rozbieżność metadanych:** `_update_preview` używa `self.session`
  (ustawionego przez `_fetch_id`, zawiera `nazwa_toru`/`uczestnik`). `_build_session()` w
  trybie tekstowym musi zawsze wywołać `replace(self.session, shots=shots)` gdy `self.session`
  nie jest `None` — inaczej render dostaje `Session` bez metadanych a podgląd je pokazuje.
  Zasada: podgląd i render muszą korzystać z tej samej sesji (te same metadane).
