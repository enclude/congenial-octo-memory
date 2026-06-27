# AGENTS.md — wytyczne dla agentów AI

Plik obowiązkowy dla każdego agenta (Claude Code, Codex, Copilot, Cursor itp.) pracującego
w tym repozytorium. Uzupełnia `CLAUDE.md` — najpierw przeczytaj tamten plik.

---

## Przed rozpoczęciem pracy

1. **Przeczytaj `CLAUDE.md`** — zawiera architekturę, mapę modułów, model czasu i zasady wersjonowania.
2. Sprawdź bieżącą wersję: `src/piro_overlay/__init__.py` → `__version__`.
3. Uruchom testy przed zmianami: `PYTHONPATH=src pytest` — upewnij się, że baseline jest zielony.

---

## Zasady pracy z kodem

### Separacja warstw (OBOWIĄZKOWA)

Moduły domenowe **nie importują PySide6**: `models`, `parser`, `api`, `i18n`, `audio_sync`,
`overlay`, `render`, `ffmpeg`, `resources`. Nowa logika trafia do domeny, nie do `gui.py`.

### Styl

- Python 3.10+; używaj `dataclasses` / `dataclassy`, type hints wszędzie.
- Brak komentarzy wyjaśniających *co* kod robi — tylko *dlaczego* (nieoczywiste pułapki).
- Bez abstrakcji na zapas — trzy podobne linie są lepsze niż przedwczesna funkcja pomocnicza.
- Bez obsługi błędów dla scenariuszy niemożliwych; waliduj tylko na granicach systemu.

### Testy

- Nowa funkcja domenowa → test jednostkowy w `tests/`.
- Zmiana `overlay.py` → sprawdź snapshoty; jeśli różnica jest zamierzona, zregeneruj:
  `PIRO_UPDATE_SNAPSHOTS=1 PYTHONPATH=src pytest tests/test_overlay.py`.
- NIE mockuj FFmpeg w testach integracyjnych — przy potrzebie użyj prawdziwego pliku wideo.

---

## Wersjonowanie (OBOWIĄZEK WYKONANIA PRZED ZAKOŃCZENIEM SESJI)

Każda sesja z funkcjonalnymi zmianami lub naprawionymi bugami **musi** kończyć się
bumpem wersji. Jedyne źródło prawdy: `src/piro_overlay/__init__.py`.

| Typ zmiany | Bump |
|---|---|
| Naprawa buga, kosmetyka | PATCH (`+0.0.1`) |
| Nowa funkcja, nowy moduł, zmiana zachowania | MINOR (`+0.1.0`) |
| Przełomowa zmiana architektury lub publicznego API | MAJOR (`+1.0.0`) |

Po zmianie `__init__.py` zaktualizuj **też** `pyproject.toml` (pole `version`).

---

## Wbudowane narzędzia / środowisko

| Narzędzie | Cel | Uwaga |
|---|---|---|
| `ffmpeg.probe` | metadane wideo/audio | parsuje stderr, nie stdout |
| `ffmpeg.find_lrf` | proxy LRF (DJI Osmo) | zwraca `Path \| None` |
| `audio_sync.detect_start` | detekcja sygnału startu (RMS) | przyjmuje okno `[start, end]` |
| `render.render_video` | główny render | jeden przebieg FFmpeg, filtergraph |
| `overlay.render_*` | panele PNG | deterministyczny — nadaje się do snapshotów |

FFmpeg: `PIRO_FFMPEG` env → `assets/bin` (full) → systemowy → imageio-ffmpeg (CPU only).

---

## Czego NIE robić

- Nie dodawaj importów PySide6 do modułów domenowych.
- Nie używaj `git push --force` ani `git reset --hard` bez jawnej zgody użytkownika.
- Nie pomijaj bumpu wersji gdy zmieniałeś funkcjonalność.
- Nie buduj `.exe` podczas pracy — iteruj ze źródła (`python app.py`).
- Nie ignoruj czerwonych testów — napraw je lub wyjaśnij, zanim zaproponujesz merge.
- Nie commituj plików `.env`, kluczy API ani dużych binariów.

---

## Typowy przepływ pracy

```
1. git status / git log — zorientuj się w stanie brancha
2. PYTHONPATH=src pytest — baseline zielony?
3. Implementuj zmiany (domenowe w src/piro_overlay/, testy w tests/)
4. PYTHONPATH=src pytest — testy nadal zielone?
5. Bump wersji w __init__.py + pyproject.toml
6. git diff — przejrzyj wszystko przed commitem
7. git commit (osobny commit na bump jeśli to wygodne)
```
