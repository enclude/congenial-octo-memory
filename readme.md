# Piro Overlay

> **Autor:** Jarosław Zjawiński — [kontakt@zjawa.it](mailto:kontakt@zjawa.it) / [szkolenia@pifpaf.fun](mailto:szkolenia@pifpaf.fun)
> **Licencja:** [GPL v3](LICENSE) — dystrybucja i modyfikacje wymagają podania oryginalnego autora oraz udostępnienia kodu źródłowego.
> **Wersja:** 0.4.0

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
   ręcznej korekty.
3. Każdy panel pojawia się o `T0 + czas_strzału`; render to **jeden przebieg FFmpeg**
   (szybko, audio zachowane).

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
```

Bez `--t0` aplikacja sama wykrywa kotwicę w audio (jeśli podasz `--trim-start/--trim-end`,
detekcja szuka tylko w tym oknie). Bez `-o` plik zapisuje się obok źródła z sufiksem
`_PiRoOverlay`.

## Przyśpieszanie

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
czas trwania planszy „START" oraz język (PL/EN). Podgląd aktualizuje się na żywo.

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
