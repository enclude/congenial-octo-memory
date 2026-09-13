"""Strażnik zestawu ikon (`assets/icons/*.svg`) — bez importu PySide6/QtSvg.

Środowisko testowe (WSL/CI) nie ma PySide6, więc nie da się tu wywołać
`ui_theme.icon()`. Zamiast tego pilnujemy dwóch rzeczy statycznie: (1) każdy
plik SVG jest poprawnym XML-em w oczekiwanym kształcie (viewBox 24x24,
`currentColor` do barwienia — bez tego `str.replace` w `ui_theme.icon` nic
by nie podmienił i ikona zostałaby czarna/biała niezależnie od motywu);
(2) każda nazwa ikony użyta w `gui.py` (`ui_theme.icon("x")` albo
`_apply_icon(btn, "x", ...)`) ma odpowiadający plik na dysku — literówka w
nazwie inaczej ujawniłaby się dopiero jako pusta ikona w uruchomionym GUI.
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
_ICONS_DIR = _ROOT / "assets" / "icons"
_GUI_SRC = (_ROOT / "src" / "piro_overlay" / "gui.py").read_text(encoding="utf-8")

_ICON_FILES = sorted(_ICONS_DIR.glob("*.svg"))


def _used_icon_names() -> set[str]:
    names = set(re.findall(r'ui_theme\.icon\(\s*"([a-z0-9-]+)"', _GUI_SRC))
    names |= set(re.findall(r'_apply_icon\([^,]+,\s*"([a-z0-9-]+)"', _GUI_SRC))
    return names


def test_icons_dir_is_not_empty():
    assert _ICON_FILES, "assets/icons powinien zawierać zestaw SVG"


@pytest.mark.parametrize("path", _ICON_FILES, ids=lambda p: p.name)
def test_icon_is_well_formed_and_tintable(path: Path):
    text = path.read_text(encoding="utf-8")
    ET.fromstring(text)   # rzuci, jeśli to nie jest poprawny XML
    assert 'viewBox="0 0 24 24"' in text, f"{path.name}: brak viewBox 0 0 24 24"
    assert "currentColor" in text, f"{path.name}: brak currentColor do barwienia tokenem"


def test_every_icon_name_used_in_gui_exists_on_disk():
    on_disk = {p.stem for p in _ICON_FILES}
    used = _used_icon_names()
    assert used, "regex nie znalazł żadnego wywołania icon(...) w gui.py — sprawdź wzorzec"
    missing = used - on_disk
    assert not missing, f"gui.py odwołuje się do brakujących ikon: {sorted(missing)}"
