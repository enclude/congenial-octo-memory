"""Konfiguracja użytkownika — ścieżki i zapis/odczyt ostatniego stylu nakładki.

Moduł domenowy: brak importów PySide6.
"""

from __future__ import annotations

import os
from pathlib import Path

from .models import OverlayStyle


def config_dir() -> Path:
    """Zwraca katalog konfiguracji aplikacji; tworzy go, jeśli nie istnieje."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "PiroOverlay"
    d.mkdir(parents=True, exist_ok=True)
    return d


def last_style_path() -> Path:
    return config_dir() / "last_style.json"


def save_last_style(style: OverlayStyle) -> None:
    try:
        style.to_json(last_style_path())
    except Exception:  # noqa: BLE001
        pass


def load_last_style() -> OverlayStyle | None:
    path = last_style_path()
    if not path.exists():
        return None
    try:
        return OverlayStyle.from_json(path)
    except Exception:  # noqa: BLE001
        return None
