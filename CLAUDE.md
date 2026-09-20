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
  `compute_t0`, `compute_trim` (+`DEFAULT_AUTO_WINDOW`, `PipelineError`); ID z audio:
  `detect_id_tone` (ramka ID-tone v3 → `audio_sync.IdToneCode`), `resolve_id_tone`
  (kod tymczasowy → ID wpisu w bazie, `IdToneResult`), `detect_id` (jedno wejście dla
  GUI/WWW/wsadu) oraz `_match_candidates` (wspólna ocena kandydatów po czasie i odcisku
  strzałów — dla `find_session_by_time` i dla kodów tymczasowych). Helpery w `cli.py`
  są cienkimi wrapperami (zachowują printy i `SystemExit`); `tests/test_cli.py` pilnuje
  równoważności. NOWĄ logikę przepływu dodawaj TU, nie w cli/gui/web.
- `preview.py` — domenowa kompozycja podglądu klatki (Pillow): `compose_preview(frame,
  session, t, t0, style, duration, video_h)` = panel aktywny dla t + zegar (zamrożony na
  ostatnim strzale, jak w renderze); `scaled_style` skaluje offsety do rozdzielczości
  podglądu (WYSIWYG). Odtwarza `gui._on_scrubber_frame_ready` — gui.py celowo NIE został
  przepięty (świadoma duplikacja, zero ryzyka regresji .exe).
- `api.py` — `fetch_session(id)` + `session_from_payload(payload)`;
  `find_sessions(from, to)` i `find_sessions_by_temp_id(temp_id)`
  (`api.php?temp_id=<5 cyfr>`, lista `SessionCandidate` — kod tymczasowy NIE jest
  unikalny globalnie; pole `SessionCandidate.temp_id`). Oś czasu czytana z
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

## Praca z subagentami (obowiązkowe)

Każde zadanie, które dotyka więcej niż jednego pliku albo wymaga przeszukania repozytorium, prowadź przez subagentów (narzędzie Task/Agent), zamiast czytać wszystko w głównym kontekście:
- **Rozpoznanie** („gdzie jest X", „które pliki dotyczą Y") → subagent typu Explore; główny kontekst dostaje wniosek, nie zrzuty plików.
- **Zmiany w kilku niezależnych obszarach** (albo w kilku repozytoriach naraz: timer / kalkulator / Piro Overlay) → po jednym subagencie na obszar, uruchamiane równolegle w jednej wiadomości.
- **Wspólne protokoły** (np. ID-tone) → najpierw spisz specyfikację i przekaż ją KAŻDEMU subagentowi dosłownie; inaczej repozytoria rozjadą się na stałych.
- Subagent NIE commituje i NIE aktualizuje dokumentacji — commit, push i dokumentację robi sesja główna po zebraniu raportów.

Wyjątek: pojedyncza, znana zmiana w jednym pliku — rób ją bez subagenta.

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

**PUŁAPKA — „No module named 'piro_overlay.gui'" w runtime .exe (v0.38.1):** PyInstaller
przy analizie POMIJA PO CICHU moduł, którego nie umie skompilować („invalid module" tylko
w `build/…/warn-*.txt`) — exe buduje się „bez błędu" i pada dopiero przy starcie. Realny
przypadek: ASCII `"` zamiast typograficznego `”` w tooltipie gui.py = SyntaxError; testy
tego nie łapały, bo środowisko testowe (WSL) nie ma PySide6 i nic nie importuje gui.py.
Strażnik: `tests/test_syntax.py` kompiluje (`py_compile`) każdy moduł pakietu + `app.py`
bez importowania — łapie błąd składni niezależnie od zależności. Spec od tej wersji jest
też odporny na PEP 660: `pathex` bezwzględny (`SPECPATH/src`), `sys.path.insert(src)` +
`hiddenimports=collect_submodules("piro_overlay")` — pakiet zbierany JAWNIE ze źródeł,
bez polegania na editable install w venv (nowe pip robią editable przez finder
`__editable___…`, którego analiza PyInstallera nie śledzi).

## Funkcje wprowadzone po MVP

