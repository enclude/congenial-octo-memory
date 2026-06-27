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
- `api.py` — `fetch_session(id)` + `session_from_payload(payload)`. Oś czasu czytana z
  `data.opis`; metadane z `nazwa_toru`, `uczestnik`, `czasy.*`, `hit_factor`.
- `i18n.py` — `Translator` z fallbackiem (wybrany język → EN → `[klucz]`). Etykiety dla
  nakładki i GUI w jednym miejscu (`_STRINGS`).
- `audio_sync.py` — `detect_onsets` / `detect_start` (RMS + próg adaptacyjny);
  `resolve_t0(anchor, mode, first_shot_time)` przelicza kotwicę na T0.
- `overlay.py` — render paneli PNG (Pillow): `render_shot_panel`, `render_summary_panel`,
  `render_start_banner`, `panel_origin`. Deterministyczny (umożliwia snapshoty).
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
  (t ≥ T0). `render.prepare_clock` wybiera ścieżkę: `_clock_drawtext_seg` (filtr `drawtext`,
  gładkie dziesiąte s, tani) gdy drawtext REALNIE koduje (`_drawtext_usable()` — test 1 klatki,
  cache), inaczej fallback `_clock_png_events` (panele PNG co 1 s — działa na każdej binarce;
  imageio-ffmpeg NIE ma drawtext). Pozycja nad najwyższym panelem strzału (`_clock_xy`/
  `_max_panel_h`), zgodnie z rogiem kotwicy; `_Event.xy` wymusza tę pozycję. Podgląd rysuje
  zegar przez `overlay.render_clock_panel`. WAŻNE (drawtext): dwukropki w `%{eif\:…\:d}` MUSZĄ
  być eskejpowane `\:`, a wartości opcji (text/x/y/enable) w apostrofach; eif daje tylko int,
  więc sekundy i dziesiąte liczone osobno przez `trunc`.
- **Auto-detekcja T0 + przycięcie:** `gui.StartDetectWorker` (QThread) odpala
  `detect_dji_start` w tle. Po wczytaniu pliku (`_on_wave_done` → `_auto_detect_t0("import")`):
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
- **Format wyjściowy:** `format_combo` w GUI → `render.render_video` (MP4/H.264) /
  `render_webm` (VP9) / `render_gif`. CLI renderuje tylko MP4.
- **Presety wyglądu:** zapisz/wczytaj JSON z pliku; auto-zapis ostatnich ustawień i
  katalogu do `AppData` (przywracane przy starcie).
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

## Uwagi / pułapki

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
