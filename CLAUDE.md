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
  `data.opis`; metadane z `nazwa_toru`, `uczestnik`, `czasy.*`, `hit_factor`.
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
  2000–4500 Hz = `energia_w_paśmie/energia_całkowita ≥ 0.7` (bzyczek to czysty ton ~2.7 kHz,
  niemal cała energia w paśmie) oraz (2) **ciągłości** ≥150 ms (3 okna). Wybiera
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
  **Eksport/import schowka:** „Eksport → schowek" zrzuca listę jako wiersze
  `<ścieżka>;<ID>` (`QApplication.clipboard().setText`); „Import ze schowka" parsuje to samo
  (`rpartition(';')` — ID zawsze po OSTATNIM średniku, ścieżka Windows bezpieczna). Istniejąca
  ścieżka → aktualizacja ID (`BatchRowWidget.set_session_id` przez spinbox), nowa → `_add_row`.
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