- **Kody tymczasowe / ID-tone v3 (v0.65.0):** na zawodach bywa BRAK INTERNETU — timer nie
  może wtedy zapisać sesji w kalkulatorze, więc nie ma jeszcze ID wpisu do zagrania
  kamerze. Rozwiązanie: timer nadaje sesji **kod tymczasowy** lokalnie (bez sieci) i gra go
  do mikrofonu kamery od razu po sesji; wpisy trafiają do bazy później (hurtem), a overlay
  odnajduje je po kodzie. Ramka ID-tone dostała więc slot KANAŁU:
  **kanał 0 = wartość jest ID wpisu w bazie kalkulatora (zachowanie v2),
  kanał 1–9 = numer stanowiska, a wartość to 4-cyfrowy kod tymczasowy** (kanoniczna
  postać w bazie/API to 5-cyfrowy string `temp_id`, np. `"30147"`; dla człowieka `3-0147`).
  Szczegóły ramki i wymóg zgodności stałych w trzech repozytoriach — w sekcji
  „Dekodowanie ID sesji z sygnału tonowego" niżej.
  Ścieżka danych: `audio_sync.decode_id_tone` → `IdToneCode` → `pipeline.detect_id_tone`
  → `pipeline.resolve_id_tone` → (kanał 1–9) `api.find_sessions_by_temp_id(temp_id)`
  = `GET api.php?temp_id=<5 cyfr>` → `IdToneResult(code, session_id, info, match)`;
  `pipeline.detect_id` łączy oba kroki i jest jednym wejściem dla GUI, wsadu i WWW.
  **Rozstrzyganie i jego granica:** kanał 0 nie odpytuje bazy w ogóle; dla kodu
  tymczasowego jeden kandydat = trafienie, a **kilku kandydatów z tym samym kodem**
  (licznik kodów w przeglądarce timera zawija się po 9999) idzie przez istniejące
  dopasowanie po czasie nagrania i odcisku strzałów (`pipeline._match_candidates`,
  wspólne z `find_session_by_time`). **Gdy to nie rozstrzyga — `session_id` jest None
  i powód ląduje w `IdToneResult.info`; ZGADYWANIE jest zakazane**, bo nakładka
  pokazałaby cudzą sesję (ta sama zasada, co odrzucanie odczytu niezgodnego z checksumą).
  Tak samo traktowane są: brak wpisu w bazie („wyślij sesje z timera"), błąd API
  i stary kalkulator bez obsługi `temp_id` (`api.ApiUnsupported`).
  GUI (`gui.py` + `i18n.py`): po wykryciu kodu tymczasowego leci drugie zadanie
  (`_run_op` → `busy_temp_id_lookup` / `status_temp_id_lookup`, slot wolny bo `_end_op`
  idzie przed callbackiem), a `_on_temp_id_resolved` albo wpisuje znalezione ID
  (`_apply_detected_id`, wspólne z kanałem 0), albo — bez rozstrzygnięcia — zachowuje się
  jak przy nieczytelnym sygnale. Wsad: `BatchIdDetectWorker` sam dolicza T0 z bzyczka,
  żeby zawęzić rozstrzyganie, a wiersz dostaje NOWE źródło ID `"temp"` (własna ikona
  i podpowiedź „ID z KODU TYMCZASOWEGO w audio (sesja offline) — sprawdź", etykieta
  `3-0147 → #1234`) obok `"tone"`/`"time"`/ręcznego.
  WWW: `/detect-id` zwraca `{id, temp_id, code, info}` (patrz sekcja o wersji webowej).
  Testy: `tests/test_id_tone.py` (ramka v3), `tests/test_pipeline.py`
  (`resolve_id_tone`: kanał 0 bez zapytania, jeden kandydat, brak wpisu, błąd API,
  wieloznaczność), `tests/test_session_match.py` (`find_sessions_by_temp_id`: parsowanie
  listy, stary serwer → `ApiUnsupported`, błąd → `ApiError`).
- **Wsad: zmienne w prefiksie/sufiksie nazwy (v0.64.0):** `pipeline.expand_name_template(
  template, session, session_id)` podstawia `{id}`, `{uczestnik}`, `{tor}`, `{strzaly}`,
  `{czas}` (czas bazowy, kropka → `_`), `{hf}`; lista w `NAME_TEMPLATE_VARS`. Nieznane `{x}`
  zostają dosłownie (literówka nie wywala wsadu). Wartości przez
  `pipeline.sanitize_filename_part` (PRZENIESIONE z gui.py; w gui zostaje alias
  `_sanitize_filename_part`) — diakrytyki → ASCII, białe znaki → `_`, znaki zabronione
  usunięte. Zastąpiło checkbox „Dodaj informacje o uczestniku” (= sufiks
  `_PiRoOverlay_{id}_{uczestnik}`); pola pamiętane w `QSettings("ui/batch/prefix"/"suffix")`,
  pod nimi etykieta `muted` z listą zmiennych, tooltip z opisem. Testy w `tests/test_pipeline.py`.

- **Wsad: metadane z API, pochodzenie ID i „Wykryj ponownie” (v0.62.0)** — trzy prośby
  z użycia na zawodach 2026-09-20 (okno wsadu jest szerokie, wiersz miał puste miejsce):
  (1) wiersz `READY` pokazuje `nazwa_toru · uczestnik · N strz. · T0=… · przyc. …` z
  `row.prep["session"]` (BatchPrepWorker zawsze niósł `Session`, nikt go nie wyświetlał);
  pełny tekst w tooltipie, bo przy węższym oknie etykieta się ucina. (2) `BatchRow.id_source`
  = `"tone"` / `"time"` / `""` (ręcznie) — `BatchIdDetectWorker.done` niesie 4. argument
  `source`; ikona `QLabel` `_src_icon` między spinboxem ID a info (`detect.svg` = sygnał
  audio, `clock.svg` = dopasowanie po czasie, puste = ręcznie; fallback glify 🔊/⏱),
  przemalowywana w `refresh_icon`. PUŁAPKA: `_on_id_detected` ustawia `id_source` PO
  `set_session_id`, bo `_on_id_changed` zeruje je (każda zmiana spinboxa = ręczne ID).
  (3) `_redetect_btn` (`loop.svg`, „↻”) → `_redetect_row`: reset wiersza do stanu jak po
  dodaniu (`prep=None`, `error=""`, `id_source=""`, `session_id=0`, `NEEDS_ID`) i
  `_start_detect(row)` (wyciągnięte z `_detect_ids`, honoruje checkbox dopasowania po
  czasie). Spinbox zerowany przez NOWE `set_session_id_silent` (bez `id_changed`) —
  zwykłe `set_session_id` przy `DETECTING` odbiłoby się od guarda `_BATCH_BUSY`.
  Aktywny zawsze poza `_BATCH_BUSY` (także dla READY — „przygotuj od zera”).

- **Wsad: „Pobierz” per wiersz (v0.61.0):** po RĘCZNYM wpisaniu ID wiersz pokazywał tylko
  „gotowe do przygotowania” i trzeba było klikać „Przygotuj wszystkie” (feedback z użycia).
  `BatchRowWidget._prep_btn` — `QToolButton` icon-only (`download.svg`, fallback „⤓”) przed
  „▶”/„✕”, sygnał `prepare_requested(row_id)` → `BatchDialog._prepare_row`: aktywny TYLKO dla
  `PENDING`/`FAILED` z ID > 0 (FAILED = ponowienie jednego pliku bez całej partii), guard na
  żywy worker w `_workers`. Wspólny start jednego wiersza wyciągnięty do `_start_prepare(row)`
  (używa go też `_prepare_all`); `_auto_total` ustawiany na liczbę trwających przygotowań,
  żeby `_stage_message` („Przygotowuję: 1/1”) nie kłamał. Tekst stanu PENDING:
  „gotowe — kliknij ⤓ albo „Przygotuj wszystkie””. PUŁAPKA powtórzona z v0.38.1: ASCII `"`
  w tym tekście = SyntaxError w gui.py, złapany przez `tests/test_syntax.py` przed zrzutem.

- **Dopasowanie nagrania do sesji PO CZASIE (v0.60.0)** — opcja awaryjna, gdy sygnał ID
  z audio jest nieczytelny (brak tonu, telefon za daleko, wiatr): zamiast ręcznie szukać
  wpisu w `wyniki.php`, aplikacja pyta API o wpisy z okna czasu nagrania. Moduł domenowy
  `session_match.py` (bez Qt) + `pipeline.find_session_by_time(video, *, t0, info, hint_id)`
  jako JEDYNE wejście dla GUI/CLI/wsadu (zwraca `MatchResult(recording, matches, picked)`).
  - **Czas po stronie nagrania** (`recording_start`, kolejność): nazwa pliku DJI
    `DJI_YYYYMMDDHHMMSS_NNNN_D` = czas LOKALNY kamery (`time_from_filename`, jest też ogólny
    wzorzec `YYYYMMDD[_]HHMMSS`; **Pixel `PXL_YYYYMMDD_HHMMSSmmm` = UTC**, v0.63.1 — zmierzone na
    `PXL_20260920_101908466.mp4`: nazwa 10:19:08Z, a `creation_time` 10:20:09Z to KONIEC nagrania
    52 s + finalizacja, więc bez nazwy start był o ~60 s za późno) → tag kontenera `creation_time` (NOWE pole
    `ffmpeg.VideoInfo.creation_time`, ffprobe `format_tags` albo regex `_CREATION_RE` na
    stderr; DJI zapisuje UTC z „Z", naiwny czas traktujemy jako UTC) → mtime pliku (to KONIEC
    nagrania → minus długość). Pomiar `DJI_20260707180623_0051_D.MP4`: nazwa 18:06:23 CEST,
    `creation_time` 16:06:24Z, mtime 18:06:59 przy 33 s — trzy źródła zgodne co do sekundy.
  - **Czas po stronie bazy — DWA komplementarne pola** (`api.SessionCandidate`):
    `data_zapisu` = UTC (SQLite `CURRENT_TIMESTAMP`; sprawdzone: ID 326 zapisane
    17:52:12 UTC = 19:52:12 CEST, plik `_0035` startuje 19:51:06 + T0 32 s + 30,5 s sesji)
    — zawsze obecne, ale to chwila ZAPISU, więc przy hurtowej wysyłce z cache timera pod
    koniec dnia nie ma nic wspólnego ze strzelaniem; `timer_sess_id` = start sesji NA
    TIMERZE (unixtime w czasie LOKALNYM urządzenia — `timer_start` skleja go z lokalną strefą,
    NIE konwertuje z UTC) — dokładny co do sekund, tylko dla wpisów z timera.
  - **Ocena (`match_sessions`)**: znany T0 → oczekiwany start sesji = start nagrania + T0;
    bez T0 sesja może być gdziekolwiek w nagraniu (tolerancje + długość nagrania).
    Kandydat z timera: Δ = start na timerze − oczekiwany start, okno `±TIMER_TOL_S` (150 s — obejmuje zmierzony dryf 110 s, a 327 przy +165 s w przypadku `_0035` zostaje poza oknem).
    **Dryf zegara timera (v0.62.1, dane z zawodów 2026-09-20):** 2026-08-12 timer zgadzał się
    z kamerą co do 2 s, 2026-09-20 szedł ~110 s do przodu (sesje 350–360 mają `data_zapisu`
    PRZED startem na timerze — fizycznie niemożliwe bez dryfu), a po południu znów ~0 (zegar
    zsynchronizowany po reconnect). Skutek: bliższy |Δ| wskazywał SĄSIEDNIĄ sesję (nagranie
    0003: 343 przy Δ+49, właściwe 344 przy Δ+111). Dlatego `pick` przy DWU kandydatach z
    timera w oknie ZAWSZE zwraca None (dialog z nazwiskami / wsad „podaj ręcznie”), a margines
    `PICK_MARGIN_S` obowiązuje tylko dla `data_zapisu` (zegar serwera). Pomysł na później:
    estymacja offsetu zegara z całej partii (rzędy z ID z tonu = kalibracja) — NIE zrobione.
    Kandydat tylko z `data_zapisu`: Δ = zapis − (oczekiwany start + `czas_bazowy`), okno
    `[SAVE_MIN_S=-15, SAVE_MAX_S=300]` — zapis pada PO końcu sesji. Sortowanie: w oknie →
    timer przed saved → mniejsze |Δ|. **`pick` (jednoznaczność):** jedno trafienie → ono;
    kilka → jeden kandydat z timera rozstrzyga nad saved, dwa z timera = None (dryf, wyżej);
    same saved: najlepszy musi wyprzedzać następnego o `PICK_MARGIN_S` (60 s), inaczej `None`
    (GUI: dialog wyboru, CLI: lista `--id`).
  - **Odcisk strzałów (v0.63.0)** — rozstrzyga między kilkoma sesjami w oknie czasu
    (realny problem: nagranie 0003 z 2026-09-20 → 343 zamiast 344, bo timer był
    synchronizowany W TRAKCIE zawodów i dryf zmieniał się z +110 s na 0). Zasada:
    czas jest kryterium GŁÓWNYM (wybiera kandydatów), odcisk tylko wybiera spośród nich.
    `audio_sync.shot_alignment_score(samples, sr, t0, shot_times)` = średnia geometryczna
    (pik energii ±60 ms przy T0+strzał) / (mediana energii w oknie sesji); ~1 = strzały w tle
    (zła oś), >>1 = w pikach. Celowo NIE progujemy onsetów — detektor onsetów przy cichych
    strzałach widział 2 z 8 (0003), a obwiednia i tak wskazała właściwą oś (3,5× vs 1,4×).
    `shot_alignment_scores(video, t0, {id: shots})` ładuje audio RAZ; pipeline liczy je na
    `audio_source()` (LRF) tylko gdy `t0` znany i ≥2 trafienia w oknie z czytelnym `opis`
    (`SessionCandidate.opis` — tryb listy i `?id=` go zwracają; `session_match.candidate_shots`
    parsuje z prefiksami). `apply_shot_scores` dopisuje `Match.shot_score` i sortuje trafienia po
    nim; `pick`: najlepszy ≥ `SHOT_SCORE_RATIO`=1,3× drugiego → wygrywa niezależnie od zegarów;
    policzone bez zwycięzcy → None (duplikat wpisu: 358 = 363 identyczna oś, 7,6× oba).
    **Walidacja na 25 nagraniach z Krotoszyna (folder `raw`):** 23 jednoznaczne, spójne ze
    stałym dryfem +110 s rano i 0 po południu; właściwa sesja wygrywała ≥1,4×; 1 duplikat →
    dialog; 1 plik bez bzyczka. Wsad (`BatchIdDetectWorker._match_by_time`) liczy teraz T0
    (`detect_start_signal`) PRZED dopasowaniem — bez T0 odcisku nie ma od czego mierzyć.
    Dialog GUI i lista CLI pokazują „odcisk N×”. Bez `opis` w API (stary serwer, skan po ID
    zwraca `?id=` z `opis`, więc też działa). Skąd margines: realne dane — kolejny strzelec zapisuje wynik 40 s – 3 min po
    poprzednim (ID 327 saved +165 s po 326), więc samo „w oknie 300 s" NIE rozstrzyga,
    a |Δ| 3 s vs 165 s już tak. Zweryfikowane na żywym API dla `_0035`: picked = 326.
  - **API (repo `www.piro-kalkulator.pifpaf.fun`, `api.php`)**: NOWY tryb listy
    `?from=<unix UTC>&to=<unix UTC>&tz_offset=<s>` → `{ok, data:[{id, nazwa_toru, uczestnik,
    opis, data_zapisu, liczba_strzalow, czas_bazowy, timer_sn, timer_sess_id}]}`; filtr SQL
    `data_zapisu ∈ [from,to] OR timer_sess_id ∈ [from+tz_offset, to+tz_offset]` (okno ≤ 7 dni,
    ≤ 200 wierszy, usunięte pomijane); `?id=` zwraca dodatkowo `timer_sn`/`timer_sess_id`.
    Klient: `api.find_sessions(from_utc, to_utc, tz_offset_s=...)`; okno buduje
    `session_match.query_window` (−120 s … +długość+420 s). **Stary serwer** (przed `git pull`
    w katalogu kontenera) odpowiada 400 „Brak … parametru "id"" → `api.ApiUnsupported` →
    `api.find_sessions_by_scan(from, to, fetch=fetch_candidate, hint_id=...)`: wyszukiwanie
    BINARNE po ID (AUTOINCREMENT, `data_zapisu` rośnie z ID, usunięte ID nie wracają):
    podwajanie od `hint_id` do końca bazy (`_SCAN_GAP`=8 sąsiadów mostkuje dziury po
    usuniętych), binarnie w `[0, hi)` (PUŁAPKA: dolna granica NIE może zostać z podwajania —
    podpowiedź bywa wyżej niż okno), potem w dół po oknie; limit `_SCAN_MAX_REQUESTS`=150.
    Pomiar na żywym API: 26–33 żądania, ~1,5 s. Skan widzi TYLKO `data_zapisu` (bez wpisów
    wysłanych hurtowo) — docelowo tryb listy.
  - **CLI:** `--match-time` (bez `--id`/`--timeline`): T0 liczony PRZED sesją, więc wymaga
    `--auto` albo `--t0` (kotwica FIRST_SHOT zależy od osi); niejednoznaczność → `SystemExit`
    z listą `--id N: tor / uczestnik (podstawa, Δ)`. Testy: `tests/test_session_match.py`
    (w tym realny przypadek 326/327 i hurtowa wysyłka z `timer_sess_id`), `test_cli.py`,
    `test_ffmpeg.py` (`creation_time`). Web: NIE zrobione (świadomie — `/detect-id` zostaje
    bez fallbacku; upload zna nazwę pliku z `X-Filename`, więc można dodać później).
  - **GUI, okno główne:** `match_time_btn` — `QToolButton` ICON-ONLY (nowa ikona
    `assets/icons/clock.svg`, fallback „⏱", przemalowywana w `_refresh_icons`) w pasku
    `idbtns` obok „Pobierz i przytnij"/„Wykryj ID z audio", w `_op_buttons`; checkbox
    `match_time_chk` „Brak ID z audio → dopasuj po czasie" (`QSettings("ui/match_by_time")`,
    domyślnie ON) w `add_widget_row` pod paskiem. `_on_id_tone_detected` przy `None` +
    checkbox → `_match_session_by_time()` (zwraca False, gdy slot `_run_op` zajęty → wtedy
    stary `msg_no_id_tone`). `_match_session_by_time` → `_run_op(partial(pipeline.
    find_session_by_time, video, t0=t0_spin>0|None, info=self._video_info, hint_id=id_spin
    |None), button=match_time_btn, status_text=…)` — BEZ `busy_text` (na icon-only tekst
    wlazłby obok ikony). NOWE pole `MainWindow._video_info` (cały `VideoInfo` z `probe`
    w `_set_video`; dotąd trzymano tylko `_video_size`). `_on_time_match`: `picked` →
    `_apply_time_match` (id_spin → `_set_source("id")` → `msg_time_matched` →
    `_fetch_id_and_trim()`, jak po udanym ID z audio); `ambiguous` → `_pick_time_match`
    (modalny `QDialog` + `QListWidget`, wiersz `time_match_row`, dwuklik = OK, `Match`
    w `Qt.UserRole`, anulowanie → `msg_time_match_cancelled`); brak trafień →
    `msg_time_match_none` (start nagrania + źródło); brak czasu → `msg_time_match_no_rec`.
    `_build_cli_command` celowo bez `--match-time`. **PUŁAPKA szerokości inspektora:**
    baseline `minimumSizeHint` 401 px przy viewport 412 — trzeci przycisk Z TEKSTEM w
    `idbtns` dawał 443, przycisk w kolumnie kontrolek wiersza „ID" 513, długa etykieta
    checkboxa w `add_row` 533 (poziomy pasek); icon-only + krótka etykieta w
    `add_widget_row` wracają do 401.
  - **GUI, wsad:** checkbox `_match_time_chk` „bez ID z audio: dopasuj po czasie"
    (`batch_match_time`, `QSettings("ui/batch/match_by_time")`, domyślnie ON) w wierszu
    „Automat z folderu…". `BatchIdDetectWorker(row_id, video_path, match_time)` — `done`
    to teraz `Signal(str, object, str)` = `(row_id, id|None, info)`; gdy ton da None,
    `_match_by_time()` woła `pipeline.find_session_by_time(video)` BEZ T0 (wsad go jeszcze
    nie zna → okno = całe nagranie) i przyjmuje TYLKO `result.picked`. `info` ląduje
    w `row.error` jako podpowiedź („ID z dopasowania po czasie: tor / uczestnik (Δ) —
    sprawdź", „kilka sesji pasuje… — podaj ręcznie", błąd sieci) — `_on_id_detected`
    ustawia je PO `set_session_id` (bo `_on_id_changed` zeruje `error`); nowa gałąź
    `BatchRowWidget.update_row` `PENDING and row.error` pokazuje ją w roli `warning`
    (ręczna zmiana ID czyści). Auto-fetch nadal NIE ma — użytkownik weryfikuje przed
    „Przygotuj wszystkie". Bez testu Qt (WSL bez PySide6); zrzuty offscreen z `.venv-win`
    obejrzane, nie w repo.

- **Nadpisanie nazwy toru / uczestnika z API (v0.58.0):** czysta funkcja
  `pipeline.apply_meta_override(session, nazwa_toru, uczestnik)` — puste/białe znaki =
  zostaw wartość z sesji (z API), niepuste = `replace(...)` po `strip()`. ŚWIADOMIE bez
  trybu „wyczyść” (ukrycie metadanych to sprawa stylu nakładki, nie danych).
  `pipeline.build_session(timeline, id, nazwa_toru=None, uczestnik=None)` nakłada ją na
  OBA źródła — przy tekście to jedyna droga, żeby sesja bez API miała metadane. CLI:
  `--track-name`/`--participant` (`tests/test_cli.py` ma je w `_args`). GUI: pola „Tor”/
  „Uczestnik” (`meta_track_edit`/`meta_participant_edit`, `QLineEdit` z przyciskiem
  czyszczenia) w sekcji „Wejście” pod przyciskami ID; placeholder = wartość z API
  (`_set_meta_placeholders`), więc widać CO się nadpisuje. Model stanu: `_api_session`
  (surowa odpowiedź API, ustawiana w `_on_session_fetched`) i `self.session` = ta kopia
  PO `_with_meta_override` — dzięki temu WSZYSTKIE istniejące odczyty `self.session`
  (podgląd, player, scrubber, markery osi, kolejka, `render._diag_metadata_args`)
  dostają nadpisane wartości bez zmian u siebie; `textChanged` → `_on_meta_override_changed` przelicza `self.session`
  z `_api_session` i woła `_update_preview`. `_build_session`: gałąź ID owija
  `api.fetch_session`, gałąź tekstowa bez `self.session` owija `Session(shots)`;
  z `self.session` zostaje `replace(shots=…)` (nadpisanie już w środku). Pamięć
  per-plik: klucze `meta_track`/`meta_participant` (surowy tekst pola, bez strip);
  `_apply_file_settings` ustawia je PRZED cichym `_fetch_id`, więc wynik pobrania od
  razu je nakłada. `_build_cli_command` dokłada obie flagi (nie przy „bez nakładki”).
  Test GUI (PySide6, `.venv-win`): `test_meta_override_applies_to_session_and_settings`.
  NIE zrobione (świadomie): wsad (`BatchDialog` — per-plik pole to inny UI, a wsad
  bierze metadane wprost z API), web (`/session` nie ma jeszcze parametrów nadpisania).

- **„Zapisz klatkę" — PNG z nakładką w pełnej rozdzielczości (v0.57.0):** przycisk
  icon-only (`camera`, nowa ikona `assets/icons/camera.svg`) w pasku nad podglądem,
  obok „Dopasuj"/„Zoom Od–Do", skrót **Ctrl+S** (skrót okna z modyfikatorem — działa
  nawet gdy fokus jest w polu tekstowym, w przeciwieństwie do gołego „E"). Domenowa
  funkcja `preview.render_still(video_path, t, session, t0, style, duration, *,
  height=None)` (bez Qt): `ffmpeg.extract_frame(..., scale_height=height)` (bez
  `height` = pełna rozdzielczość źródła — `extract_frame` już obsługiwał
  `scale_height=None`, zero zmian tam potrzebnych) + `compose_preview` z `video_h`
  klatki (skalowanie offsetów 1:1, bo klatka i offsety są w tej samej rozdzielczości).
  GUI (`gui._on_save_frame`): dialog zapisu (`QFileDialog.getSaveFileName`, filtr PNG,
  domyślna nazwa `<stem>_<czas>s.png` w `config.load_last_dir("output")` — ten sam
  klucz co `_choose_output`) PRZED pracą w tle — użytkownik nie czeka na ekstrakcję
  klatki z 4K/HEVC (sekundy), żeby dopiero wybrać plik. Ekstrakcja+kompozycja+zapis
  idzie przez `_run_op(fn, button=save_frame_btn, ...)` jak inne długie operacje;
  `save_frame_btn` jest w `_op_buttons` (blokowany na czas innej operacji) i wyłączony
  bez wideo (`_set_render_enabled` — jak `render_btn`, ale NIEZALEŻNIE od stanu
  renderu: czytanie oryginału FFmpeg-iem obok trwającego renderu jest bezpieczne).
  **Czas klatki** (`gui._current_still_time`) = to samo źródło co pasek „▶ czas" nad
  podglądem: pozycja playera (`player.position()`, gdy aktywny) → kursor podglądu
  (`waveform.preview_t`) → playhead → T0+1 s (świeżo wczytany plik, nic jeszcze nie
  wskazano). Sesja jak w `_on_scrubber_frame_ready`/`_update_preview` (`self.session
  or self._safe_session()` — ta sama zasada „podgląd i render muszą używać tej samej
  sesji", patrz wpis w „Uwagi/pułapki"); `session=None` → czysta klatka (tryb „bez
  nakładki"). Tryb `--screenshot --video X --save-frame PATH`: ta sama ścieżka
  domenowa, ale SYNCHRONICZNIE i bez dialogu (tryb zrzutu nie ma pętli zdarzeń dla
  `_run_op`/QThread) — użyty do weryfikacji na realnym nagraniu `_0035`
  (ID 326, T0+1,5 s): 3840×2880, nakładka (panel metadanych) w tej samej pozycji
  co w podglądzie na żywo. i18n: `save_frame`, `tip_save_frame`, `busy_save_frame`,
  `msg_frame_saved`, `msg_save_frame_failed`.

- **„Automat z folderu…" we wsadzie (v0.56.0):** jedno kliknięcie od karty pamięci do
  przeglądu — `BatchDialog._auto_from_folder` pyta o katalog
  (`QFileDialog.getExistingDirectory`, pamięć katalogu pod NOWYM kluczem
  `config.load/save_last_dir("batch_dir")`, fallback na klucz `"video"`), skanuje go
  `pipeline.scan_video_dir(path, recursive)` (domena, BEZ Qt: rozszerzenia
  `VIDEO_SUFFIXES` = .mp4/.mov/.mkv/.avi/.m4v bez względu na wielkość liter, pomija
  proxy `.LRF`, miniatury `.THM`, pliki ukryte i AppleDouble `._*`, sortuje katalog→nazwa;
  testy w `tests/test_pipeline.py`), dokłada wiersze (duplikaty ścieżek pomijane jak przy
  imporcie ze schowka) i uruchamia łańcuch: detekcja ID z audio → przygotowanie (API+T0).
  Do kolejki NIC nie trafia automatycznie — błędnie odczytane ID pobrałoby cudzą sesję,
  więc „Wyślij gotowe do kolejki" zostaje ręczne (świadomie).
  - **Maszyna etapów:** `_auto_queue` (`["detect", "prep"]`) + `_auto_stage` (etap
    trwający) + `_auto_total` (licznik do paska stanu). `_auto_advance` zdejmuje etapy
    z kolejki i POMIJA te bez pracy (brak wierszy NEEDS_ID → od razu przygotowanie),
    a na końcu `_auto_finish` wypisuje podsumowanie `batch_auto_summary`
    („Gotowe: N, bez ID: M, błędy: K") — PO `_refresh()`, bo ono nadpisuje pasek stanu
    napisem „Gotowy". Łańcuch gasi `_auto_cancel()` z `closeEvent` i „Wyczyść wszystko";
    pojedynczy błąd wiersza (API/brak bzyczka) NIE przerywa partii — wiersz zostaje
    FAILED i ląduje w liczniku podsumowania (inaczej jeden zły plik zabierałby
    przygotowanie pozostałych 18).
  - **PUŁAPKA QThread:** łańcucha NIE wolno popychać z sygnału `done` workera —
    `self._workers` jest keyowany po `row.id`, więc wstawienie tam `BatchPrepWorker`
    dla tego samego wiersza zwolniłoby referencję do JESZCZE ŻYJĄCEGO
    `BatchIdDetectWorker` (twardy crash, jak w kolejce renderów przed v0.21.0).
    Stąd wspólny `_finish_worker(row_id)` podpięty do `finished` (zastąpił obie lambdy
    `self._workers.pop(...)`): robi `wait()` przed zwolnieniem referencji, a kolejny etap
    odpala dopiero gdy `_workers` jest PUSTE i przez `QTimer.singleShot(0, …)` — nowy
    QThread nie startuje z wnętrza `finished` poprzedniego.
  - **UI:** przycisk (i18n `batch_auto`) + checkbox „z podkatalogami"
    (`batch_auto_recursive`) w OSOBNYM wierszu nad paskiem akcji — pasek ma już 4
    przyciski, piąty (najdłuższa etykieta) nie mieściłby się w oknie 720–820 px.
    Jest to teraz JEDYNY primary w oknie wsadu, więc „Przygotuj wszystkie" zeszło na
    `secondary` (zasada „jeden primary na widoku"; „Automat" jest ścieżką domyślną,
    „Przygotuj wszystkie" — dokończeniem po ręcznym uzupełnieniu ID). Postęp: istniejący
    nieokreślony `QProgressBar` + `_stage_message()` w pasku stanu („Wykrywam ID: 3/12",
    „Przygotowuję: 5/12") — licznik ustawiają też `_detect_ids`/`_prepare_all`, więc
    działa również przy ręcznym kliknięciu. Wszystkie guardy `_BATCH_BUSY` i format
    eksportu/importu schowka bez zmian. Zrzut: `--screenshot --window batch`.

- **Wykrywanie przestarzałego T0 z pamięci pliku (v0.55.0):** problem realny —
  `file_settings.json` (per plik, patrz „Pamięć ustawień per-plik" niżej) trzyma T0 wyznaczony
  automatyczną detekcją, ale detektor (`audio_sync.detect_dji_start`) był od premiery kilka
  razy poprawiany (v0.42.0 guard obwiedni + scoring i dalsze); wpis sprzed poprawki może nieść
  ZŁY T0 bez żadnego sygnału dla użytkownika. Przypadek z pola:
  `DJI_20260812195106_0035_D.MP4` (ID 326) miał zapisane T0=26,2 s (metaliczny kling zrzutu
  zamka — dokładnie ten przypadek z wpisu „Wykrywanie sygnału startu" niżej), poprawna
  detekcja daje 32,05 s.
  - **Wersjonowanie detektora:** `audio_sync.START_DETECTOR_VERSION` (int, obecnie 2) —
    PODNOŚ o 1 przy KAŻDEJ zmianie zachowania `detect_dji_start`, która może zmienić wynik na
    realnych nagraniach (nowy próg, nowy guard, zmiana pasma/okna). 0 jest zarezerwowane jako
    „T0 ustawiony ręcznie" — nigdy nie oznaczaj nią wersji.
  - **Śledzenie pochodzenia T0 w GUI:** `MainWindow._t0_detector` (`int | None`) — 0 = ręczna
    zmiana (spinbox albo klik na osi), `None` = nieznana/przestarzała wersja (wpis sprzed tej
    funkcji), `>=1` = wersja detektora z chwili automatycznej detekcji. Jedyne miejsce, które
    ustawia T0 programowo i OD RAZU znaczy pochodzenie, to `_set_t0(value, detector=...)` —
    ustawia `_t0_detector` PRZED `t0_spin.setValue`, otoczonym flagą `_suppress_manual_t0`, bo
    `valueChanged` (`_on_t0_spin`) obsługuje TEN SAM sygnał co ręczna edycja użytkownika: bez
    flagi nie dałoby się ich odróżnić, a `_on_t0_spin` domyślnie zakłada „ręczna" (`detector=0`)
    gdy flaga nie jest ustawiona. Wszystkie wywołania `detect_dji_start` w GUI (auto po
    imporcie, „Wykryj sygnał startu", „Pobierz i przytnij") idą przez `_set_t0(...,
    detector=audio_sync.START_DETECTOR_VERSION)`; zwykłe „Wykryj kotwicę" (`detect_start`,
    inny — nie wersjonowany algorytm) i ręczna edycja spinboxa/osi zostają na `setValue` wprost
    → `detector=0`, bo nie są objęte tym mechanizmem.
  - **Zapis/odczyt:** `_collect_file_settings` dokłada klucz `"t0_detector": self._t0_detector`
    (może być `None` — JSON `null`, świadomie NIE mapowane na 0, żeby nie gubić „nieznane" na
    zawsze); `_apply_file_settings` woła `_set_t0(t0, detector=data.get("t0_detector"))` — brak
    klucza w starym wpisie daje `None` z samego `dict.get`, czyli naturalnie „nieznany/
    przestarzały" bez dodatkowego kodu.
  - **Porównanie — czyste funkcje w `pipeline.py`:** `t0_needs_recheck(saved_detector,
    current)` (False tylko dla `saved_detector == 0`; True dla `None` i dla wersji starszej
    niż bieżąca) i `t0_differs(a, b, tol=0.3)`. Testy w `tests/test_pipeline.py`.
  - **Przepływ w GUI:** `_on_wave_done` po zastosowaniu zapisanych ustawień woła
    `_maybe_recheck_t0(pending)` PRZED `_maybe_start_proxy()` (T0 ma pierwszeństwo, jak
    auto-detekcja) — gdy potrzebne, odpala `detect_dji_start` w tle przez `_run_op` (BEZ
    nadpisywania T0). Wynik: różnica > 0,3 s → `InlineMessage` w sekcji „Synchronizacja"
    (`_notify_sync_action`, kind `warning`, tekst i18n `msg_t0_stale` + przycisk akcji
    `msg_t0_stale_use` „Użyj X s") — klik (`_on_sync_msg_action` → `_apply_t0_recheck`)
    ustawia nowy T0 (`detector` = bieżąca wersja), przelicza przycięcie jak `_apply_auto_trim`
    i chowa komunikat. Różnica ≤ 0,3 s → cicho podnosi `_t0_detector` do bieżącej wersji (zapis
    dopiero przy najbliższym `_save_file_settings` — bez tego sprawdzalibyśmy ten sam plik przy
    KAŻDYM wczytaniu). PUŁAPKA odkryta przy weryfikacji: `_apply_file_settings` (source="id")
    kończy się CICHYM `_fetch_id(silent=True)`, który sam zajmuje slot `_run_op` — recheck
    odpalony zaraz potem dostawałby zawsze odmowę. Fix: gdy `_run_op` zwróci `False` (zajęte),
    `_maybe_recheck_t0` NIE zgłasza niczego, tylko planuje ponowną próbę
    (`QTimer.singleShot(_T0_RECHECK_RETRY_MS, ...)`, jak `_maybe_start_proxy`/`_proxy_poll`) —
    aż slot się zwolni albo plik się zmieni (`_retry_recheck_t0` porównuje `self.video_path`).
  - **`InlineMessage` z przyciskiem akcji (`ui_widgets.py`):** `show_message(text, kind,
    action_text=None)` + sygnał `actionClicked` — opcjonalny ghost-button obok tekstu,
    chowany gdy `action_text` nie podano (ZERO zmian w istniejących wywołaniach bez tego
    argumentu). `clear()` chowa też przycisk.
  - **Tryb `--screenshot`:** pole `MainWindow._t0_recheck_busy` (True od decyzji, że recheck
    jest potrzebny, do wyniku) dopisane do warunku oczekiwania w `--screenshot --video` (obok
    `_op_worker is None` i `_proxy_busy()`) — bez tego zrzut łapał moment W TRAKCIE detekcji
    (pasek postępu w połowie), zanim komunikat zdążył się pojawić. Zweryfikowane zrzutem na
    realnym pliku ze starym wpisem T0 (26,2 s → poprawne 32,05 s): `pictures` nie dodawano
    (zrzut roboczy w `.tmp-shots/`, nie w repo), ale przebieg potwierdzony ręcznie.
  - Zapisany T0 = 0 (nigdy nie wykryty) nie wywołuje sprawdzenia — nie ma z czym porównywać.

- **Edycja strzałów na osi czasu (v0.54.0):** `WaveformWidget` rysuje znaczniki strzałów
  sesji w czasie ABSOLUTNYM (`shots` = T0 + `shot.czas`, listę podaje `MainWindow.
  _sync_wave_shots` — oś sama nic nie liczy): cienka linia `text` z alfą 120 od 1/3
  wysokości w dół (pełnowysokie zostają kotwica/playhead/podgląd, onsety dalej `success`),
  zaznaczony = `accent` 3 px + pastylka „#N" w istniejącym mechanizmie `_tag_rect/_draw_tag`
  (dokładane NA KOŃCU listy etykiet, więc T0/Od/Do wygrywają miejsce, a zderzone numery
  wracają w tooltipie). Interakcja: klik = zaznacz (±`_SHOT_HIT_PX`=4 px), przeciągnięcie =
  zmiana czasu (podgląd w locie, `shotMoved(index, czas_absolutny)` dopiero na
  `mouseRelease`), Delete/Backspace = `shotDeleted(index)`, kursor `SizeHorCursor` nad
  markerem. **Priorytet trafień myszy: Ctrl (podgląd) → uchwyty Od/Do → marker strzału →
  kotwica** — uchwyty muszą zostać pierwsze (inaczej nie dałoby się chwycić granicy
  stojącej na strzale), a strzał wyprzedza kotwicę, bo klik w kotwicę wolno powtórzyć
  kilka pikseli obok, a w strzał nie. **Dlaczego ←/→ zmieniają znaczenie:** przy
  ZAZNACZONYM strzale przesuwają jego czas (0,05 s / Shift 1 s), a nie kotwicę —
  osobny modyfikator byłby trzecim wariantem tych samych klawiszy, a zaznaczenie
  i tak jest stanem chwilowym: Escape albo klik obok oddaje strzałki kotwicy. PUŁAPKA:
  Escape obsługuje `MainWindow._escape_edit_pos`, bo `QShortcut` okna ma pierwszeństwo
  przed `keyPressEvent` widżetu (ta sama sztuczka co `_home_key`/`_end_key`).
  Domena bez Qt: `parser.move_shot/delete_shot/renumber` (sortowanie po czasie, numeracja
  1..N, splity przeliczone z czasów, czas ujemny → `TimelineParseError`, zły indeks →
  `IndexError`) — testy round-trip w `tests/test_parser.py`. GUI zapisuje wynik przez
  `format_timeline` do `timeline_edit` (`_apply_edited_shots`), więc działa TYLKO przy
  źródle „Tekst" (przy „ID (API)" `msg_shot_text_only` i cofnięcie podglądu
  przeciągnięcia). Po przesunięciu strzał może zmienić numer (lista jest sortowana) —
  zaznaczenie idzie za NOWYM indeksem, po usunięciu gaśnie. `_sync_wave_shots` bierze
  sesję z `self.session` przy źródle ID (`_build_session` odpytałoby tam SIEĆ) i
  z `_safe_session()` przy tekście; wołane z `_update_preview` (czyli też przy każdej
  zmianie pola osi) i z `_on_t0_spin` (T0 przesuwa czasy absolutne). Tryb zrzutu:
  `--select-shot N` (numeracja jak na pastylce, od 1) — zrzut `.tmp-shots/shots-edit.png`.

- **Komponenty UI (v0.46.0):** trzecia iteracja odświeżenia (skill `python-desktop-ux`,
  krok III) — wymiana kontrolek na te z `ui_widgets.py`, ZERO zmian w formacie ustawień.
  (1) `ColorButton` USUNIĘTY → `ColorSwatchButton` (7 użyć: tło/tekst/akcent/obramowanie
  + 3 planszy START): próbka z szachownicą pod alfą, `#RRGGBB` i alfa w %, malowana z
  tokenów zamiast `setStyleSheet` — `grep -c setStyleSheet gui.py` == 0. W `_apply_style`
  ustawianie wartości idzie przez `set_rgba(rgba, emit=False)` (dawne `btn._rgba = …;
  btn._refresh()`); do `OverlayStyle` nadal trafiają krotki RGBA 0–255.
  (2) Radio „Tekst/ID (API)" → `SegmentedControl` + **warstwa zgodności** na `MainWindow`:
  `_source_is_id()` i `_set_source("id"/"text")` zastąpiły `rb_id.isChecked()`/`setChecked`
  we WSZYSTKICH miejscach (`_build_session`, `_detect_id_tone`, `_collect/_apply_file_settings`,
  `_build_cli_command`); klucz `"source"` w `file_settings.json` ma te same wartości
  (`source_seg.value()` zwraca dokładnie `"id"`/`"text"`).
  (3) `video_edit`/`out_edit` (QLineEdit + „…") → `PathField` (elipsa OD LEWEJ, tooltip z
  pełną ścieżką, drag&drop). PUŁAPKA: `PathField` ma WŁASNY `QFileDialog` bez pamięci
  katalogu — przycisk przeglądania jest `disconnect()`-owany i podpięty do istniejących
  `act_open`/`_choose_output` (`config.load/save_last_dir` bez zmian). Zapisy robimy
  `set_path(path, emit=False)`, bo `changed` jest podpięty do `_set_video` (upuszczenie
  pliku na pole = ta sama droga co wybór z dialogu, bez dublowania `dropEvent` okna).
  (4) Oś czasu: `role=mono`, krótszy placeholder i **walidacja inline** —
  `_refresh_timeline_summary()` parsuje pole przez `parse_timeline` i pokazuje pod nim
  „N strzałów, 2.81–26.14 s" (`role=muted`) albo powód błędu (`role=danger`) +
  `invalid="true"` na polu (nowe reguły QSS dla `QPlainTextEdit` w `ui_theme.py`); pusta
  etykieta jest chowana, żeby nie zostawiać dziury w formularzu.
  (5) **Skala nakładki tylko w WIDOKU jako procent**: `_pct_spin()` (QSpinBox 30–500,
  krok 5, sufiks „ %"), konwersja ×/÷100 wyłącznie w `_pct_value`/`_set_pct` wołanych z
  `current_style()`/`_apply_style` — `style.scale` i pliki ustawień nadal trzymają float.
  Skutek uboczny: skala ma teraz ziarno 1 % (0.855 z pliku wróci jako 0.86).
  (6) Pola czasu (`t0_spin`, `trim_*`, `tail_spin`, helper `_elastic`) wyrównane do prawej,
  `setKeyboardTracking(False)` (podgląd nie przelicza się na każdy wpisany znak),
  min. szerokość 92 px (sufiks „ s" mieści się też przy 150 %).
  REGRESJA Z ITERACJI II NAPRAWIONA: `id_spin` z `QSizePolicy.Ignored` + `AllNonFixedFieldsGrow`
  zgniatał się do paska ~4 px obok „Pobierz" — teraz `Fixed` 110 px, wyrównany do prawej i
  `setButtonSymbols(NoButtons)` (strzałki nie mają sensu dla ID sesji; typ `QSpinBox`
  i `id_spin.value()` zostają, bo czyta je wiele miejsc). Test bez Qt się nie da —
  `tests/test_gui_style_roundtrip.py` (`pytest.importorskip("PySide6")`) sprawdza
  `_apply_style(style)` → `current_style().to_dict() == style.to_dict()` oraz klucze źródła.
  Zrzuty: `pictures/ui-refresh/03-*.png`.

- **Layout i sekcje UI (v0.45.0):** `ui_widgets.py` (kopia `scripts/qt_widgets.py` ze skilla
  `python-desktop-ux`, import na `.ui_theme`, bez demo) + własna klasa `StatusDot` (kropka
  statusu malowana kolorem roli z `current_tokens`). W `gui.py` ZERO `setStyleSheet` poza
  `ColorButton._refresh` (pasek koloru bierze się z danych, nie ze zbioru ról — i tam kolory
  też idą już z tokenów); reszta to `role`/`kind` + `set_role`/`set_kind`/`repolish`.
  **Pasek akcji** (`QToolBar`, tekst bez ikon): Otwórz wideo (Ctrl+O), Pobierz z API (Ctrl+G),
  Wykryj sygnał startu (Ctrl+D), Auto-przycięcie (Ctrl+T), Dodaj do kolejki, Kolejka, Wsadowo,
  przełącznik motywu, po prawej „Renderuj" (Ctrl+R) jako `QToolButton` `kind=primary` —
  jedyny primary na widoku. Przyciski w formularzu wołają TE SAME `QAction`
  (`clicked → action.trigger()`), a `_set_render_enabled` trzyma stan Renderuj/Zatrzymaj
  w obu miejscach naraz. **Pasek stanu**: `progress` + `nvenc_label` przez
  `addPermanentWidget` (pasek zostaje widoczny z wartością 0 — ukrywanie przesuwałoby
  etykietę NVENC), `showMessage` → `status_message(bar, text, kind, ms)` (kolor stanu).
  **Sekcje**: `QGroupBox` → `FormSection` (nagłówek + chevron + `add_row/add_pair_row/
  add_widget_row`); przeładowany „Wygląd nakładki" rozbity na Wygląd / Kolory / Nakładka
  metadanych / Zegar / Plansza START (trzy ostatnie domyślnie zwinięte), stan zwinięcia w
  `QSettings` `ui/section/<klucz>` (ta sama przestrzeń co geometria, `config.py` nietknięte).
  `self.appearance_box` to teraz KONTENER wszystkich sekcji wyglądu — `setDisabled` w trybie
  „bez nakładki" działa jak dotąd. Zależności kontrolek przez `_sync_dependencies()`
  (WYŁĄCZANIE, nie ukrywanie) — wołane też na końcu `_apply_style`, bo tam sygnały są
  zablokowane. PUŁAPKI: (1) **kombosy pozycji mają teraz polskie etykiety i klucz w
  `userData`** — czytaj WYŁĄCZNIE `currentData()`; `currentText()` zwróciłby „Lewy dolny"
  i wysadził walidację `OverlayStyle` (dotyczy `pos_combo`, `meta_pos_combo`,
  `clock_pos_combo` w `current_style`, `_apply_style`, `_update_preview`); (2)
  `FormSection` ze skilla ma `ExpandingFieldsGrow`, które rozciąga TYLKO pola z polityką
  `Expanding` — wiersze z paskami przycisków (`QSizePolicy.Ignored`) kurczyły się do zera,
  więc w `ui_widgets.py` jest `AllNonFixedFieldsGrow`; (3) `QSizePolicy.Ignored` na
  przyciskach ucina tekst w środku („Wykryj kotwicę" → „kryj kotw") — paski przycisków idą
  przez `add_widget_row` (pełna szerokość wiersza), a nie w kolumnie kontrolek; (4) minimalna
  szerokość inspektora to suma najszerszego wiersza: długie etykiety checkboxów, combosy
  (`setMinimumContentsLength`) i spinboxy (`Ignored` + `setMinimumWidth`) — po skróceniu
  `minimumSizeHint` spadł 453→393 px, więc `left_scroll.setMinimumWidth(380)` i
  `splitter.setSizes([420, 760])` wystarczają bez poziomego paska (tryb `--screenshot`
  wypisuje zmierzoną wartość na stdout). Nowe teksty (akcje, sekcje, pozycje) w `i18n._STRINGS`
  PL+EN, czytane przez `_TR = get_translator(Lang.PL)` — GUI jest po polsku.

- **Motyw UI z tokenów (v0.44.0):** `ui_theme.py` (kopia `scripts/qt_theme.py` ze skilla
  `python-desktop-ux`, bez sekcji demo) — Fusion + `QPalette` + QSS generowane z `TOKENS`
  przez `apply_theme(app, mode)`; `setup_hidpi()` (PassThrough) PRZED `QApplication`,
  `set_app_user_model_id("Piro.Overlay")`, `load_app_fonts(Path(resources.font_path()).parent)`,
  `QSettings` (org „Piro", app „PiroOverlay"; klucze `ui/geometry`, `ui/splitter`, `ui/theme`
  — NOWA przestrzeń, nie rusza `config.py`), ciemny pasek tytułu (`set_windows_dark_titlebar`
  po `show()`, helper `gui._dark_titlebar` dla kolejki/wsadu/dialogu CLI). Splitter zapisany
  jako `self.splitter` w `_build_ui`. Flaga dev: `python -m piro_overlay.gui --screenshot PATH
  [--scale F] [--light]` — sama ustawia `QT_QPA_PLATFORM=offscreen`, `QT_QPA_FONTDIR` i
  `QT_SCALE_FACTOR` PRZED `QApplication` (zmienne z powłoki WSL nie docierają pewnie do
  procesu Windows), wymusza rozmiar 1180x760 i pomija restore geometrii (powtarzalne zrzuty),
  zapisuje okno + `_inspector`; flagi są zdejmowane z `argv` (bo `app.py` przekazuje KAŻDY
  argument do CLI, więc żyją wyłącznie w `gui.main()`). Zrzuty: `pictures/ui-refresh/`.
  PUŁAPKI: (1) `QScrollArea` ma w QSS przezroczyste tło, a `widget.grab()` na przezroczystym
  płótnie GUBI krycie tekstu etykiet (wyglądają na prawie czarne) — inspektor renderujemy
  przez `QPixmap.fill(bg)` + `widget.render(pix)`; (2) kontrolki motywu są wyższe/szersze niż
  domyślne Fusion, więc lewa kolumna (`minimumSizeHint` 478 px) dostawała poziomy pasek
  przewijania — `left_scroll.setMinimumWidth` 360→500, `splitter.setSizes` [380,800]→[540,640];
  (3) `QGroupBox::title` z szablonu maskuje linię sekcji tłem `surface` — na tle okna (`bg`)
  wyglądało to jak szara plakietka, więc w `build_qss` tytuł ma `background: $bg`.
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
  uchwyty=trim, znaczniki=onsety). Ctrl+klik = podgląd klatki z nakładką (scrubber);
  gdy działa podgląd w ruchu, Ctrl+klik tylko PRZEWIJA playera (bez ekstrakcji FFmpeg
  i bez drugiego markera). Oś ma DWA kursory czasu: `preview_t` (klatka scrubbera —
  linia przerywana, trójkąt konturowy, pastylka „⊹") i `playhead_t` (pozycja
  odtwarzania — linia ciągła, trójkąt wypełniony, pastylka „▶"); `set_playhead`
  przesuwa okno widoku dopiero, gdy playhead z niego wyjedzie (bez zmiany zoomu).
  Klawiatura osi (v0.50.0): I/O = „Od"/„Do" w bieżącym czasie (`current_t()` =
  playhead → kursor podglądu → kotwica → „Od"), T = kotwica, M = dodaj strzał
  (sygnał `addShotAt`). UWAGA: samo O przejęło rolę punktu „Do" z konwencji edytorów
  wideo, więc warstwa onsetów przeszła na **Shift+O**.
  Od v0.48.0 rysowanie idzie WYŁĄCZNIE z tokenów motywu (`current_tokens` czytane
  w `paintEvent`, bez kopii w polach), obwiednia jest w cache `QPixmap`
  (`_ensure_wave_cache`, klucz `(len(env), view_start, view_end, w, h, kolory)`),
  etykiety markerów układają się w dwóch rzędach bez kolizji, a oś przyjmuje fokus
  i klawiaturę — szczegóły w sekcji „Oś czasu, podgląd i format czasu (v0.48.0)".
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
  <100 ms). **Guard obwiedni + scoring (v0.42.0),** realny przypadek z sesji 2026-08-12
  (plik `_0035`): metaliczny kling **zrzutu zamka** („Load and make ready" pada przed
  KAŻDYM startem!) dzwonił tonalnie 4.1 kHz przez równo 150 ms z koncentracją 0.8 —
  przeszedł GŁÓWNY test i jako najwcześniejszy wygrał z idealnym bzyczkiem (2720 Hz,
  650 ms, conc 0.99) granym 6 s później → T0 o 6 s za wcześnie. Koncentracja+ciągłość
  NIE odrzucają dzwoniącej stali (jest tonalna i wybrzmiewa >150 ms); rozróżnia ją
  dopiero OBWIEDNIA: (3) `_impact_ring` — run o profilu impulsu (szczytowe okno ≥5×
  drugiego najgłośniejszego, `_BUZZER_IMPACT_RATIO`) odpada w głównym teście i w
  fallbacku (kling: spadek 12× między oknami + dryf częstotliwości w dół, jak
  wybrzmiewający metal; buzzer: płaska amplituda, wahania ~3×, częstotliwość co do Hz);
  (4) scoring — najwcześniejszy run wygrywa, CHYBA że jest marginalny (≤`MIN_RUN`+1
  okien i conc <0.85 — +1 okno na rozmycie AAC), a później gra solidny (≥2×`MIN_RUN`
  i conc ≥0.9): wtedy wygrywa solidny (drugi bezpiecznik na artefakty o płaskiej
  obwiedni; marginalny BEZ solidnego rywala nadal wygrywa — krótki/cichy bzyczek nie
  ginie). Walidacja polowa: 19 nagrań z 2026-08-12 (obie kamery) — DWIE zmiany wyniku
  i obie to naprawy: `_0035` (kling zrzutu zamka, ubił go guard obwiedni) oraz `_0027`
  (dryfujący ton ~3.7 kHz, conc 0.76, obwiednia PŁASKA — ubił go dopiero scoring:
  prawdziwy bzyczek 2720 Hz/conc 1.00 grał 18 s później; stara detekcja myliła się tu
  PO CICHU). 17 pozostałych bez zmian. Testy: `test_impact_ring_field_profiles` (liczby z realnego
  nagrania), `test_detect_dji_start_ignores_slide_drop_ring`,
  `test_detect_dji_start_prefers_solid_run_over_marginal`,
  `test_detect_dji_start_marginal_alone_still_wins`. FALLBACK gdy główny test nic nie znajdzie (bzyczek krótki/zagłuszony — tylko 1
  okno przebija próg koncentracji): bierze najwcześniejsze okno o conc≥0.7, którego
  **dominująca częstotliwość jest stabilna ±150 Hz przez ≥150 ms** (ton ma stałą częstotl.,
  strzał błądzi). Fallback odpala się tylko gdy główny zwróciłby None — zero regresji.
  GUI: przycisk „Wykryj sygnał startu" (obok „Wykryj kotwicę") wymusza
  `AnchorMode.START_SIGNAL` i ustawia wynik jako T0; zwykłe „Wykryj kotwicę" używa
  `detect_start` (bez filtra, pierwszy onset).
- **Dekodowanie ID sesji z sygnału tonowego (v0.27.0, protokół v2 od v0.33.0,
  v3 od v0.65.0):**
  `audio_sync.decode_id_tone` odczytuje ramkę ID z pary timer↔kamera — timer
  (www.timer.pifpaf.fun, `playIdToneFrame`) i kalkulator (www.piro-kalkulator.pifpaf.fun,
  `id_tone.js`) odtwarzają kod przez głośnik telefonu: marker 5000 Hz („tu zaczyna
  się kod") + **6 slotów: slot 0 = KANAŁ, sloty 1–4 = WARTOŚĆ (zero-padded), slot 5 =
  cyfra kontrolna** (`_id_tone_checksum` = suma ważona pozycją 1–5 po `[kanał, 4 cyfry]`
  mod 10 — odczyt niezgodny z checksumą jest ODRZUCANY, żeby nie pobrać cudzej sesji),
  każdy jako jeden z 10 tonów 5200–7000 Hz (co 200 Hz), ton 300 ms + 50 ms ciszy,
  sekwencja powtórzona 2× dla odporności. Wynikiem jest `IdToneCode(channel, value)`
  (własności `is_db_id`, `entry_id`, `temp_id` → `"30147"`, `label` → `#1234` / `3-0147`),
  a NIE `int` jak w v2. **Protokół v3 (v0.65.0) NIE jest kompatybilny z v2** (ramka ma
  slot więcej), a v2 (v0.33.0) nie był kompatybilny
  z v1 (5250–7500 Hz co 250 Hz, 200 ms, bez checksumy) — nagrania sprzed zmiany nie
  dekodują się nową wersją; wydawać RAZEM z aktualizacją timera i kalkulatora.
  **STAŁE PROTOKOŁU MUSZĄ BYĆ IDENTYCZNE W TRZECH REPOZYTORIACH** — tu
  (`audio_sync.py`, `_ID_TONE_*` + `_id_tone_checksum`), w timerze
  (`www.timer.pifpaf.fun/index.php`, `playIdToneFrame` + `idToneChecksum`) i w kalkulatorze
  (`www.piro-kalkulator.pifpaf.fun/id_tone.js`). Zmiana częstotliwości, czasów, liczby
  slotów albo wag checksumy w JEDNYM z nich rozjeżdża cały łańcuch — poprawiaj wszystkie
  trzy w jednej fali wydań. Sufit pasma obniżony
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
  DANYCH jest odzyskiwany (od v0.65.0 slotów danych jest 5: kanał + 4 cyfry wartości);
  wagi 1/3/5 nad 10: waga 1 i 3 dają jednego kandydata, wagi 2 i 4 → 2 kandydatów
  (rozstrzyga energia pasm, bez wyraźnego zwycięzcy → None), a **waga 5 (ostatnia cyfra
  wartości) → 5 kandydatów, więc odzysk jest tam z zasady ODMAWIANY**
  (`_ID_TONE_RESCUE_MAX_CAND` = 2 — to już zgadywanie, nie odzysk); (5) **marker z edge-floor**
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
  None; v3: `test_decode_id_tone_temp_code` = ramka z kanałem 1–9,
  `test_decode_id_tone_checksum_recovers_missing_channel` = odzysk slotu kanału,
  `test_decode_id_tone_weight5_recovery_refused` = odmowa przy wadze 5);
  `conftest.id_tone_expr` ma parametry `skip_slots`/`slot_amps`/`checksum_offset`/
  `skip_markers`/`t_start`/`channel` i sam dolicza cyfrę kontrolną (numery slotów liczą
  się OD KANAŁU — slot 0 = kanał).
  Pasmo 5000–7000 Hz wybrano tak, by (1) NIE kolidować z pasmem bzyczka 2000–4800 Hz i
  (2) zmieścić się pod Nyquistem tej samej ekstrakcji audio 16 kHz (`_load_audio`, Nyquist
  8000 Hz) — bez potrzeby osobnej ścieżki ekstrakcji o wyższym sample rate; sufit 7000 Hz
  (nie 7500 jak w v1) wynika z pomiaru realnego nagrania — patrz uzasadnienie v2 wyżej.
  GUI: przycisk „Wykryj ID z audio" (grupa źródła danych, pod polem ID) woła
  `decode_id_tone` NA `self.video_path` (świadomie NIE na proxy LRF — sygnał ID gra pod
  koniec nagrania, poza oknem na które LRF było dotąd używane), wpisuje wynik do
  `id_spin`, przełącza źródło na ID (`rb_id`) i OD RAZU woła `_fetch_id_and_trim()`
  (pobranie z API + T0 + przycięcie) — od v0.38.0; wcześniej celowo bez auto-fetch,
  ale wykryte ID przechodzi checksumę protokołu, więc ręczne „Pobierz" było zbędnym
  krokiem (feedback z użycia). Wsad (`BatchIdDetectWorker`) ZOSTAJE bez auto-fetch —
  tam użytkownik weryfikuje ID hurtowo przed „Przygotuj wszystkie".
- **Panel „lista strzałów" + nakładka metadanych (v0.37.0):** `OverlayStyle.panel_mode`
  (`"classic"`/`"list"`). Tryb listy: ostatnie ≤`list_max_rows` (domyślnie 5) strzałów jako
  pigułki (numer | czas | split), najnowszy na dole (większy font, pełna alfa), starsze
  przesunięte wyżej i wygaszane (`_LIST_ALPHA_*`); aktywny wiersz może pokazywać numer jako
  „x/yy" (`list_show_progress`, domyślnie ON). Panel ma STAŁY rozmiar z konstrukcji
  (wysokość = `list_max_rows` slotów dosuniętych do DOŁU — najnowszy strzał zawsze w tym
  samym miejscu ekranu; szerokości kolumn liczone po WSZYSTKICH strzałach), więc
  `fixed_size` jest w tym trybie zbędny/ignorowany. DISPATCH jest w
  `overlay.render_shot_panel`/`shot_panel_max_size` (po `style.panel_mode`) — dzięki temu
  `render.build_events`, `preview.compose_preview` i scrubber GUI nie znają trybu panelu
  (zero zmian w ich logice okien czasowych; jeden panel na przedział między strzałami jak
  dotąd). Teksty pionowo kotwiczone `anchor="lm"` (wspólna oś kolumn o różnych fontach —
  bez tego numer siedział wyżej niż czas/split, realny bug report z prototypu). Osobna
  **nakładka metadanych** `render_meta_panel` (jedno tło: nazwa toru + „uczestnik — x
  strzałów", i18n `shots_label`; None gdy sesja bez metadanych): `show_meta_panel` +
  `meta_position`/`meta_offset_x/y`, w `build_events` jako zdarzenie z `xy=`
  (`panel_origin_at`) grające od T0 do końca RÓWNOLEGLE z panelami strzałów — dlatego
  pętle podglądu (preview.py, gui scrubber) NIE robią już `break` po pierwszym aktywnym
  zdarzeniu i honorują `ev.xy`. GUI: combo „Styl panelu", spin „Wiersze listy", checkboxy
  progresu i metadanych, pozycja+offsety metadanych; przeciąganie w podglądzie obsługuje
  trzeci prostokąt `_preview_rects["meta"]` (priorytet trafień: zegar → meta → panel).
  W trybie listy nazwa toru/uczestnik/licznik NIE są w panelu strzału — od tego jest
  nakładka metadanych i panel podsumowania (bez zmian). Snapshoty:
  `shot_list_panel_pl.png`, `meta_panel_pl.png`.
- **Przypięty pierwszy strzał + czas pierwszego strzału w podsumowaniu (v0.40.0),**
  feedback z Bill drilla (ID 300/305: 6 strzałów w ~3.25 s, splity ~0.3 s — czas
  strzału 1 znikał z listy po <2 s i wracał dopiero nigdy): `OverlayStyle.
  list_pin_first_shot` (domyślnie ON; checkbox w GUI obok progresu listy — wsad
  dziedziczy przez kopię `current_style()`). Gdy strzał 1 wypada z naturalnego okna
  (`idx >= list_max_rows`), zostaje PRZYPIĘTY w górnym slocie: stała czytelna alfa
  `_LIST_ALPHA_PINNED=155` (celowo NIE wygaszany jak najstarszy — to sedno feedbacku)
  + dodatkowy odstęp `_LIST_PIN_EXTRA_GAP` od reszty listy; środek pokazuje wtedy
  `list_max_rows−2` poprzednich strzałów. Odstęp jest DOLICZONY do `panel_size` w
  `_list_metrics` tylko gdy przypięcie kiedykolwiek się uaktywni dla tej sesji
  (`_list_pin_enabled`: pin ON + rows≥2 + strzałów > rows — zależy tylko od
  sesji+stylu, więc gwarancja „stały rozmiar z konstrukcji" zostaje; pozycje pigułek
  dolnych bez zmian, pin rysowany w y=0). Sesje ≤ rows wyglądają identycznie jak bez
  funkcji (test `test_list_panel_pin_noop_for_short_session`). Tryb classic celowo
  BEZ zmian. `render_summary_panel` dostał linię `first_shot` (i18n) po nagłówku —
  tylko gdy strzałów >1 (przy jednym dublowałaby czas bazowy). Snapshoty
  `shot_list_panel_pl`/`summary_panel_pl` zregenerowane.
- **Diagnostyka renderu w metadanych pliku (v0.39.0):** `render._diag_metadata_args`
  dokłada `-metadata comment=<JSON>` do render_video (per próba enkodera — po fallbacku
  w pliku jest FAKTYCZNY enkoder), render_webm i trim_video (GIF nie ma metadanych
  kontenera — pomijany). Payload: wersja aplikacji, kind (overlay/trim), rendered_at,
  trim, t0, anchor, encoder, liczba strzałów/ostatni strzał/tor/uczestnik oraz PEŁNY
  `style.to_dict()`. Odczyt: `ffprobe -show_format plik.mp4` albo `ffmpeg -i` (UWAGA:
  `ffmpeg -i` UCINA wyświetlaną wartość ~256 znaków — pełny JSON jest w pliku; asercje
  testów celują w pola z początku payloadu). Powód: diagnoza „czemu render tak wygląda"
  (np. stary styl z pamięci per-plik / zapisanej kolejki) bez zgadywania — plik sam mówi,
  czym i z jakimi parametrami powstał. Testy: `test_diag_metadata_args_payload`,
  `test_render_video_embeds_diag_metadata` (e2e na tiny_video).
- **Plansza START w stylistyce pigułek (v0.39.0):** `render_start_banner` rysuje własne
  tło (rounded, radius `panel_h*0.18`) i kotwiczy napis `anchor="mm"` w środku — stary
  `_render_panel` rysował tekst od górnej krawędzi tight-bboxa, więc wersaliki „START"
  siadały optycznie za nisko. Nowe domyślne: `start_banner_bg_color=(0,0,0,150)`
  (bardziej przezroczysta), `start_banner_border_enabled=False`; pola stylu bez zmian
  (obramowanie nadal dostępne, tylko domyślnie wyłączone). Snapshot `start_banner_pl`
  zregenerowany.
- **Operacje w tle + „wynik zawsze widoczny" (v0.47.0):** `gui.FuncWorker` (QThread
  wołający domknięte `functools.partial`) zastąpił `StartDetectWorker` i jest JEDYNYM
  mechanizmem długich operacji okna głównego: detekcja bzyczka, kotwicy, ID z audio,
  pobranie sesji z API. Sterowanie w `MainWindow._run_op(fn, button=…, busy_text=…,
  status_text=…, on_result=…, on_error=…)`: `set_busy` na przycisku, `progress.setRange(0,0)`
  (nieokreślony), komunikat w pasku stanu i przycisk „Anuluj" (`op_cancel_btn`, ghost,
  widoczny tylko w trakcie). Jeden worker naraz (`_op_worker`); kolejne żądanie dostaje
  „Trwa inna operacja…". ZASADA (powód porzucenia synchroniczności, patrz wpis wyżej):
  każda ścieżka zakończenia — wynik, brak wyniku, wyjątek, anulowanie — kończy się
  `status_message` (+ `InlineMessage` przy braku wyniku) i odblokowaniem przycisków;
  żadnej „cichej pustki". Token pokolenia `_op_gen` odrzuca wyniki po anulowaniu i po
  zmianie pliku (`_set_video` woła `_cancel_operation(silent=True)`); workery żyją
  w `_op_workers` do `finished`, `closeEvent` na nie czeka (QThread niszczony w trakcie
  = crash). Łańcuchy operacji (ID z audio → API → detekcja T0 → przycięcie) to kolejne
  `_run_op` wołane z `on_result`. SYNCHRONICZNE zostaje tylko `_apply_auto_trim`
  (arytmetyka na znanych wartościach) i `_next_candidate` — wątek byłby tam kosztem
  bez zysku; `_collect_render_kwargs` nadal woła `api.fetch_session` synchronicznie
  przy starcie renderu (jedno szybkie żądanie tuż przed długim workerem).
- **Komunikaty, stan pusty, walidacja inline (v0.47.0):** komunikaty trzyczęściowe
  (co / dlaczego / co zrobić) są w `i18n._STRINGS` (`msg_*`) i idą przez
  `MainWindow._notify(where, text, kind)` — pełny tekst w `InlineMessage` pod sekcją
  (`input_msg` w „Wejście", `sync_msg` w „Synchronizacja"), pierwsze zdanie w pasku
  stanu. `QMessageBox` ZOSTAJE tylko dla błędów blokujących: błąd API i błąd renderu
  (krótkie zdanie + `setDetailedText` z wyjściem FFmpeg) oraz dla ostrzeżenia po
  udanym renderze (fallback enkodera). Sukces renderu/anulowanie/„render już trwa"
  to pasek stanu, nie modal. Walidacja przycięcia (`_validate_trim`, `editingFinished`
  — NIE przy każdym znaku): `setProperty("invalid", …)` + repolish na obu spinach +
  `InlineMessage` z zakresem 0–długość. Stan pusty podglądu: `preview_stack`
  (`QStackedWidget`) — strona 0 to „Brak wideo" + podpowiedź + primary „Otwórz wideo…",
  strona 1 to TEN SAM `preview_label` co dotąd (scrubber i przeciąganie pozycji
  wymagają tego samego obiektu). Bez wideo `act_render`/`render_btn` są wyłączone
  (`_set_render_enabled` sprawdza też `video_path`), więc primary na widoku jest jeden.
  Tytuł okna: `"<plik> — Piro Overlay"` po wczytaniu, `"Piro Overlay v<wersja>"` bez pliku.
  Klawiatura: Escape zamyka `RenderQueueWindow`/`BatchDialog` (to `QWidget`, nie
  `QDialog` — `QShortcut(QKeySequence.Cancel, …)`) i wychodzi z trybu „Edytuj pozycje".
  Tryb `--screenshot` przyjmuje `--video PATH` (wczytuje plik i czeka pętlą
  `processEvents` na analizę audio — jedyne dopuszczalne użycie `processEvents`).
- **Podgląd w ruchu + pasek transportu + skróty osi (v0.50.0):** czwarta strona
  `preview_stack` — `gui.VideoPlayerPage` (`QGraphicsView` + `QGraphicsVideoItem`)
  napędzana `QMediaPlayer`. DLACZEGO tak, a nie „klatka z QVideoSink przemalowana
  Pillow": dekodowanie i skalowanie zostaje po stronie Qt (zero kopii przez Pythona
  na każdą klatkę), a nakładki liczy RAZ `render.build_events` — te same okna czasowe
  co render — i wrzuca jako `QGraphicsPixmapItem`; przy klatce przełączamy tylko
  `setVisible` (odpowiednik `enable='between(t,a,b)'` z filtergrafu). Pozycje liczy
  `render._overlay_xy`, więc player, `preview.compose_preview` i render nie mogą się
  rozjechać. Układ współrzędnych sceny = płótno nakładek: `min(wysokość źródła,
  _PLAYER_OVERLAY_H=540)` — panele rysujemy w 540p, nie w 4K. **Źródłem jest proxy:**
  LRF (DJI) → proxy podglądu 540p → oryginał (od v0.52.0 — pierwotnie
  `self.lrf_path or self.video_path`, co dla plików BEZ LRF oznaczało 4K wprost do
  playera i kilka klatek na sekundę; patrz wpis „Proxy podglądu"). Mały plik dekoduje
  się od ręki, a offsety i tak skalujemy przez `_scaled_style` do wysokości ORYGINAŁU
  (WYSIWYG jak dotąd).
  Synchronizacja nakładek idzie z `QVideoSink.videoFrameChanged` →
  `frame.startTime()` (µs) — dokładniejsze niż `positionChanged`, który zasila tylko
  playhead i etykietę czasu. **ALE tylko w `PlayingState` (v0.51.1):** w pauzie/po
  zatrzymaniu jedyną wiarygodną osią czasu jest `player.position()`, bo po
  `setPosition` backend potrafi dosłać klatkę ze znacznikiem SPRZED przewinięcia —
  nakładki zostawały wtedy na starym zdarzeniu (realny objaw: zrzut
  `09-icons-dark.png` pokazywał planszę START zamiast panelu strzału 1 na 3,5 s,
  a jasny wariant tej samej pozycji był poprawny — czysta wyścigówka). Stąd trzy
  bezpieczniki: `_sync_overlays(t)` jako jedyne wejście do sceny; `_on_player_position`
  synchronizuje scenę także poza odtwarzaniem; `_seek` dokłada jednorazowy
  `QTimer.singleShot(_SEEK_VERIFY_MS=150)` → `_verify_seek_overlays` (kontrola, czy
  scena zgadza się z `position()`), a klatki starsze od pozycji o ponad
  `_FRAME_STALE_S=0.5` s są w pauzie ignorowane. Zegar (`show_running_clock`) to jedyna nakładka zależna
  od czasu: `render_clock_panel` z `fixed_size=clock_panel_max_size(...)`, treść
  liczona co dziesiątą sekundy i keszowana po tej wartości (`_clock_cache`,
  `_CLOCK_CACHE_MAX`), zamrożona na ostatnim strzale — jak w renderze. Przebudowa
  nakładek: JEDNA funkcja `_rebuild_player_overlays()` przez debounce
  `_PLAYER_REBUILD_MS` (zmiana stylu/sesji/T0) — bez tego każdy tick spinboxa
  renderowałby N paneli Pillow. **Rozgrzewanie (`_priming`/`_primed`/`_prime_pending`):**
  po `setSource` scena jest PUSTA, dopóki player czegoś nie zdekoduje, więc przy
  `LoadedMedia` robimy RAZ wyciszone play→pauza→seek(T0); pauza i seek lecą przez
  `QTimer.singleShot(0, …)`, bo wywołane z wnętrza sygnału sinka potrafią zawiesić
  backend, a `_priming` gaśnie dopiero w `_finish_prime` (inaczej zrzut/test uzna
  rozgrzewanie za skończone za wcześnie i jego `play()` dostanie pauzę z rozgrzewania).
  Pasek transportu nad podglądem: glify (`|◀ ◀◀ ▶/❚❚ ▶▶ ▶| ↻`) z tooltipami niosącymi
  skrót; skróty okna Spacja/J/K/L/,/. i Home/End przez `_transport_shortcut`
  (odpuszcza, gdy fokus jest w polu tekstowym; Spacja na przycisku go KLIKA).
  Home/End na osi zostaje przy kotwicy — `_home_key`/`_end_key` delegują do
  `waveform.commit_anchor`, bo `QShortcut` okna ma pierwszeństwo przed `keyPressEvent`
  widżetu. Pauza na „Do" albo pętla Od–Do (`loop_btn`). Tryb „Edytuj pozycje" pauzuje
  player i wraca na stronę statyczną (Pillow zostaje źródłem prawdy WYSIWYG dla
  przeciągania) — `_show_image` NIE przełącza już strony samo, robi to
  `_show_preview_page()`. Import `PySide6.QtMultimedia*` jest w try/except
  (`_HAS_MULTIMEDIA`), a `errorOccurred` ustawia `_player_failed` → transport gaśnie,
  wracamy do podglądu klatki i mówimy dlaczego (`msg_player_error`): funkcja jest
  ADDYTYWNA, jej awaria nie może zabrać niczego, co działało. `closeEvent` woła
  `_release_player()` (stop + `setSource(QUrl())`) — żywy strumień przy niszczeniu
  sceny potrafi wywalić proces. **PyInstaller:** hook PySide6 zbiera QtMultimedia
  i pluginy (`PySide6/plugins/multimedia/`), ale moduły importujemy warunkowo, więc
  `build_exe.spec` wymienia je JAWNIE w `hiddenimports`; po buildzie sprawdź, czy
  w `dist/` jest `ffmpegmediaplugin.dll` / `windowsmediaplugin.dll` — bez nich player
  zgłosi błąd i zostanie sam podgląd statyczny.
- **Proxy podglądu 540p (v0.52.0)** — odpowiednik LRF dla plików, które go nie mają.
  POMIAR (DJI `DJI_20260812195408_0036_D.MP4`: HEVC Main 8-bit, 3840×2880, 50 fps,
  66 Mbit/s, BEZ pliku .LRF obok): `QMediaPlayer` (backend ffmpeg Qt 6.11) dekoduje
  go PROGRAMOWO — **4 klatki na 5 s odtwarzania**; podpowiedzi
  `QT_FFMPEG_DECODING_HW_DEVICE_TYPES=d3d11va|cuda|dxva2` NIC nie dają. To samo
  nagranie jako proxy 540p H.264: budowa **21,5 s** (NVENC), odtwarzanie **~50 fps**
  (253 klatki/5 s), 24,8 MB. Seeki w pauzie i sync nakładek działały na 4K poprawnie —
  problemem jest wyłącznie przepustowość dekodera.
  - **Domena:** `render.make_preview_proxy(video, out, *, height=PREVIEW_PROXY_HEIGHT=540,
    encoder="auto", progress_cb, cancel_check, on_process, on_encoder)`. Komenda:
    `-map 0:v:0 -map 0:a:0?` (pliki DJI mają obok HEVC miniaturę MJPEG i strumień
    `djmd` — ta sama pułapka `0:v:0` co w render/trim), `scale=-2:540`, audio AAC 96k,
    `+faststart`, `UNTRUSTED_INPUT_ARGS` przed `-i`, postęp/anulowanie przez
    `_run_with_progress`. Trzy próby po kolei: NVENC `-hwaccel cuda -preset p1 -b:v 3M`
    → NVENC bez `-hwaccel` → `libx264 -preset ultrafast -crf 28` (bez NVENC budowa
    idzie mniej więcej w czasie rzeczywistym, czyli ~1 min na minutę nagrania —
    znośnie, bo raz na plik). PUŁAPKA: zapis idzie do `*.part.mp4` i dopiero po
    sukcesie `rename` — przerwana budowa (anulowanie, awaria, zamknięcie aplikacji)
    NIE MOŻE zostawić w cache pliku wyglądającego na gotowe proxy.
  - **Cache (`config.py`):** `proxy_dir()` = `config_dir()/"proxies"`;
    `proxy_path_for(video)` = `sha1("<ścieżka>|<rozmiar>|<mtime_ns>")[:20] + ".mp4"`
    (podmiana pliku pod tą samą nazwą daje inny skrót — nigdy nie odtworzymy proxy
    nieodpowiadającego zawartości); `find_proxy` (istnieje i > 0 B); `prune_proxies`
    (24 pliki / 3 GB, kasuje najstarsze po `atime`/`mtime`) wołane po każdej udanej
    budowie. Katalog jest OSOBNY — `file_settings.json`/`last_style.json` bez zmian.
  - **Polityka źródła (GUI, `_set_video`):** `lrf_path` → gdy `probe` mówi
    `height > 1080` LUB `codec` zawiera `hevc` (nowe pole `ffmpeg.VideoInfo.codec`,
    z `codec_name` w ffprobe albo `Video: hevc` ze stderr) → `config.find_proxy`;
    brak → budowa w tle. Pliki ≤1080p H.264 grają wprost, jak dotąd. Do czasu
    gotowości player jest NIEAKTYWNY (`_set_player_pending` zeruje `_player_size`,
    więc `_player_active()` = False → transport wyłączony, tooltip
    „Trwa przygotowanie proxy podglądu"), zostaje podgląd klatki. `FrameExtractWorker`
    czyta ze wspólnego `_frame_src()` (LRF → proxy → oryginał) — ekstrakcja klatki
    z 4K HEVC trwa sekundy, z proxy ułamek; `PREVIEW_HEIGHT=360` < 540, więc jakość
    podglądu bez zmian.
  - **Kolejność zadań:** budowa rusza dopiero po `_on_wave_done` i tylko gdy wolny
    jest slot `_run_op` (analiza audio + detekcja T0 mają pierwszeństwo) oraz gdy nie
    trwa render (`_render_busy`) — inaczej `_maybe_start_proxy` odpytuje co
    `_PROXY_RETRY_MS=1000` (świadomie proste odpytywanie zamiast łańcucha sygnałów;
    `_reset_render_ui` dobudza je po renderze). Zmiana pliku w trakcie budowy anuluje
    ją przez istniejący `_cancel_operation` + token pokolenia `_op_gen`.
  - **`_run_op(..., progress=True)`:** pasek postępu jest DETERMINISTYCZNY (0–100 %),
    a `fn` dostaje trzy uchwyty jak render — `fn(progress_cb, cancel_check, on_process)`
    (`FuncWorker(with_callbacks=True)`; `cancel()` dodatkowo ubija proces FFmpeg, bo
    sama flaga zadziałałaby dopiero przy kolejnej linii postępu). Pasek stanu
    („Przygotowuję proxy podglądu… N %") odświeżany nie częściej niż raz na sekundę.
  - **Ustawienie:** checkbox „Proxy podglądu (auto)" w sekcji „Wejście" pod polem
    Wideo (to sprawa WEJŚCIA — render zawsze idzie na oryginale), stan w
    `QSettings("ui/preview_proxy")`, domyślnie ON.
  - **PUŁAPKA odkryta przy weryfikacji (v0.52.0):** `setPosition` zrobione w PAUZIE na
    nagraniu, które jeszcze nie było odtwarzane, bywa przez backend GUBIONE — `play()`
    ruszał od 0 zamiast od kursora (zmierzone: po rozgrzewaniu + seek na T0−1 s
    odtwarzanie szło od zera; dotyczy i 4K, i proxy). `_on_play_toggled` po `play()`
    sprawdza więc pozycję (`_PLAY_RESUME_MS=200`) i przy rozjeździe > 1 s przewija
    jeszcze raz.

- **`parser.format_timeline(shots)` (v0.50.0):** odwrotność `parse_timeline`
  (round-trip, test w `tests/test_parser.py`) — numeruje od 1 i PRZELICZA splity
  z czasów, bo po wstawieniu strzału w środek sesji stare splity są nieaktualne.
  Używa jej skrót **M** na osi: czas względem T0 (`resolve_t0`), wstawienie,
  sortowanie i zapis z powrotem do `timeline_edit`. Działa tylko przy źródle „Tekst"
  (oś z API jest do odczytu — `msg_shot_text_only`).
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
- **Auto-detekcja T0 + przycięcie:** po wczytaniu pliku (`_on_wave_done` →
  `_auto_detect_t0()`): T0 (`detect_dji_start`) + przycięcie 5 s przed → max 75 s po T0.
  Przycisk „Pobierz i przytnij" (`_fetch_id_and_trim`): pobranie z API + T0 + przycięcie
  5 s przed → ostatni strzał + 5 s. Zwykły „Pobierz" (`_fetch_id`) tylko pobiera dane.
  HISTORIA DECYZJI: do v0.46.0 „Pobierz i przytnij" i wszystkie ręczne detekcje działały
  SYNCHRONICZNIE (blokując UI), bo asynchroniczna detekcja bywała „cicho pusta" —
  wyglądała jak brak działania. Od v0.47.0 wszystko idzie przez `FuncWorker` + `_run_op`,
  a powód zniknął, bo KAŻDA ścieżka zakończenia melduje wynik (patrz wpis „Operacje
  w tle" niżej).
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
  `BatchIdDetectWorker` (QThread/plik) z `pipeline.detect_id_tone` na ORYGINALNYM
  pliku (nie LRF — jak `_detect_id_tone` w głównym oknie; sygnał ID gra pod koniec
  nagrania). Od v0.65.0 ramka może nieść KOD TYMCZASOWY (kanał 1–9) — wtedy worker
  dolicza jeszcze T0 (`pipeline.detect_start_signal`) i woła `pipeline.resolve_id_tone`,
  a wiersz dostaje źródło ID `"temp"` (ikona + „sprawdź"); brak rozstrzygnięcia zostawia
  powód w `row.error` i wiersz wraca do `NEEDS_ID`. Wynik wpisywany do spinboxa wiersza (`set_session_id` → `_on_id_changed`
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
- **Zestaw ikon SVG paska akcji/transportu (v0.51.0):** `assets/icons/*.svg` (24 pliki,
  własne, minimalne, liniowe — `viewBox="0 0 24 24"`, `stroke="currentColor"`,
  `stroke-width="2"`, zaokrąglone końce; kilka używa `fill="currentColor"` dla
  wypełnionych kształtów jak trójkąt play). `resources.icons_dir()` (obsługa
  `sys._MEIPASS`) + `ui_theme.icon(name, color=None, size=16) -> QIcon` — wczytuje plik,
  podmienia `currentColor` (zwykły `str.replace`, działa niezależnie od atrybutu:
  `stroke` czy `fill`) na `color` albo domyślnie token `text` (dla primary „Renderuj"
  wołający jawnie podaje `accent_text` — tło przycisku jest już akcentem, `text` byłby
  prawie niewidoczny), renderuje `QSvgRenderer` i cachuje wynikowy `QIcon` po
  `(name, color, size)` — motyw ciemny/jasny mają różne tokeny, więc klucz cache
  rozjeżdża się sam; `ui_theme.clear_icon_cache()` (wołane z `_on_theme_toggled`) to
  tylko higiena pamięci, nie warunek poprawności. Stany `Normal`/`Disabled` (drugi kolor: `text_disabled`) —
  zwykłe `btn.setIcon(icon("play"))` przygasza się poprawnie przy `setEnabled(False)`.
  **PUŁAPKA — DPR × QT_SCALE_FACTOR renderuje pocięte/duplikowane ikony:** pierwsza
  wersja tworzyła `QPixmap(size*dpr)`, wołała `pm.setDevicePixelRatio(dpr)` PRZED
  `QPainter(pm)`, i renderowała `QSvgRenderer.render(painter)` bez jawnego rect —
  przy 100% skalowania wyglądało OK, ale zrzut `--scale 1.5` pokazał ikony
  pocięte/zduplikowane (dpr aplikowany dwa razy: raz przez `QT_SCALE_FACTOR`, raz przez
  ręczne `setDevicePixelRatio` na pixmapie, w którą się maluje). Fix: malować na gołym
  `QImage` (dpr zawsze 1) w rozmiarze FIZYCZNYM z jawnym `renderer.render(painter,
  QRectF(0,0,px,px))`, dopiero `QPixmap.fromImage(img)` dostaje `setDevicePixelRatio`
  — dpr wpływa tylko na to, jak Qt WYŚWIETLA gotową pixmapę, nigdy na to, jak się do
  niej maluje. Zweryfikowane zrzutem `pictures/ui-refresh/09-icons-150.png`.
  **Fallback bez `QtSvg`/pliku:** `icon()` zwraca pusty `QIcon()` (nie wyjątek) — SAM
  pusty `QIcon` nie robi nic złego na `QAction`/przycisku z widocznym tekstem
  (`ToolButtonTextBesideIcon`), ale przycisk **icon-only** (transport, „Dopasuj”/„Zoom
  Od–Do”, ✕/▶ w kolejce/wsadzie) zostałby całkiem pusty — stąd `gui._apply_icon(btn,
  name, size, fallback_text)`: gdy `icon.isNull()`, wpisuje `fallback_text` (stare glify
  `tr_t0`/`tr_play`/… albo zwykłe „✕”/„▶”) i przełącza `QToolButton` na
  `ToolButtonTextOnly`. `ensure_svg_support()` nie zmienia się w trakcie procesu, więc to
  jednorazowa decyzja bez potrzeby cofania.
  **Pasek akcji:** `ToolButtonTextBesideIcon`, ikony 16 px (nie 18 — zmierzone
  `sizeHint()` pokazało overflow ~10–50 px przy oknie 1180 px z 18 px ikonami: Fusion
  wtedy ucina tekst ELIPSĄ na WSZYSTKICH przyciskach naraz, nie tylko na najdłuższym).
  Dodatkowo `QToolBar` dostał ciaśniejszy `spacing` (`sp_1` zamiast `sp_2`) i własną
  regułę `QToolBar QToolButton { padding: 0 sp_1px; }` węższą niż gdzie indziej — bez
  obu zmian pasek z 9 przyciskami (ikona+tekst każdy) nie mieścił się w 1180 px wcale.
  „Motyw" pokazuje `sun`/`moon` zależnie od trybu. `MainWindow._refresh_icons()` jest
  JEDNYM miejscem przebarwienia po zmianie motywu — woła się z `_on_theme_toggled`,
  `sync_theme_action` i raz na końcu `__init__` (bo `_build_toolbar()` biegnie PRZED
  budową transportu/`edit_pos_btn`/`fit_btn`/`zoom_range_btn`, więc pierwsze wywołanie
  wewnątrz `_build_toolbar` jeszcze ich nie widzi) i deleguje do
  `RenderQueueWindow.refresh_icons()`/`BatchDialog.refresh_icons()` dla wierszy tych
  okien. **Pasek transportu** jest teraz icon-only (`ToolButtonIconOnly`, 20 px) zamiast
  glifów unicode wprost jako tekst przycisku — skrót w tooltipie (`tip_tr_*`, już miał
  „(J)"/„(L)"/…) jest jedynym opisem. Play↔pauza podmienia ikonę (`_on_player_state`).
  Bundle: `build_exe.spec` dokłada CAŁY katalog `assets/icons` do `datas` (nazwy plików
  są dynamiczne — `Analysis` ich nie widzi) i `PySide6.QtSvg` do `hiddenimports` (import
  jest w `try/except` w `ui_theme`, więc analiza bytecode'u by go pominęła — ta sama
  pułapka co przy `QtMultimedia`, v0.50.0). Po buildzie sprawdź w `dist/`:
  `PySide6/plugins/imageformats/qsvg.dll`, `PySide6/plugins/iconengines/qsvgicon.dll`,
  `PySide6/Qt6Svg.dll` — ich brak nie wywala aplikacji (fallback tekstowy działa), ale
  ikony po prostu nigdzie się nie pojawią. Strażnik bez PySide6: `tests/test_icons.py`
  (każdy SVG jest poprawnym XML-em z `viewBox="0 0 24 24"` i `currentColor`; nazwy
  użyte w `gui.py` przez `ui_theme.icon("x"...)`/`_apply_icon(btn, "x", ...)` — regex,
  nie import — mają odpowiadający plik na dysku).
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
  **Prefiks daty sesji (v0.60.1):** timer od 2026-09-20 dokłada PRZED opóźnieniem datę startu
  w formacie `toLocaleString('pl-PL')`: `"20.09.2026, 13:00:08 | opoznienie startu 3s | 1: …"`
  — `_SESSION_DATE_RE` odcina ją (nie interpretuje; czas startu niesie `timer_sess_id`), bez
  tego KAŻDA sesja z timera padała „Nie rozpoznano tokenu strzału: '20.09.2026, …'"
  (realny błąd z dnia premiery). ŚWIADOMIE trzymane, ale NIEUŻYWANE jeszcze w żadnej logice
  (T0/przycięcie/render) — GUI
  (`self.session.start_delay`) i web (`job.session.start_delay`, patrz `session_meta` w
  sekcji webowej) mają do niego dostęp, ale nic nie zmienia się w zachowaniu. Manualne
  wklejanie tekstu (bez prefiksu) działa jak dotychczas — `extract_start_delay` na tekście
  bez prefiksu zwraca `(tekst_bez_zmian, None)`.
- **Oś czasu, podgląd i format czasu (v0.48.0)** — piąta (ostatnia) iteracja odświeżenia
  UI wg skilla `python-desktop-ux` (§8 oś czasu, §9 podgląd, §11 klawiatura):
  - **`WaveformWidget` z tokenów:** tło osi `surface`, zakres Od…Do `accent_subtle`,
    poza zakresem `bg` z alfą 130 + fala w `text_disabled`, fala w zakresie `text_muted`,
    onsety `success` (alfa), kotwica T0/T1 `accent` 2 px, uchwyty Od/Do `info` 2 px
    (zieleń/czerwień ZNIKAJĄ — kolory semantyczne tylko dla stanów), krawędzie
    Start/Koniec `text_muted` przerywane BEZ pastylek, kursor podglądu `text` 1 px
    przerywany + trójkąt na osi, podziałka `border`, etykiety `text_muted`
    w `font_ui_small`. Zmiana motywu = samo `update()` (dopisane do `_on_theme_toggled`).
  - **Cache obwiedni:** `_ensure_wave_cache` renderuje falę do DWÓCH `QPixmap`
    (w zakresie / poza zakresem) z `setDevicePixelRatio`, jedna kolumna na piksel
    (`_columns`: max z próbek wpadających w kolumnę, a przy dużym zoomie odwrotnie —
    kolumna czyta próbkę ze swojego czasu, inaczej fala jest dziurawa). Klucz cache NIE
    zawiera przycięcia (żeby przeciąganie uchwytu nie przebudowywało pixmap) — stąd dwa
    pixmapy i `setClipRect` zamiast przebarwiania w locie. Mapowanie `_t2x/_x2t` i cała
    interakcja myszą bez zmian.
  - **Etykiety bez kolizji:** `_tag_rect`/`_draw_tag` — pastylka `RADIUS["r_sm"]`, tło
    w kolorze markera, tekst `accent_text` dla T0 i `text`/`bg` wybierane po luminancji
    tła (`_tag_text_color`). Dwa rzędy; trzecia kolizja = sam znacznik, tekst wraca
    w tooltipie po najechaniu (`_hover` + `_hidden_tags`). Priorytet: T0 > Od/Do > podgląd.
  - **Fokus i klawiatura osi:** `Qt.StrongFocus` + pierścień `_focus_ring` w `paintEvent`;
    ←/→ kotwica o 0,05 s (Shift: 1 s, `_commit_anchor` emituje `anchorChanged` jak klik),
    Home/End = granice przycięcia, `+`/`−` zoom, `0` reset (`fit_view`), `O` przełącza
    WARSTWĘ onsetów (widok, nie dane). Kursor `SizeHorCursor` w strefie uchwytu.
  - **Pasek nad podglądem:** `edit_pos_btn` jest teraz `QToolButton` checkable (stan
    `:checked` z QSS — `accent_subtle` + ramka `accent`), obok ghost „Dopasuj"
    (`fit_view`) i „Zoom do zakresu" (`zoom_to_trim`, widok = Od…Do + 5 %) oraz etykieta
    `role=mono` „▶ czas / długość". Skrót `E` przełącza tryb edycji tylko, gdy fokus nie
    jest w polu tekstowym/spinboxie/combo (`_shortcut_edit_pos`); Escape wychodzi (było).
    Transportu play/pauza NIE ma i mieć nie będzie — aplikacja nie odtwarza wideo.
  - **`PreviewLabel`:** w trybie edycji rysuje ramki 1 px `accent` wokół nakładek
    (`set_edit_rects` dostaje `_preview_rects` w pikselach KLATKI, `_to_widget` to
    odwrotność `_to_frame`) z podpisami `rect_panel`/`rect_clock`/`rect_meta`; poza trybem
    edycji podgląd jest czysty. Kursor `OpenHandCursor` nad nakładką (`setMouseTracking`).
    Klatka scrubbera czyści ramki (inny czas = inne pozycje paneli). Stan „Analiza audio…"
    to TRZECIA strona `QStackedWidget` (`_loading_page`: `role=muted` + nieokreślony
    `QProgressBar` 120 px) zamiast surowego tekstu na etykiecie podglądu.
  - **Jeden format czasu:** `_fmt_axis_time` (oś, pastylki, pasek podglądu) podmienia
    separator dziesiętny na ten z `QLocale` (PL: przecinek), a komunikaty o czasie idą
    przez nowe `_fmt_time_s` (`_fmt_num` + separator z locale). `_fmt_num` ZOSTAJE z kropką
    — używa go builder komendy CLI, gdzie przecinek byłby błędem składni.
  - **Ikony:** świadomie BEZ zestawu SVG (repo go nie ma) — zostają glify unicode ✥ i ▶.
  - **PUŁAPKA — tryb `--screenshot` kończył się kodem 9:** bez pętli zdarzeń żywy QThread
    (klatka/analiza audio) ginie razem z interpreterem i Qt wywala proces JUŻ PO wypisaniu
    „zapisano …" (pliki są poprawne, ale exit code kłamie, a przez potok WSL ginie też
    stdout). `main()` w trybie zrzutu czeka teraz na `_frame_worker`/`wave_worker`.
    Tryb zrzutu z `--video` ustawia demo osi czasu, węższe przycięcie, kursor podglądu
    i fokus na osi; nowa flaga `--edit` robi zrzut trybu „Edytuj pozycje".
- **Kolejka renderów i wsad przez komponenty UI (v0.49.0)** — odświeżenie okien
  pomocniczych (`RenderQueueWindow`, `BatchDialog`) tymi samymi komponentami co główne
  okno (skill `python-desktop-ux`), po pięciu iteracjach na oknie głównym (v0.44–v0.48.1):
  - **`RenderQueueWindow`:** nagłówek `SectionHeader` (klucz i18n `queue_title`), lista
    zadań w `QScrollArea` bez ramki, jeden `QStatusBar` (`status_message`) zamiast gołego
    `QLabel` — pokazuje łączny % i komunikaty stanu z rolami (info/warning/success);
    pasek akcji z JEDNYM primary („Start kolejki"), secondary „Zatrzymaj", reszta ghost.
    `JobRowWidget`: etykieta z elipsą środkową (`QFontMetrics.elidedText`, przelicza się
    w `resizeEvent`) + tooltip pełnej nazwy (albo powodu błędu, gdy ustawiony), „Usuń" jako
    `QToolButton` ghost „✕". Stan pusty (`queue_empty`) wyśrodkowany, `role=muted`.
    Geometria w `QSettings` (`ui/queue/geometry`, przez `restore_window_state`/
    `save_window_state(prefix="ui/queue")`) — odczyt w `showEvent` (raz), zapis w
    `closeEvent` (gdy kolejka nie renderuje).
  - **`BatchDialog`:** `QGroupBox("Ustawienia wspólne")` → `FormSection` (katalog
    docelowy jako `PathField(mode="dir")` — `PathField` już wspierał tryb katalogu,
    zero zmian w `ui_widgets.py`); pasek akcji: „Dodaj pliki…" secondary, reszta
    (import/eksport/wykryj ID) ghost, dół: „Przygotuj wszystkie" primary, „Wyślij gotowe
    do kolejki" secondary, „Wyczyść wszystko"/„Zamknij" ghost. Drag&drop plików wideo na
    całe okno (`setAcceptDrops`/`dropEvent` → `_add_row`, jak `_add_files`). Stan pusty
    listy (`batch_empty`). Pasek stanu: `QStatusBar` + `QProgressBar` nieokreślony
    (widoczny tylko gdy trwa `DETECTING`/`PREPARING`), przyciski „Przygotuj wszystkie"/
    „Wykryj ID z audio" w stanie `set_busy` podczas operacji w tle. `BatchRowWidget`:
    `_id_spin` jak `id_spin` głównego okna (`Fixed` 110 px, `NoButtons`, do prawej),
    nazwa pliku z elipsą środkową + tooltip pełnej ścieżki, „▶"/„Usuń" jako `QToolButton`
    ghost. Geometria w `ui/batch/geometry` (ten sam mechanizm co kolejka).
  - **`--window queue|batch` w trybie `--screenshot`:** `_screenshot_helper_window(win,
    kind)` otwiera odpowiednie okno pomocnicze z 2–3 przykładowymi wierszami (statusy
    PENDING/RUNNING/FAILED w kolejce; NEEDS_ID/READY/FAILED we wsadzie) i zwraca je do
    zrzutu zamiast głównego okna — `main()` rozgałęzia PRZED istniejącą logiką
    `--video`/grab głównego okna.
  - **`--id N` / `--at S` w trybie `--screenshot --video` (v0.52.1, zrzuty README):** prawdziwa
    sesja z API zamiast demo osi; przed „Pobierz i przytnij” WYMUSZA świeżą detekcję T0, bo
    `file_settings.json` ma pierwszeństwo i może nieść stary T0 sprzed poprawek detekcji
    (realny przypadek `_0035`: zapisane 26,2 s = kling zrzutu zamka, poprawne 32,05 s);
    player pauzuje na T0+S i czeka na NOWĄ klatkę po seeku (w offscreen bywała spóźniona —
    zrzut łapał same nakładki na tle sceny). Zrzuty w README: nagranie
    `DJI_20260812195106_0035` (ID 326, uczestnik Jaro), klatki nakładek z renderu (NVENC),
    JPG dla klatek wideo (PNG 3 MB → 250–300 KB).
  - **PUŁAPKA — `BatchDialog` za niski po zamianie `QGroupBox` na `FormSection`:**
    `FormSection` (nagłówek + odstępy tokenów) zajmuje więcej pionu niż
    `QGroupBox`+`QFormLayout`; przy starym `setMinimumSize(720, 460)` layout się nakładał
    (pola „Katalog docelowy"/„Prefiks"/„Format" zachodziły na siebie). Zmierzone
    `sizeHint()` z 3 wierszami wynosi ok. 690 px wysokości → `setMinimumSize` podniesione
    do `(720, 700)`.
  - **Nowe klucze `_STRINGS`:** `queue_title`, `queue_empty`, `batch_title`,
    `batch_empty` (PL+EN) — pozostałe teksty okien (nazwy przycisków, tooltipy)
    zostały jako literały PL zgodnie z resztą `gui.py` (drugi mechanizm i18n nie
    powstał).
  - Bez zmian: `RenderQueueRunner`, `BatchPrepWorker`, `BatchIdDetectWorker`,
    `_job_to_dict`/`_job_from_dict`, format `render_queue.json`, logika statusów.

- **Miniatura klatki w wierszu kolejki renderów (v0.53.0):** użytkownik miał w
  `RenderQueueWindow` same nazwy `DJI_2026…` i nie rozróżniał plików — każdy
  `JobRowWidget` dostał po lewej miniaturę 96×54 px (letterbox w tle `surface`,
  rogi `RADIUS["r_sm"]`) klatki ze ŚRODKA okna przycięcia zadania
  (`_job_thumb_anchor`: `(trim_start+trim_end)/2`, brak przycięcia → T0+1 s,
  brak T0 → 0). **Ekstrakcja sekwencyjna, NIE N naraz:** `QueueThumbWorker`
  (wariant `FrameExtractWorker` niosący `job_id`) + FIFO `RenderQueueWindow.
  _thumb_pending`/`_thumb_worker` — `_advance_thumb_queue` odpala kolejny worker
  dopiero po `finished` poprzedniego, więc 20 zadań dodanych naraz nie odpala
  20 równoległych FFmpegów. Źródło klatki (`_job_thumb_source`): `config.
  find_proxy` (proxy 540p) → `ffmpeg.find_lrf` → oryginał — ekstrakcja niska
  (`_QUEUE_THUMB_EXTRACT_H=108`), miniatura i tak ją pomniejsza. Wynik
  (`PIL.Image`) leci przez sygnał jak w `FrameExtractWorker` — konwersja na
  `QPixmap` (`_queue_thumb_pixmap`) TYLKO w wątku GUI (Qt tego wymaga); render
  robi zaokrąglone rogi przez `QPainterPath` + `QImage` z jawnym DPR (ta sama
  pułapka co przy ikonach SVG v0.51.0 — malować na `QImage` fizycznego
  rozmiaru, `setDevicePixelRatio` dopiero na `QPixmap.fromImage`). Placeholder
  (ikona `play-file` w `text_muted`) dopóki klatki nie ma/ekstrakcja padła —
  `JobRowWidget.set_thumb_frame` cache'uje wynik na wierszu (bez ponownej
  ekstrakcji przy update statusu/postępu), `refresh_icon()` przemalowuje
  WYŁĄCZNIE placeholder (klatka już wyciągnięta ma barwy z realnego obrazu,
  nie z tokenów). Zadania z `render_queue.json` (`_job_from_dict`) dostają
  miniatury leniwie — `add_job` woła `_request_thumb` zawsze, format pliku
  BEZ ZMIAN (miniatura nie jest serializowana). Pułapki QThread z reguł
  projektu: usunięcie wiersza w trakcie ekstrakcji filtruje `_thumb_pending`
  i `_on_thumb_done/_failed` sprawdzają, czy wiersz nadal istnieje w `_rows`;
  `RenderQueueWindow.closeEvent` i `MainWindow.closeEvent` czekają na żywy
  `_thumb_worker` (`wait(_THREAD_JOIN_MS)`) — ta sama zasada co przy innych
  workerach kolejki/wsadu. Tooltip miniatury (`queue_thumb_tooltip`, i18n
  PL+EN) pokazuje czas klatki przez `_fmt_time_s`. `--screenshot --window
  queue --video PLIK`: `_screenshot_helper_window` dostał parametr
  `video_path` — z prawdziwym plikiem demo-wiersze mają realną ścieżkę (bez
  niego `video_path` == etykieta wiersza, FFmpeg jej nie otworzy, więc
  placeholder — świadomie dopuszczalne), a `main()` doczekuje pustego
  `_thumb_pending`/`_thumb_worker` przed zrzutem (do 60 s).

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
- **Nadpisanie nazwy toru / uczestnika (v0.59.0)** — odpowiednik pól „Tor”/„Uczestnik”
  z GUI (v0.58.0). `Job.session_raw` (surowa sesja z `/session`) + `Job.meta_override`
  (dict `nazwa_toru`/`uczestnik`, surowy tekst pól); `job.session` = `session_raw` po
  `pipeline.apply_meta_override` (`api._apply_meta_override`, zeruje `preview_cache`) —
  `/preview`, `/render`, `session_meta` czytają `job.session` bez zmian. NOWY endpoint
  `POST /jobs/{id}/session-meta` (`SessionMetaBody`, 409 w trakcie renderu) ustawia
  nadpisanie BEZ ponownego pobierania z API i działa też PRZED `/session` (zostaje na
  zadaniu, nakłada się przy pobraniu). `SessionBody` przyjmuje opcjonalnie te same pola
  (gdy podane, zastępują zapamiętane nadpisanie; frontend ich tam nie wysyła).
  `session_meta` niesie dodatkowo `nazwa_toru_api`/`uczestnik_api` (wartości sprzed
  nadpisania) — frontend wstawia je jako placeholder pól `#meta-track`/`#meta-participant`
  (krok 02, pod listą strzałów; `renderSessionMeta` wspólne dla `/session` i
  `/session-meta`), zdarzenie `change` (nie `input`) → jedno żądanie po edycji.
  Odpowiedź niesie też `meta_override` (echo pól). Testy:
  `test_session_meta_override_applies_and_clears`, `test_set_session_timeline_with_meta_override`.
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
- **Wykrywanie ID z sygnału tonowego (v0.28.0, kody tymczasowe od v0.65.0):**
  `POST /api/jobs/{id}/detect-id` woła `pipeline.detect_id` (patrz sekcja
  o `audio_sync.decode_id_tone` wyżej — timer odtwarza marker 5000 Hz + kanał + 4 cyfry
  + cyfrę kontrolną, tony 5200–7000 Hz; protokół v2 od v0.33.0, v3 od v0.65.0)
  i zwraca `{id: int|None, temp_id: str|None, code: str, info: str}` — `id` jest już
  ID WPISU w bazie (dla kanału 1–9 po wyszukaniu `temp_id` w kalkulatorze), `code` to
  postać dla człowieka (`3-0147`), a `info` niesie powód, gdy ID nie da się ustalić
  (brak wpisu, kilku kandydatów z tym samym kodem, błąd/stare API). Brak sygnału ORAZ
  brak rozstrzygnięcia to NIE błąd (jak `/analyze` dla T0), frontend prosi o ręczne ID —
  `app.js` pokazuje wtedy `data.info` zamiast ogólnego komunikatu, a po sukcesie dopisuje
  „(kod tymczasowy 3-0147)". Guard identyczny jak `/analyze`: 409 gdy zadanie `QUEUED`/`RENDERING`.
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

- **Wyjście FFmpeg czytaj ZAWSZE z `encoding="utf-8", errors="replace"` (v0.41.0):**
  FFmpeg pisze stdout/stderr w UTF-8, a `text=True` bez `encoding` dekoduje wg locale
  (Windows: cp1250). Bajt 0x81 z UTF-8 „Ł" jest w cp1250 NIEZDEFINIOWANY →
  `UnicodeDecodeError` w pętli czytającej `_run_with_progress`. Realny przypadek: sesje
  z torem „ŁUKASZ W." — FFmpeg echem wypisuje metadane wyjścia (`-metadata comment=`
  z `nazwa_toru`, v0.39.0), render padał ~2–6 s po starcie; małe „ł"/„ń" (0x82/0x84)
  przechodziły, więc wcześniejsze sesje niczego nie ujawniły. Podwójnie zdradliwe:
  wyjątek Pythona (nie FFmpeg) wylatywał PRZED logowaniem wyniku — w `render_log.txt`
  brak linii `OK`/`FAIL` dla tych prób, a proces FFmpeg zostawał osierocony. Od v0.41.0:
  wszystkie `subprocess.run/Popen` czytające FFmpeg mają jawne utf-8 (`ffmpeg._run`,
  `render._run_with_progress`, `_drawtext_usable`, `_resolve_nvenc_args`, paleta GIF),
  a `_run_with_progress` łapie wyjątki Pythona w pętli → `proc.kill()` + wpis
  `FAIL (python): …` do logu (testy: `test_run_with_progress_reads_stderr_as_utf8`,
  `test_run_with_progress_logs_python_exception_and_kills_proc`).
- **Kolejka: powód błędu na zadaniu (v0.41.0):** `RenderJob.error` — `_on_job_failed`
  zapisuje komunikat z `RenderWorker.failed` NA zadaniu przed `_mark` (handler statusu
  i autozapis muszą go już widzieć), `_job_to_dict`/`_job_from_dict` serializują pole
  (trafia do `render_queue.json` w AppData — plik sam mówi, czemu zadanie padło),
  wiersz kolejki pokazuje pełny komunikat w tooltipie (`JobRowWidget.set_error`).
  Czyszczenie w `_start_job` (nowa próba), tooltip zdejmowany przy `RUNNING`.

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
- **Wideo pionowe z telefonu (v0.65.1):** plik Pixela `PXL_…mp4` jest zakodowany 1920×1080 z
  metadanym obrotem (`displaymatrix: rotation of -90.00 degrees`, starsze: tag `rotate`), a FFmpeg
  AUTOROTUJE przy dekodowaniu (render, `extract_frame`, player) → kadr wyjściowy to 1080×1920.
  `probe` zwracał wymiary kodowane, więc nakładki liczono dla poziomego kadru i plansza START
  wychodziła poza obraz. Fix: `ffmpeg._rotated_size` (±90°/270° zamienia W↔H) w obu ścieżkach
  probe (ffprobe: `stream_side_data=rotation`/`stream_tags=rotate`; regexy `_DISPLAYMATRIX_RE`/
  `_ROTATE_TAG_RE`). Do tego `overlay.ref_dim(video_size) = min(w, h)` jako wymiar odniesienia
  czcionek/paneli (dla poziomego = wysokość jak dotąd → snapshoty bez zmian; dla pionowego =
  szerokość) we WSZYSTKICH `_base_font_size(...)` w overlay.py i render.py, plus bezpiecznik:
  plansza START zmniejsza czcionkę, aż zmieści się w 92 % szerokości kadru. Zweryfikowane
  `preview.render_still` na realnym PXL (START, panel strzału, zegar — w kadrze).
- Snapshoty (`tests/snapshots/*.png`) zależą od bundlowanego fontu DejaVu i wersji Pillow;
  porównanie ma tolerancję `MAX_MEAN_DIFF`. Przy zmianie fontu/renderu — regeneruj.
- Detekcja onsetów jest prosta (RMS); przy hałaśliwym audio użyj ręcznej korekty T0 w GUI.
- **Podgląd vs. render — rozbieżność metadanych:** `_update_preview` używa `self.session`
  (ustawionego przez `_fetch_id`, zawiera `nazwa_toru`/`uczestnik`). `_build_session()` w
  trybie tekstowym musi zawsze wywołać `replace(self.session, shots=shots)` gdy `self.session`
  nie jest `None` — inaczej render dostaje `Session` bez metadanych a podgląd je pokazuje.
  Zasada: podgląd i render muszą korzystać z tej samej sesji (te same metadane).

## Promocja / domeny (decyzja z 2026-09-12)

- **Jedna marka na wszystkie rynki: `ShotHUD`** → `shothud.com` (główna domena
  one-pagera) oraz `shothud.pifpaf.fun` (subdomena w istniejącym ekosystemie, obok
  `timer.pifpaf.fun` i `piro-kalkulator.pifpaf.fun`). Osobnej domeny dla rynku polskiego
  NIE MA (świadoma decyzja — patrz `splity.pl` niżej). Dlaczego ShotHUD: HUD = heads-up
  display = dokładnie to, czym jest nakładka; krótkie, zrozumiałe bez tłumaczenia; `.com`
  był wolny (rzadkość dla sensownej angielskiej nazwy); brak istniejącego produktu ani
  znaku towarowego pod tą nazwą (w sieci tylko mody do gier). Wolne były też
  `shothud.{pl,video,io,app,net,tv,fun,dev,tools,eu}`.
- **`splity.pl` — rozważana jako domena PL, ODRZUCONA tego samego dnia** (najpierw
  „bierzemy na pewno", potem rezygnacja — decyzja użytkownika, bez podanego powodu). Była
  WOLNA w rejestrze NASK (sprawdzone trzema drogami: RDAP, WHOIS `whois.dns.pl:43`, strefa
  .pl przez Google/Cloudflare DNS). Gdyby kiedyś zaszła potrzeba osobnej domeny PL,
  `shothud.pl` też było wolne w dniu sprawdzenia.
- **PUŁAPKA przy sprawdzaniu domen w przeglądarce:** lokalny resolver (Windows → WSL)
  mapuje KAŻDĄ nieistniejącą nazwę na IP z sieci home.pl (188.128.234.120), więc
  przeglądarka pokazuje stronę (301 → 403) i wolna domena WYGLĄDA na zajętą (tak było ze
  splity.pl). Status domen sprawdzać w rejestrze, nie w przeglądarce.
- **Odrzucone i dlaczego:** `pirooverlay.*` (wolne wszędzie, ale czysto techniczne —
  „nazwa aplikacji", nie marka); `splits.video`/`splity.video` (dla zagranicy chciano
  inne słowo niż „splity"); `makeready` (znak MAKEREADY™ na makeready.com);
  `stagereplay` (działający produkt); `overshot` (firma); `timerlay.com` (spekulant,
  „for sale"); `afterthebeep` (najlepsza historia, ale .com/.app/.net/.tv zajęte);
  `splitstamp`/`beepsplit` (wolne wszędzie, zapas gdyby ShotHUD nie wypalił).
- **Konkurent** do obejrzenia przed pisaniem tekstów na one-pager: „Shooting Cut"
  (App Store) — edytor wideo dla USPSA/IPSC/IDPA/3-Gun.
- **Jak sprawdzać dostępność hurtowo (bez `whois` w systemie):** RDAP — mapa serwerów
  per TLD `https://data.iana.org/rdap/dns.json`; `.com`/`.net`
  `rdap.verisign.com/{com,net}/v1/domain/X`, `.pl` `rdap.dns.pl/domain/X`, `.app`/`.dev`
  `pubapi.registry.google/rdap/domain/X`, `.video`/`.io`/`.tools` (Identity Digital)
  `rdap.identitydigital.services/rdap/domain/X`, `.fun` `rdap.radix.host/rdap/domain/X`;
  HTTP 404 = wolna, 200 = zajęta. `.eu` bez RDAP — WHOIS `whois.eu:43`
  („Status: AVAILABLE"). `.co` nie odpowiadał (niesprawdzone). RDAP NIE pokazuje ceny
  premium (krótkie słowa ze słownika w .video/.tv/.app bywają wielokrotnie droższe, także
  przy odnowieniu) — cenę sprawdzać w koszyku rejestratora. `.app`/`.dev` wymuszają HTTPS
  (HSTS preload), `.eu` wymaga siedziby/obywatelstwa w UE.
