# PyInstaller spec dla Piro Overlay.
#
# Build (na Windows — PyInstaller nie robi cross-compile):
#     pip install pyinstaller
#     pyinstaller build_exe.spec
#     -> dist/PiroOverlay.exe
#
# UWAGA — imageio-ffmpeg: PyInstaller nie zbiera automatycznie binarki FFmpeg.
# Dokładamy ją ręcznie do katalogu `imageio_ffmpeg/binaries`, gdzie szuka jej
# `imageio_ffmpeg.get_ffmpeg_exe()` w trybie spakowanym. Fonty trafiają do
# `assets/fonts`, skąd czyta je `resources.py` przez `sys._MEIPASS`.

import os
import imageio_ffmpeg

block_cipher = None

# SPECPATH = katalog zawierający ten plik .spec (korzeń projektu).
# Używamy ścieżek bezwzględnych — PyInstaller po cichu ignoruje ścieżki względne,
# których nie może znaleźć, co powoduje brak ikony lub zasobów w paczce.
_root = SPECPATH

ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

binaries = [
    (ffmpeg_exe, "imageio_ffmpeg/binaries"),
]

datas = [
    (os.path.join(_root, "assets", "fonts", "DejaVuSans.ttf"),      "assets/fonts"),
    (os.path.join(_root, "assets", "fonts", "DejaVuSans-Bold.ttf"), "assets/fonts"),
    (os.path.join(_root, "assets", "icon.png"),                      "assets"),
    (os.path.join(_root, "assets", "icon.ico"),                      "assets"),
]

# Opcjonalny pełny FFmpeg (z NVENC) dołączany przez `build.ps1 -WithFfmpeg`.
_full_ffmpeg = os.path.join(_root, "assets", "bin", "ffmpeg.exe")
if os.path.exists(_full_ffmpeg):
    datas.append((_full_ffmpeg, "assets/bin"))

a = Analysis(
    ["app.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=["imageio_ffmpeg"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PiroOverlay",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,              # bez UPX — szybszy build (UPX wolno kompresuje)
    console=False,          # aplikacja GUI — bez okna konsoli
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(_root, "assets", "icon.ico"),
)
