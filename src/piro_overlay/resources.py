"""Rozwiązywanie ścieżek do zasobów (fonty) w trybie dev i spakowanym (.exe).

PyInstaller rozpakowuje dołączone dane do katalogu wskazywanego przez
`sys._MEIPASS`. W trybie deweloperskim zasoby leżą w `assets/` w korzeniu repo.
"""

from __future__ import annotations

import sys
from pathlib import Path

_FONT_REGULAR = "DejaVuSans.ttf"
_FONT_BOLD = "DejaVuSans-Bold.ttf"


def _assets_root() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:  # tryb spakowany — dane w <bundle>/assets
        return Path(base) / "assets"
    # tryb dev — src/piro_overlay/resources.py -> korzeń repo / assets
    return Path(__file__).resolve().parents[2] / "assets"


def font_path(bold: bool = False) -> str:
    name = _FONT_BOLD if bold else _FONT_REGULAR
    return str(_assets_root() / "fonts" / name)


def icon_path(ico: bool = False) -> str:
    """Ścieżka do ikony aplikacji (.png dla okna, .ico dla .exe)."""
    return str(_assets_root() / ("icon.ico" if ico else "icon.png"))


def bundled_ffmpeg_path() -> str | None:
    """Ścieżka do dołączonego pełnego FFmpeg (np. z NVENC), jeśli istnieje.

    Build z flagą -WithFfmpeg umieszcza binarkę w assets/bin/. Dzięki temu .exe
    może mieć akcelerację GPU bez instalowania FFmpeg w systemie.
    """
    name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    path = _assets_root() / "bin" / name
    return str(path) if path.exists() else None
