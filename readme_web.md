# Piro Overlay — wersja webowa

Backend FastAPI + prosty frontend (kreator 5 kroków) reużywający te same moduły domenowe
co aplikacja desktopowa. **`.exe` i wersja webowa działają równolegle, z jednego repo** —
web niczego nie zmienia w GUI/CLI ani w buildzie PyInstaller.

> Dokumentacja aplikacji desktopowej (.exe, GUI, CLI): [readme.md](readme.md)

## Przepływ w przeglądarce

1. **Wgraj wideo** — przeciągnij plik (MP4/MOV/MKV/AVI), pasek postępu uploadu.
2. **Oś czasu strzałów** — ID wyniku z kalkulatora (pobranie z API) albo wklejony tekst
   `"1: 2.81s | 2: 4.63s (+1.82s)"`. **Opcjonalna** przy checkboksie „Bez nakładki” (patrz
   „Bez nakładki — tylko przycięcie” niżej) — ale nawet wtedy podanie ID/tekstu poprawia
   auto-przycięcie.
3. **Sygnał startu** — auto-detekcja bzyczka shot-timera (T0) + automatyczne przycięcie;
   gdy bzyczka nie słychać, T0 ustawia się ręcznie w kroku 4.
4. **Podgląd i korekta** — klatka z nakładką dokładnie taką, jaka będzie w wyniku
   (WYSIWYG); suwak czasu, korekta T0/przycięcia, język PL/EN, płynący zegar od T0.
5. **Render i pobranie** — MP4 (H.264) / WebM (VP9) / GIF, postęp na żywo (SSE),
   przycisk „Zatrzymaj", link do pobrania.

## Bez nakładki — tylko przycięcie

Checkbox **„Bez nakładki"** w kroku 2 wyłącza wypalanie grafiki o strzałach na wideo —
render tylko wykrywa T0 i przycina źródło. Oś czasu strzałów (ID/tekst) zostaje
**opcjonalna, ale przydatna**: jeśli ją podasz, auto-przycięcie użyje jej do policzenia
okna „ostatni strzał + margines" (dokładniej niż stałe okno); bez niej korzysta ze
stałego okna **75 s po T0** (jak w CLI bez `--timeline`/`--id`).

- Pola język i płynący zegar w kroku 4 się chowają — nie mają zastosowania bez nakładki.
- Pole „Przytnij do (s)" zastępowane jest polem **„Długość od T0 (s)"** — wygodniej podać
  ile sekund materiału chcesz od sygnału startu, niż liczyć absolutny koniec przycięcia.
- Render wspiera wyłącznie **MP4** (przycięcie koduje audio jako AAC — niekompatybilne
  z kontenerami WebM/GIF).

Odpowiednik w CLI: `piro-overlay --video in.mp4 --id 5 --auto --no-overlay` (z osią) albo
`piro-overlay --video in.mp4 --auto --auto-window 75 --no-overlay` (bez osi).

## Uruchomienie

### Dev lokalny

```bash
pip install -e .[web]
PYTHONPATH=src uvicorn web.backend.app:create_app --factory --reload
# → http://127.0.0.1:8000
```

### Produkcja (VPS, Docker)

```bash
docker compose -f web/docker-compose.yml up -d --build
```

Obraz: `python:3.12-slim` + systemowy `ffmpeg` z apt (filtr drawtext → tani, płynny
zegar). Pliki robocze na named volume `piro-data:/data`. **Kontener musi działać jako
JEDEN proces uvicorn** (`--workers 1`, wpisane w Dockerfile) — magazyn zadań jest
in-memory; równoległość dają pule wątków.

### Reverse proxy (SSL)

Aplikacja nie terminuje SSL — ruch z internetu przechodzi przez **nginx proxy manager
(NPM) na osobnym hoście**. W proxy hoście NPM (zakładka *Advanced*) wymagane:

```nginx
client_max_body_size 2100m;       # >= PIRO_WEB_MAX_UPLOAD_MB
proxy_buffering off;              # SSE (/api/jobs/*/events) musi płynąć na bieżąco
proxy_request_buffering off;      # upload strumieniem, nie do bufora proxy
proxy_read_timeout 3600s;         # długi render nie zrywa połączenia SSE
```

NPM domyślnie przekazuje `X-Forwarded-For` — rate limiting z niego korzysta, gdy żądanie
nie ma jeszcze cookie sesji.

## Konfiguracja (zmienne środowiskowe)

