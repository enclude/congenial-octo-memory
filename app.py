"""Punkt wejścia dla pakowania do .exe (PyInstaller).

Bez argumentów uruchamia GUI; z argumentami działa jak CLI (`piro-overlay …`),
więc ten sam PiroOverlay.exe robi zadania bezgłowo, np.:

    PiroOverlay.exe --video in.mp4 --id 5 --auto --clock -o out.mp4

Import pakietu (a nie samego modułu) sprawia, że importy względne wewnątrz
`piro_overlay` działają poprawnie również w trybie spakowanym.
"""

import sys


def _attach_parent_console() -> None:
    """Windows: podłącz konsolę procesu-rodzica, by stdout/stderr CLI był widoczny.

    Exe budujemy jako aplikację GUI (console=False), więc bez tego tryb CLI
    działałby „po cichu". Gdy uruchomiono z cmd/PowerShell, podpinamy się do tej
    konsoli; w innym wypadku (np. podwójny klik) po prostu nic nie robimy.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ATTACH_PARENT_PROCESS = -1
        if ctypes.windll.kernel32.AttachConsole(ATTACH_PARENT_PROCESS):
            for name in ("stdout", "stderr"):
                try:
                    setattr(sys, name, open("CONOUT$", "w", encoding="utf-8"))
                except OSError:
                    pass
    except Exception:  # noqa: BLE001 — brak konsoli to nie błąd
        pass


def main() -> int:
    if len(sys.argv) > 1:  # jakikolwiek argument → tryb CLI
        _attach_parent_console()
        from piro_overlay.cli import main as cli_main
        return cli_main()
    from piro_overlay.gui import main as gui_main
    return gui_main()


if __name__ == "__main__":
    sys.exit(main())
