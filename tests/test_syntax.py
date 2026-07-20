"""Strażnik składni: kompiluje KAŻDY moduł pakietu (+ app.py), bez importowania.

Środowisko testowe (WSL/CI) nie ma PySide6, więc żaden test nie importuje
`gui.py` — błąd składni potrafił przejść niezauważony aż do builda .exe,
gdzie PyInstaller po cichu pomijał „invalid module" i exe padał w runtime
z ModuleNotFoundError (realny przypadek: ASCII `"` zamiast `”` w tooltipie,
v0.38.0). Kompilacja nie wymaga zależności modułu, więc łapie to zawsze.
"""

import py_compile
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
_SOURCES = sorted((_ROOT / "src" / "piro_overlay").glob("*.py")) + [_ROOT / "app.py"]


@pytest.mark.parametrize("path", _SOURCES, ids=lambda p: p.name)
def test_module_compiles(path: Path):
    py_compile.compile(str(path), doraise=True)
