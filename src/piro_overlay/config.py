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


def _last_dirs_path() -> Path:
    return config_dir() / "last_dirs.json"


def save_last_dir(key: str, path: str | Path) -> None:
    """Zapisuje ostatnio używany katalog dla danego klucza (np. 'video', 'output', 'preset')."""
    try:
        import json
        p = _last_dirs_path()
        data: dict[str, str] = {}
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                pass
        data[key] = str(path)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def load_last_dir(key: str) -> str | None:
    """Wczytuje ostatnio używany katalog dla klucza. Zwraca None jeśli nie zapisany lub nie istnieje."""
    try:
        import json
        p = _last_dirs_path()
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        value = data.get(key)
        if value and Path(value).is_dir():
            return value
        return None
    except Exception:  # noqa: BLE001
        return None


# --- ustawienia per-plik (zapamiętane przy renderze / dodaniu do kolejki) ---
_MAX_FILE_ENTRIES = 100  # limit wpisów — najstarsze usuwane przy przekroczeniu


def _file_settings_path() -> Path:
    return config_dir() / "file_settings.json"


def _file_key(video_path: str | Path) -> str:
    """Klucz wpisu = znormalizowana, bezwzględna ścieżka pliku."""
    try:
        return str(Path(video_path).resolve())
    except Exception:  # noqa: BLE001
        return str(video_path)


def _load_file_store() -> dict:
    p = _file_settings_path()
    if not p.exists():
        return {}
    try:
        import json
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def save_file_settings(video_path: str | Path, data: dict) -> None:
    """Zapisuje komplet parametrów dla danego pliku wideo (klucz = ścieżka).

    Wpis trafia na koniec (najświeższy); przy przekroczeniu limitu usuwane są
    najstarsze wpisy. Całość trzymana w jednym pliku JSON w katalogu konfiguracji.
    """
    try:
        import json
        store = _load_file_store()
        key = _file_key(video_path)
        store.pop(key, None)  # ponowny zapis → przenieś na koniec (LRU)
        store[key] = data
        overflow = len(store) - _MAX_FILE_ENTRIES
        if overflow > 0:
            for old in list(store.keys())[:overflow]:
                store.pop(old, None)
        _file_settings_path().write_text(
            json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def load_file_settings(video_path: str | Path) -> dict | None:
    """Wczytuje zapisane parametry dla danego pliku wideo (None gdy brak)."""
    data = _load_file_store().get(_file_key(video_path))
    return data if isinstance(data, dict) else None
