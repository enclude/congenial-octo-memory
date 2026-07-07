"""Konfiguracja backendu WWW — wszystko przez zmienne środowiskowe PIRO_WEB_*.

Defaulty dobrane pod publiczny VPS bez GPU (encoder=cpu, 1 render naraz).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_PREFIX = "PIRO_WEB_"


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("web_data")
    max_upload_mb: int = 2048
    max_jobs_per_session: int = 3
    render_workers: int = 1
    analyze_workers: int = 2
    job_ttl_min: int = 120
    max_job_age_min: int = 720
    encoder: str = "cpu"
    rate_per_min: int = 120
    renders_per_hour: int = 10
    max_jobs_total: int = 60
    # Bez zaufanego proxy przed aplikacją nagłówek X-Forwarded-For jest w pełni
    # kontrolowany przez klienta — ufanie mu wprost pozwala obchodzić rate limit
    # (inny "adres" na każde żądanie). Domyślnie WYŁĄCZONE; włączać tylko gdy
    # aplikacja faktycznie stoi za reverse proxy, który nadpisuje/dokłada ten
    # nagłówek na podstawie realnego adresu peera (patrz ratelimit.client_key).
    trust_proxy_headers: bool = False

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(_PREFIX + name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(_PREFIX + name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def load_settings() -> Settings:
    return Settings(
        data_dir=Path(os.environ.get(_PREFIX + "DATA_DIR", "web_data")),
        max_upload_mb=_env_int("MAX_UPLOAD_MB", 2048),
        max_jobs_per_session=_env_int("MAX_JOBS_PER_SESSION", 3),
        render_workers=min(_env_int("RENDER_WORKERS", 1), 2),
        analyze_workers=_env_int("ANALYZE_WORKERS", 2),
        job_ttl_min=_env_int("JOB_TTL_MIN", 120),
        max_job_age_min=_env_int("MAX_JOB_AGE_MIN", 720),
        encoder=os.environ.get(_PREFIX + "ENCODER", "cpu"),
        rate_per_min=_env_int("RATE_PER_MIN", 120),
        renders_per_hour=_env_int("RENDERS_PER_HOUR", 10),
        max_jobs_total=_env_int("MAX_JOBS_TOTAL", 60),
        trust_proxy_headers=_env_bool("TRUST_PROXY_HEADERS", False),
    )
