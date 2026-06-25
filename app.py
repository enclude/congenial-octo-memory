"""Punkt wejścia dla pakowania do .exe (PyInstaller).

Uruchamia GUI przez import pakietu — dzięki temu importy względne wewnątrz
`piro_overlay` działają poprawnie (gdy entry-pointem jest sam `gui.py`,
moduł rusza jako `__main__` bez pakietu nadrzędnego i importy względne padają).
"""

import sys

from piro_overlay.gui import main

if __name__ == "__main__":
    sys.exit(main())
