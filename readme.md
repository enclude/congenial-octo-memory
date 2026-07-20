# Piro Overlay

> **Autor:** Jarosław Zjawiński — [kontakt@zjawa.it](mailto:kontakt@zjawa.it) / [szkolenia@pifpaf.fun](mailto:szkolenia@pifpaf.fun)
> **Licencja:** [GPL v3](LICENSE) — dystrybucja i modyfikacje wymagają podania oryginalnego autora oraz udostępnienia kodu źródłowego.
> **Wersja:** 0.37.0
> **Dokumentacja wersji web (Docker/deploy):** [readme_web.md](readme_web.md)

Aplikacja desktop (Python + PySide6), która na podstawie **wideo ze strzelania** oraz
**osi czasu strzałów** nakłada na film informacyjną grafikę (numer strzału, czas od startu,
split, „x z yy") i po ostatnim strzale panel podsumowania (czas bazowy, suma kar, czas
końcowy, hit factor), a następnie renderuje gotowy plik wideo z wypaloną nakładką.

Oś czasu można wkleić ręcznie **albo** pobrać po **ID** z API kalkulatora Piro
(`piro-kalkulator.pifpaf.fun`) — oś czasu znajduje się tam w polu `opis`, a pozostałe pola
wzbogacają nagłówek i podsumowanie.

## Zrzuty ekranu

### Główne okno (po wczytaniu wideo)

Lewy panel — wejście (wideo, oś czasu/ID), synchronizacja i przycięcie oraz pełna
konfiguracja wyglądu nakładki. Po prawej podgląd na żywo (z planszą START) i waveforma
z zaznaczonymi T0 oraz oknem przycięcia.

![Główne okno aplikacji po załadowaniu wideo](pictures/02%20widok%20aplikacji%20po%20załadowaniu%20wideo.png)

### Nakładka z płynącym czasem

