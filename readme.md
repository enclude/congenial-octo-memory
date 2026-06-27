# Piro Overlay

> **Autor:** Jarosław Zjawiński — [kontakt@zjawa.it](mailto:kontakt@zjawa.it) / [szkolenia@pifpaf.fun](mailto:szkolenia@pifpaf.fun)
> **Licencja:** [GPL v3](LICENSE) — dystrybucja i modyfikacje wymagają podania oryginalnego autora oraz udostępnienia kodu źródłowego.
> **Wersja:** 0.14.0

Aplikacja desktop (Python + PySide6), która na podstawie **wideo ze strzelania** oraz
**osi czasu strzałów** nakłada na film informacyjną grafikę (numer strzału, czas od startu,
split, „x z yy") i po ostatnim strzale panel podsumowania (czas bazowy, suma kar, czas
końcowy, hit factor), a następnie renderuje gotowy plik wideo z wypaloną nakładką.

Oś czasu można wkleić ręcznie **albo** pobrać po **ID** z API kalkulatora Piro
(`piro-kalkulator.pifpaf.fun`) — oś czasu znajduje się tam w polu `opis`, a pozostałe pola
wzbogacają nagłówek i podsumowanie.

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

- **Przeciąganie pozycji w podglądzie:** włącz „✥ Edytuj pozycje (przeciąganie)" nad
  podglądem i przeciągnij **panel strzału** lub **zegar** myszą, by ustawić ich pozycję
  (aktualizuje offsety na żywo). W tym trybie podgląd pokazuje panel strzału także przy
  kotwicy „Sygnał startu". Offsety przeliczane są na rozdzielczość wyjściową, więc podgląd
  odpowiada renderowi.

- **Płynący czas od T0:** opcjonalny zegar **„T+x.xs"** liczony od sygnału startu i widoczny
  już od STARTU (jeszcze przed pierwszym strzałem). Włącz checkboxem w sekcji wyglądu.
  **Pozycję** wybierasz w „Pozycja zegara": *Nad nakładką (auto)* albo dowolny z 6 rogów
  (wtedy działa „Offset zegara X/Y"). Przy pełnym FFmpeg zegar tyka płynnie z dokładnością
  do **dziesiątych sekundy**; na okrojonej binarce (bez filtra `drawtext`) działa fallback
  co 1 s — funkcja jest dostępna zawsze.
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

Render można **przerwać** przyciskiem „Zatrzymaj" (np. po pomyłce) — ubija proces FFmpeg
i usuwa niedokończony plik. Można też kolejkować wiele zadań („Dodaj do kolejki" → „Kolejka").

## Synchronizacja po API — „Pobierz" vs „Pobierz i przytnij"

Przy źródle **ID (API)** są dwa przyciski:

- **Pobierz** — pobiera samą oś czasu i metadane (nie rusza przycięcia).
- **Pobierz i przytnij** — pobiera dane, ustala T0 (używa wykrytego przy imporcie, a gdy
  brak — wykrywa bzyczek) i przycina film: **5 s przed T0 → ostatni strzał + 5 s**.

Po samym **wczytaniu pliku** aplikacja również od razu wykrywa T0 i ustawia przycięcie
(5 s przed T0 → maks. 75 s po T0).

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

## Architektura

Logika domenowa jest oddzielona od UI — moduły `parser`, `api`, `audio_sync`, `overlay`,
`render`, `ffmpeg` nie zależą od PySide6. Dzięki temu przyszły wariant **WWW** może dodać
tylko backend + frontend i reużyć te moduły. Szczegóły w `CLAUDE.md`.

## Licencja

Copyright © 2024–2026 Jarosław Zjawiński ([kontakt@zjawa.it](mailto:kontakt@zjawa.it) / [szkolenia@pifpaf.fun](mailto:szkolenia@pifpaf.fun))

Projekt jest udostępniony na licencji **GNU General Public License v3.0 lub nowszej** — szczegóły w pliku [LICENSE](LICENSE).

W skrócie: możesz używać, modyfikować i dystrybuować aplikację, ale **musisz**:
- zachować informację o oryginalnym autorze,
- udostępnić kod źródłowy modyfikacji na tej samej licencji GPL v3.
