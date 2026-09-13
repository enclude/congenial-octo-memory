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


def _log_error(context: str, exc: Exception) -> None:
    """Dopisuje błąd zapisu/odczytu konfiguracji do config_log.txt w AppData.

    Operacje konfiguracyjne są best-effort (nie mogą wywrócić aplikacji), ale
    cicha porażka zapisu ukrywała już bugi (np. last_style.json = 0 B) — plik
    dziennika jest jedynym śladem, gdy ustawienia „znikają"."""
    try:
        path = config_dir() / "config_log.txt"
        if path.exists() and path.stat().st_size > 256 * 1024:
            path.write_text("", encoding="utf-8")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{context}: {type(exc).__name__}: {exc}\n")
    except Exception:  # noqa: BLE001
        pass


def last_style_path() -> Path:
    return config_dir() / "last_style.json"


def save_last_style(style: OverlayStyle) -> None:
    try:
        style.to_json(last_style_path())
    except Exception as exc:  # noqa: BLE001
        _log_error("save_last_style", exc)


def load_last_style() -> OverlayStyle | None:
    path = last_style_path()
    if not path.exists():
        return None
    try:
        return OverlayStyle.from_json(path)
    except Exception as exc:  # noqa: BLE001
        _log_error("load_last_style", exc)
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
    except Exception as exc:  # noqa: BLE001
        _log_error("save_last_dir", exc)


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
    except Exception as exc:  # noqa: BLE001
        _log_error("load_last_dir", exc)
        return None


# --- ustawienia UI (drobne, globalne — np. współbieżność kolejki renderów) ---
_QUEUE_PARALLEL_DEFAULT = 2   # patrz CLAUDE.md: NVENC ~45% przy 1 zadaniu → 2 równolegle
_QUEUE_PARALLEL_MAX = 4


def _ui_settings_path() -> Path:
    return config_dir() / "ui_settings.json"


def save_queue_parallel(n: int) -> None:
    """Zapisuje limit równoległych renderów kolejki."""
    try:
        import json
        p = _ui_settings_path()
        data: dict = {}
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                pass
        data["queue_parallel"] = int(n)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        _log_error("save_queue_parallel", exc)


def load_queue_parallel() -> int:
    """Limit równoległych renderów kolejki (przycięty do 1..4)."""
    try:
        import json
        p = _ui_settings_path()
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            val = data.get("queue_parallel")
            if val is not None:
                return max(1, min(_QUEUE_PARALLEL_MAX, int(val)))
    except Exception as exc:  # noqa: BLE001
        _log_error("load_queue_parallel", exc)
    return _QUEUE_PARALLEL_DEFAULT


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
    except Exception as exc:  # noqa: BLE001
        _log_error("_load_file_store", exc)
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
    except Exception as exc:  # noqa: BLE001
        _log_error("save_file_settings", exc)


def load_file_settings(video_path: str | Path) -> dict | None:
    """Wczytuje zapisane parametry dla danego pliku wideo (None gdy brak)."""
    data = _load_file_store().get(_file_key(video_path))
    return data if isinstance(data, dict) else None


# --- kolejka renderów (zapis w AppData, odzysk po awarii) ---
def queue_path() -> Path:
    return config_dir() / "render_queue.json"


def save_queue(data: dict) -> None:
    """Zapisuje stan kolejki renderów do AppData. Gotowe (DONE) zadania pomijaj
    przed wywołaniem — w pliku mają zostać tylko zadania do (po)wykonania."""
    try:
        import json
        queue_path().write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        _log_error("save_queue", exc)


def load_queue() -> dict | None:
    """Wczytuje zapisaną kolejkę renderów (None gdy brak/uszkodzona)."""
    try:
        import json
        p = queue_path()
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception as exc:  # noqa: BLE001
        _log_error("load_queue", exc)
        return None


# --- cache proxy podglądu (osobny katalog, NIE miesza się z file_settings.json) ---
# Proxy 540p jednego nagrania to kilka–kilkadziesiąt MB, więc cache ma DWA limity:
# liczbę plików i łączny rozmiar. Sprzątamy po każdej udanej budowie.
_PROXY_MAX_FILES = 24
_PROXY_MAX_BYTES = 3 * 1024 ** 3


def proxy_dir() -> Path:
    """Katalog z proxy podglądu (tworzy go, jeśli nie istnieje)."""
    d = config_dir() / "proxies"
    d.mkdir(parents=True, exist_ok=True)
    return d


def proxy_path_for(video_path: str | Path) -> Path:
    """Ścieżka proxy dla danego pliku wideo (nie sprawdza, czy istnieje).

    Nazwa to skrót ze ścieżki ORAZ rozmiaru i czasu modyfikacji — podmiana pliku
    pod tą samą nazwą (albo dogranie innego nagrania z kamery) daje inny skrót,
    więc nigdy nie odtworzymy proxy nieodpowiadającego bieżącej zawartości.
    """
    import hashlib
    p = Path(video_path)
    try:
        resolved = str(p.resolve())
    except Exception:  # noqa: BLE001
        resolved = str(p)
    try:
        st = p.stat()
        size, mtime = st.st_size, st.st_mtime_ns
    except OSError:
        size, mtime = 0, 0
    key = f"{resolved}|{size}|{mtime}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]
    return proxy_dir() / f"{digest}.mp4"


def find_proxy(video_path: str | Path) -> Path | None:
    """Gotowe proxy dla pliku (None gdy brak albo plik pusty/uszkodzony)."""
    try:
        path = proxy_path_for(video_path)
        if path.exists() and path.stat().st_size > 0:
            return path
    except Exception as exc:  # noqa: BLE001
        _log_error("find_proxy", exc)
    return None


def prune_proxies(max_files: int = _PROXY_MAX_FILES,
                  max_bytes: int = _PROXY_MAX_BYTES) -> None:
    """Usuwa najstarsze proxy, gdy cache przekroczy limit plików albo rozmiaru.

    „Najstarsze" liczymy po ostatnim UŻYCIU (`atime`, z `mtime` jako zapasem) —
    proxy, na którym użytkownik wciąż pracuje, przeżywa sprzątanie."""
    try:
        entries = []
        for path in proxy_dir().glob("*.mp4"):
            try:
                st = path.stat()
            except OSError:
                continue
            entries.append((max(st.st_atime, st.st_mtime), st.st_size, path))
        entries.sort(reverse=True)   # najświeższe pierwsze
        total = 0
        for i, (_, size, path) in enumerate(entries):
            total += size
            if i >= max_files or total > max_bytes:
                path.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        _log_error("prune_proxies", exc)