Panel strzału (numer, czas od startu, split, „x z yy") oraz opcjonalny zegar „T+x.xs"
liczony od sygnału startu.

![Widok nakładki z płynącym czasem](pictures/01%20widok%20nakładki%20z%20czasem.png)

### Nakładka „lista strzałów" + metadane (od v0.37.0)

Alternatywny styl panelu: ostatnie strzały jako lista (numer | czas | split) — nowy strzał
pojawia się na dole (wyróżniony, z postępem „x/yy"), starsze przesuwają się w górę
i stopniowo gasną. Do tego osobna, niezależnie pozycjonowana nakładka z nazwą toru
i uczestnikiem. Obie nakładki można przeciągać myszą w podglądzie (tryb edycji pozycji).

![Widok nakładki „lista strzałów" z metadanymi toru i uczestnika](pictures/04%20widok%20nakładki%20lista%20strzałów.png)

### Przetwarzanie wsadowe

Okno „Wsadowo…" — wiele plików naraz w trybie auto + ID, ze wspólnymi ustawieniami
(katalog, sufiks, format, GPU, nakładka, zegar) i eksportem/importem listy przez schowek.

![Widok wsadowego przetwarzania danych](pictures/03%20widok%20wsadowego%20przetwarzania%20danych.png)

## Jak to działa

1. Wybierasz plik wideo i podajesz oś czasu (tekst lub ID).
2. Aplikacja wykrywa w audio **sygnał startu / pierwszy strzał** (T0) — z możliwością
   ręcznej korekty na waveformie.
3. Każdy panel pojawia się o `T0 + czas_strzału`; render to **jeden przebieg FFmpeg**
   (szybko, audio zachowane).

### Wykrywanie T0 (kotwicy)

W sekcji „Synchronizacja i przycięcie" są trzy przyciski:

- **Wykryj kotwicę** — pierwszy wyraźny onset w zaznaczonym fragmencie (uniwersalne).
- **Następna proponowana kotwica** — przeskakuje do kolejnego wykrytego onsetu.
- **Wykryj sygnał startu** — detekcja bzyczka shot-timera w paśmie **2000–4500 Hz**
  rozpoznawanego po **tonalności** (koncentracja energii w paśmie ≥ 0.7) i **ciągłości**
  (≥150 ms czystego tonu), z fallbackiem po stabilności częstotliwości. Odporne na strzały
  (szerokopasmowe, krótkie) i szum — dopracowane pod nagrania DJI Osmo. Ustawia typ kotwicy
  na „Sygnał startu" i wpisuje wykryty bzyczek jako T0.

Można też kliknąć bezpośrednio na waveformie, by ręcznie ustawić kotwicę.

**Automatyka przycięcia:**

- **Po wczytaniu pliku** aplikacja od razu wykrywa T0 (bzyczek) i ustawia przycięcie na
  **5 s przed T0 → maks. 75 s po T0**.
- Przycisk **„Pobierz i przytnij"** (obok „Pobierz") pobiera dane z API, wykrywa T0 i
  przycina film na **5 s przed T0 → ostatni strzał + 5 s**. Zwykły **„Pobierz"** tylko
  pobiera oś czasu i metadane (bez zmiany przycięcia).

Format osi czasu:

```
1: 2.81s | 2: 4.63s (+1.82s) | 3: 6.28s (+1.65s) | ...
```

`czas` — czas od sygnału startu; `(+split)` — przyrost względem poprzedniego strzału
(brak przy pierwszym strzale).

## Wymagania

- Python 3.10+
- FFmpeg — **nie trzeba** instalować osobno; dostarcza go pakiet `imageio-ffmpeg`.

## Instalacja (dev)

```bash
python -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Uruchomienie

GUI:

```bash
piro-overlay-gui
```

CLI:

```bash
# z tekstu
piro-overlay --video in.mp4 --timeline "1: 2.81s | 2: 4.63s (+1.82s)" --t0 3.2 -o out.mp4

# z API po ID (oś czasu z pola opis + metadane)
piro-overlay --video in.mp4 --id 5 -o out.mp4

# wybór typu kotwicy i języka napisów
piro-overlay --video in.mp4 --id 5 --anchor first_shot --lang en -o out.mp4

# auto-przycięcie wyniku (od ~T0 do ostatniego strzału + margines) i GPU
piro-overlay --video in.mp4 --id 5 --auto-trim --tail 5 --encoder gpu

# ręczne przycięcie fragmentu źródła
piro-overlay --video in.mp4 --id 5 --trim-start 12 --trim-end 80

# AUTO: wykryj T0 (bzyczek) i przytnij wg strzałów, z płynącym czasem w rogu
piro-overlay --video in.mp4 --id 5 --auto --clock --clock-position top-right -o out.mp4

# AUTO bez nakładki — samo przycięcie 5 s przed T0 → 75 s po T0
piro-overlay --video in.mp4 --auto --auto-window 75 --no-overlay -o out.mp4
```

### Tryb bezgłowy z `.exe`

Ten sam `PiroOverlay.exe` po podaniu argumentów działa jak CLI (bez GUI) — wygodne do
automatyzacji/skryptów:

```powershell
PiroOverlay.exe --video in.mp4 --id 5 --auto --clock -o out.mp4
```

Najważniejsze flagi: `--auto` (wykryj T0=bzyczek + auto-przytnij), `--auto-window N`
(stałe okno N s po T0 zamiast „ostatni strzał + margines”), `--lead-in N` (s przed T0,
domyślnie 5), `--no-overlay` (tylko przycięcie), `--clock` + `--clock-position`
(`auto`/rogi) + `--clock-offset-x/y`. Pełna lista: `PiroOverlay.exe --help`.

Bez `--t0` aplikacja sama wykrywa kotwicę w audio (jeśli podasz `--trim-start/--trim-end`,
detekcja szuka tylko w tym oknie). Bez `-o` plik zapisuje się obok źródła z sufiksem
`_PiRoOverlay`.

**Generowanie komendy z GUI:** w sekcji „Wyjście” przycisk **„Pokaż komendę CLI”** buduje
równoważne wywołanie bezgłowe na podstawie aktualnych ustawień (wideo, źródło osi, T0,
kotwica, przycięcie, język, enkoder, zegar, tryb „bez nakładki”) i pozwala je skopiować do
schowka. Uwaga: szczegóły wyglądu nakładki (kolory, skala, pozycja panelu, offsety, plansza
START) nie mają odpowiedników w CLI i są pomijane.

## Przyśpieszanie

- **Proxy LRF (DJI Osmo):** kamery DJI nagrywają obok każdego MP4 plik `.LRF` — to ta
  sama treść w niskiej rozdzielczości (~480p). Aplikacja automatycznie go wykrywa i używa
  do analizy audio (detekcja T0, waveforma), co **znacznie przyspiesza wczytywanie** przy
  dużych plikach 4K/60fps. Render końcowy zawsze odbywa się z oryginalnego MP4.
  Żadnej konfiguracji — wystarczy mieć plik `.LRF` obok `.MP4`.

- **Render na GPU (NVENC):** w GUI zaznacz „Akceleracja GPU", w CLI `--encoder gpu/auto`.
  Status NVENC widać w GUI pod tym polem; po renderze komunikat pokazuje faktyczny enkoder.
  Gdy GPU zawiedzie, render samoczynnie wraca do CPU (x264).
- **Podgląd** renderowany jest w obniżonej rozdzielczości — lżejszy przy dużych plikach.

### Włączenie GPU (NVENC) na Windows

FFmpeg dołączony z `imageio-ffmpeg` **nie ma** NVENC. Aby włączyć GPU, wybierz jedną opcję:

1. **Zainstaluj pełny FFmpeg w systemie** (najprościej) — aplikacja sama go wykryje:
   ```powershell
   winget install Gyan.FFmpeg
   ```
   (lub build z gyan.dev / BtbN dodany do PATH).
2. **Wbuduj FFmpeg w `.exe`** — przy budowaniu użyj flagi, która pobierze pełny FFmpeg z NVENC:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\build.ps1 -WithFfmpeg
   ```

Kolejność wyboru binarki: zmienna `PIRO_FFMPEG` → wbudowany pełny FFmpeg (`assets/bin`) →
systemowy z NVENC → `imageio-ffmpeg` (CPU).

## Wygląd nakładki

W GUI konfigurowalne: rozmiar (skala), pozycja (róg + offset X/Y), tło (kolor +
przezroczystość), obramowanie (kolor/grubość/wł.-wył.), kolor napisów (tekst + akcent),
czas trwania planszy „START" oraz język (PL/EN). Podgląd aktualizuje się na żywo, a
**Ctrl+klik na waveformie** pokazuje klatkę wideo z nałożonym podglądem nakładki.

- **Styl panelu (od v0.37.0):** *Klasyczny* (pojedynczy panel „Strzał x z yy" z metadanymi)
  albo *Lista ostatnich strzałów* — ostatnie strzały jako wiersze (numer | czas | split),
  nowy strzał pojawia się na dole (wyróżniony), starsze przesuwają się w górę i gasną.
  Liczba wierszy do wyboru (2–10, domyślnie 5); aktywny wiersz może pokazywać numer jako
  postęp **„x/yy"** (np. „6/9"). Panel listy ma stały rozmiar i stałą pozycję aktywnego
  wiersza — nic nie skacze między strzałami.
- **Nakładka toru/uczestnika (od v0.37.0):** osobna nakładka z nazwą toru i uczestnikiem
  („Jaro — 9 strzałów"), widoczna od T0 do końca filmu, z własną pozycją (róg + offset).
  Przydatna zwłaszcza w trybie listy, który nie pokazuje metadanych w panelu strzału.
- **Przeciąganie pozycji w podglądzie:** włącz „✥ Edytuj pozycje (przeciąganie)" nad
  podglądem i przeciągnij **panel strzału**, **nakładkę metadanych** lub **zegar** myszą,
  by ustawić ich pozycję (aktualizuje offsety na żywo). W tym trybie podgląd pokazuje
  panel strzału także przy kotwicy „Sygnał startu". Offsety przeliczane są na
  rozdzielczość wyjściową, więc podgląd odpowiada renderowi.

- **Płynący czas od T0:** opcjonalny zegar **„T+x.xs"** liczony od sygnału startu i widoczny
  już od STARTU (jeszcze przed pierwszym strzałem). Włącz checkboxem w sekcji wyglądu.
  **Pozycję** wybierasz w „Pozycja zegara": *Nad nakładką (auto)* albo dowolny z 6 rogów
  (wtedy działa „Offset zegara X/Y"). Zegar tyka z dokładnością do **dziesiątych sekundy**
  na **każdej** binarce FFmpeg: przy pełnym FFmpeg przez filtr `drawtext`, a na okrojonej
  binarce (np. wbudowany `imageio-ffmpeg` bez `drawtext`) przez sekwencję klatek PNG
  nakładaną jednym przebiegiem — efekt ten sam (dziesiąte sekundy), bez różnicy dla użytkownika.
  Ruch zegara jest **płynny** (kadencja klatek dopasowana do FPS wideo, więc na nagraniach
  29.97/59.94 fps nie „zacina się"), a po **ostatnim strzale zegar zamarza** — pokazuje
  finalny czas i nie biegnie dalej do końca filmu.
- **Zapisz/wczytaj presety:** ustawienia wyglądu można eksportować i wczytywać z pliku
  **JSON** (przyciski w sekcji wyglądu).
- **Auto-zapis:** ostatnio użyte ustawienia wyglądu oraz katalog zapisują się automatycznie
  w `AppData`, więc przy kolejnym uruchomieniu są przywracane.
- **Pamięć ustawień per-plik:** gdy dany plik zostanie **wyrenderowany** lub **dodany do
  kolejki**, jego komplet parametrów (wygląd nakładki, źródło osi i ID, T0, kotwica,
  przycięcie, margines, język, enkoder/GPU, format, tryb „bez nakładki”, ścieżka wyjścia)
  zapisuje się w `AppData` pod kluczem ścieżki pliku. Po ponownym otwarciu **tego samego
  pliku** ustawienia wczytują się automatycznie (zamiast auto-detekcji T0), a w pasku stanu
  pojawia się „Wczytano zapisane ustawienia dla tego pliku”.

## Format wyjściowy

W sekcji „Wyjście" wybierasz format renderu:

- **MP4** (H.264, domyślny) — z dźwiękiem, do publikacji.
- **WebM** (VP9) — lekki format webowy.
- **GIF** — zapętlona animacja bez dźwięku (np. do social media).

## Przyciski renderowania

Pod paskiem postępu znajdują się przyciski (w kilku wierszach):

- **Renderuj** — uruchamia render bieżącego pliku.
- **Zatrzymaj** — przerywa trwający render: natychmiast ubija proces FFmpeg i usuwa
  niedokończony (uszkodzony) plik wyjściowy.
- **Dodaj do kolejki** — dodaje bieżące ustawienia jako zadanie do kolejki renderów
  (otwiera okno kolejki).
- **Kolejka** — otwiera okno kolejki renderów (patrz niżej).
- **Wsadowo…** — otwiera okno przetwarzania wsadowego wielu plików (patrz niżej).
- **Otwórz folder z wynikiem** — pojawia się **dopiero po udanym renderze**; otwiera
  folder z plikiem (na Windows zaznacza plik w eksploratorze).

## Kolejka renderów

Okno **„Kolejka"** renderuje wiele zadań po kolei (jeden render naraz), pokazując dla
każdego liczbowy **% postępu**, a w pasku stanu — postęp łączny („Render 3/20 · plik ·
bieżący 47% · łącznie 31%"). Przyciski:

- **Start kolejki** — uruchamia kolejkę; **ponawia też zadania nieudane** (FAILED → ponów),
  więc po błędzie/awarii wystarczy kliknąć Start, by spróbować ponownie.
- **Zatrzymaj** — przerywa bieżący render i **pauzuje** kolejkę; przerwane zadanie wraca do
  stanu „oczekuje", a „Start kolejki" wznawia od niego.
- **Wyczyść zakończone** — usuwa z listy zadania ukończone i nieudane.
- **Zapisz kolejkę / Wczytaj kolejkę** — zapisuje/odczytuje listę zadań w `AppData`
  (`render_queue.json`). Służy do **odzysku po awarii**: stan zapisuje się też automatycznie
  przy każdej zmianie, a **zadania ukończone pomyślnie nie są zapisywane** (w pliku zostają
  tylko te do wykonania). Po ponownym otwarciu kliknij „Wczytaj kolejkę", by wznowić.

## Przetwarzanie wsadowe (Wsadowo…)

Okno **„Wsadowo…"** pozwala przerobić **wiele plików naraz** w trybie **auto + ID**
(oś czasu z API po ID, T0 = wykryty bzyczek, automatyczne przycięcie). Krok po kroku:

1. **Dodaj pliki…** — wybierasz wiele plików wideo; każdy trafia do listy.
2. Dla każdego wiersza podajesz **ID** z API (pole obok nazwy pliku).
3. **Przygotuj wszystkie** — w tle dla każdego pliku: pobiera sesję z API, wykrywa T0
   (bzyczek) i liczy przycięcie (5 s przed T0 → ostatni strzał + 5 s). Status wiersza
   pokazuje wynik (T0, okno przycięcia) lub błąd.
4. **Wyślij gotowe do kolejki** — gotowe wiersze stają się zadaniami w zwykłej kolejce
   renderów i renderują się po kolei.

Ustawienia **wspólne dla całej partii**: katalog docelowy, **sufiks nazwy** pliku
wyjściowego, format (MP4/WebM/GIF), GPU, nakładka wł./wył. oraz płynący zegar. Wygląd
nakładki jest kopiowany z głównego okna (ustaw go tam przed otwarciem).

- **Dodaj informacje o uczestniku** — gdy zaznaczone, do nazwy pliku **po sufiksie**
  dopisywane jest **ID sesji** oraz **nazwa uczestnika** (np.
  `klip_PiRoOverlay_163_Jaroslaw_Zjawinski.mp4`). Znaki diakrytyczne są sanityzowane do
  ASCII (np. `Jarosław → Jaroslaw`), a spacje zamieniane na `_`, by uniknąć problemów z
  nazwami plików w różnych systemach.

Dodatkowe przyciski:

- **▶** (przy wierszu) — otwiera **plik źródłowy** w domyślnym odtwarzaczu (podgląd).
- **Usuń** (przy wierszu) / **Wyczyść wszystko** — usuwa pojedynczy plik / całą listę.
- **Eksport → schowek** — kopiuje listę do schowka, po jednym pliku w wierszu w formacie
  `<ścieżka>;<ID>`.
- **Import ze schowka** — wkleja listę w tym samym formacie (`<ścieżka>;<ID>` w wierszach);
  dla istniejącej ścieżki aktualizuje ID, nową dodaje jako nowy wiersz.

## Drobiazgi GUI

- **Kółko myszy nie zmienia wartości pól** — przewijanie nad polami liczbowymi i listami
  rozwijanymi nie zmienia ich wartości (częsty przypadkowy błąd); przewija się tylko strona.
- **Diagnostyka NVENC** — przycisk w sekcji „Wyjście" pokazuje status NVENC, używaną binarkę
  FFmpeg i — gdy GPU nie działa — powód oraz wskazówki (np. wymuszenie karty NVIDIA dla aplikacji).
- **Pokaż komendę CLI** — buduje równoważne wywołanie bezgłowe z aktualnych ustawień (patrz
  wyżej, „Generowanie komendy z GUI").

## Diagnostyka (logi w AppData)

Gdyby render się nie udał albo aplikacja zachowała się niestabilnie, w katalogu
`AppData\PiroOverlay` (Windows) / `~/.config/PiroOverlay` (Linux) powstają pliki pomocne
przy zgłaszaniu problemu:

- **`render_log.txt`** — dokładna komenda FFmpeg każdego renderu oraz wynik (`OK` / `FAIL`
  z ogonem błędu / `CANCELLED`). Najszybszy sposób, by zobaczyć, czy i dlaczego FFmpeg zawiódł.
- **`crash_log.txt`** — ślad twardego crashu (zrzut stosów wątków) oraz nieobsłużone wyjątki.

## Synchronizacja po API — „Pobierz" vs „Pobierz i przytnij"

Przy źródle **ID (API)** są dwa przyciski:

- **Pobierz** — pobiera samą oś czasu i metadane (nie rusza przycięcia).
- **Pobierz i przytnij** — pobiera dane, ustala T0 (używa wykrytego przy imporcie, a gdy
  brak — wykrywa bzyczek) i przycina film: **5 s przed T0 → ostatni strzał + 5 s**.

Po samym **wczytaniu pliku** aplikacja również od razu wykrywa T0 i ustawia przycięcie
(5 s przed T0 → maks. 75 s po T0).

### Wykryj ID z audio

Przycisk **„Wykryj ID z audio"** (pod polem ID) odczytuje ID sesji prosto z nagrania —
przydatne, gdy timer (np. [timer.pifpaf.fun](https://timer.pifpaf.fun)) po zapisaniu
sesji w bazie kalkulatora odtworzył sygnał tonowy ID, a mikrofon kamery go nagrał.
Rozpoznaje marker 5000 Hz + 4 cyfry i cyfrę kontrolną (5200–7000 Hz), wpisuje wykryte ID do pola —
kliknij potem „Pobierz" jak zwykle. Gdy nie znajdzie sygnału (timer go nie odtworzył
albo mikrofon nie nagrał), pokazuje komunikat i nic nie zmienia — ID wpisujesz ręcznie.
Analizuje zawsze oryginalny plik wideo (nie proxy `.LRF`).

## Testy

```bash
PYTHONPATH=src pytest
# regeneracja snapshotów paneli:
PIRO_UPDATE_SNAPSHOTS=1 PYTHONPATH=src pytest tests/test_overlay.py
```

## Build .exe (Windows)

PyInstaller buduje samodzielny plik (bez Pythona i FFmpeg u użytkownika). **Build trzeba
uruchomić na Windows** — PyInstaller nie robi cross-compile. Dokładna, sprawdzona komenda
jest w [`CLAUDE.md`](CLAUDE.md).

Najprościej skryptem (PowerShell, z katalogu projektu):

```powershell
.\build.ps1            # lub: .\build.ps1 -Clean  (czyści build/dist/venv)
# wynik: dist\PiroOverlay.exe
```

Ręcznie:

```powershell
pip install pyinstaller
pyinstaller build_exe.spec
# wynik: dist\PiroOverlay.exe
```

**W chmurze (GitHub Actions):** workflow `.github/workflows/build.yml` uruchamia testy na
Linuksie i buduje `.exe` na `windows-latest`. Plik jest dostępny jako artefakt każdego
przebiegu, a po wypchnięciu tagu `v*` (np. `v0.1.0`) zostaje automatycznie dołączony do
GitHub Release. Można też odpalić ręcznie z zakładki **Actions → Build → Run workflow**.

## Wersja webowa

Istnieje też **wersja webowa** (Docker na VPS, publiczna): upload wideo w przeglądarce →
oś czasu (ID lub tekst) → auto-detekcja T0 → podgląd z korektą → render → pobranie.
Reużywa te same moduły domenowe — `.exe` i web działają równolegle, z jednego repo. Dostępny
jest też przełącznik **„Bez nakładki"** — wykrywa T0 i przycina wideo bez wypalania grafiki
o strzałach (oś czasu jest wtedy opcjonalna, ale nadal poprawia auto-przycięcie, jeśli ją podasz).

**Pełna dokumentacja: [readme_web.md](readme_web.md)** (uruchomienie, Docker,
konfiguracja `PIRO_WEB_*`, ustawienia reverse proxy, API).

## Architektura

Logika domenowa jest oddzielona od UI — moduły `parser`, `api`, `audio_sync`, `overlay`,
`render`, `ffmpeg`, `pipeline`, `preview` nie zależą od PySide6. Warstwy wejścia to
`gui.py` (PySide6), `cli.py` i `web/` (FastAPI) — wszystkie reużywają tę samą domenę.
Szczegóły w `CLAUDE.md`.

## Licencja

Copyright © 2024–2026 Jarosław Zjawiński ([kontakt@zjawa.it](mailto:kontakt@zjawa.it) / [szkolenia@pifpaf.fun](mailto:szkolenia@pifpaf.fun))

Projekt jest udostępniony na licencji **GNU General Public License v3.0 lub nowszej** — szczegóły w pliku [LICENSE](LICENSE).

W skrócie: możesz używać, modyfikować i dystrybuować aplikację, ale **musisz**:
- zachować informację o oryginalnym autorze,
- udostępnić kod źródłowy modyfikacji na tej samej licencji GPL v3.
