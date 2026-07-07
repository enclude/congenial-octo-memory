# Piro Overlay Web — obraz backendu (FastAPI + FFmpeg).
# Kontekst budowania = KORZEŃ repo:  docker build -f web/Dockerfile .
#
# Systemowy ffmpeg z apt ma filtr drawtext (tani, płynny zegar) i pełne muxery;
# PIRO_FFMPEG wskazujemy JAWNIE, bo ffmpeg._resolve_ffmpeg wybiera systemową
# binarkę tylko wtedy, gdy ma NVENC (na VPS bez GPU nie ma).
# imageio-ffmpeg zostaje jako awaryjny fallback.

FROM python:3.12-slim

LABEL org.opencontainers.image.description="Piro Overlay Web — backend FastAPI do nakładania informacji o strzałach na wideo ze strzelania (dokumentacja: readme_web.md)"

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

ENV PIRO_FFMPEG=/usr/bin/ffmpeg \
    XDG_CONFIG_HOME=/data/config \
    PIRO_WEB_DATA_DIR=/data/jobs \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY web/requirements.txt web/requirements.txt
RUN pip install --no-cache-dir -r web/requirements.txt

# Pakiet uruchamiamy z layoutu repo (PYTHONPATH=/app/src) — bez pip install,
# dzięki czemu resources.py znajduje fonty w assets/ jak w trybie dev.
COPY src ./src
COPY assets ./assets
COPY web ./web

EXPOSE 8000

# --workers 1 to WYMÓG: magazyn zadań jest in-memory (jeden proces);
# równoległość dają pule wątków (PIRO_WEB_RENDER_WORKERS / ANALYZE_WORKERS).
CMD ["uvicorn", "web.backend.app:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