| Zmienna | Domyślnie | Znaczenie |
|---|---|---|
| `PIRO_WEB_DATA_DIR` | `/data/jobs` (Docker) | katalogi robocze zadań |
| `PIRO_WEB_MAX_UPLOAD_MB` | `2048` | limit rozmiaru uploadu (413 powyżej) |
| `PIRO_WEB_MAX_JOBS_PER_SESSION` | `3` | równoczesne aktywne zadania na przeglądarkę |
| `PIRO_WEB_RENDER_WORKERS` | `1` | równoległe rendery FFmpeg (2 tylko na ≥8 vCPU) |
| `PIRO_WEB_ANALYZE_WORKERS` | `2` | wątki analizy audio / podglądu |
| `PIRO_WEB_JOB_TTL_MIN` | `120` | kasowanie plików po zakończeniu zadania |
| `PIRO_WEB_MAX_JOB_AGE_MIN` | `720` | twardy limit życia zadania |
| `PIRO_WEB_ENCODER` | `cpu` | `auto`/`gpu` tylko gdy host ma NVENC |
| `PIRO_WEB_RATE_PER_MIN` | `120` | ogólny limit żądań API na sesję |
| `PIRO_WEB_RENDERS_PER_HOUR` | `10` | limit uruchomień renderu na sesję |

## Publiczny hosting — co jest wbudowane

- **Izolacja sesji**: cookie `piro_sid` (HttpOnly); cudze/nieznane zadanie zwraca 404
  (bez możliwości enumeracji identyfikatorów).
- **Bezpieczne ścieżki**: nazwa pliku od klienta nigdy nie trafia na dysk — plik zapisuje
  się jako `source.<ext>` w `DATA_DIR/<sid>/<job_id>/`; oryginalna nazwa wraca tylko
  w nazwie pobieranego wyniku.
- **Limity**: rozmiar uploadu (licznik bajtów w trakcie strumienia), liczba zadań na
  sesję, rate limiting (token bucket in-memory) osobno dla API i dla renderów.
- **Sprzątanie**: pętla co 10 min usuwa zakończone zadania po TTL, przeterminowane
  aktywne oraz osierocone katalogi (np. po restarcie kontenera).
- **Anulowanie**: „Zatrzymaj" ubija proces FFmpeg natychmiast i sprząta niedokończony plik.

## API (skrót)

| Endpoint | Działanie |
|---|---|
| `GET /api/version` | `{version, repo}` — stopka frontendu |
| `POST /api/jobs` | upload (body = plik, nagłówek `X-Filename`) → JSON zadania |
| `POST /api/jobs/{id}/session` | `{source:"id"\|"timeline", id?, timeline?}` |
| `POST /api/jobs/{id}/analyze` | detekcja T0 + auto-przycięcie (`t0:null` gdy brak bzyczka) |
| `GET /api/jobs/{id}/preview?t=&t0=&lang=&clock=&h=` | PNG klatki z nakładką |
| `POST /api/jobs/{id}/render` | `{format, lang, clock, t0, trim_start, trim_end, no_overlay}` → 202 |
| `GET /api/jobs/{id}/events` | SSE: `state` / `progress` / `encoder` / `done` / `error` |
| `POST /api/jobs/{id}/cancel` | przerwij render |
| `GET /api/jobs/{id}/download` | pobierz wynik |
| `DELETE /api/jobs/{id}` | usuń zadanie i pliki |

Interaktywna dokumentacja OpenAPI: `http://<host>:8000/docs`.

## Testy

```bash
PYTHONPATH=src pytest tests/test_web_api.py tests/test_web_limits.py
```

Testy web wymagają `fastapi` (`pip install -e .[web]`); bez niego są pomijane
(`pytest.importorskip`) — środowisko builda `.exe` pozostaje zielone. Fixture
`tiny_video` generuje realny MP4 (lavfi: obraz testowy + ton 2700 Hz udający bzyczek),
więc detekcja T0 i render testują się end-to-end, bez mockowania FFmpeg.

## Architektura

`web/backend/` importuje wyłącznie domenę (`pipeline`, `preview`, `render`, `ffmpeg`,
`api`, `models`) — zero Qt. Wspólna orkiestracja przepływu (sesja → T0 → przycięcie)
mieszka w `src/piro_overlay/pipeline.py` i jest dzielona z CLI; kompozycja podglądu
w `src/piro_overlay/preview.py`. Szczegóły i pułapki: `CLAUDE.md`, sekcja
„Wersja webowa (`web/`)".
