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
import sys

import imageio_ffmpeg

block_cipher = None

# SPECPATH = katalog zawierający ten plik .spec (korzeń projektu).
# Używamy ścieżek bezwzględnych — PyInstaller po cichu ignoruje ścieżki względne,
# których nie może znaleźć, co powoduje brak ikony lub zasobów w paczce.
_root = SPECPATH

# Pakiet bierzemy JAWNIE ze źródeł (src/), nie z instalacji w venv. Nowsze pip
# instalują `pip install -e .` przez finder PEP 660 (__editable___…_finder),
# którego analiza PyInstallera nie umie prześledzić — objaw: exe buduje się bez
# błędu, a w runtime pada „No module named 'piro_overlay.gui'" (pakiet-rodzic
# trafia do paczki, submoduły nie). sys.path dla collect_submodules poniżej,
# pathex (bezwzględny!) dla analizy importów z app.py.
_src = os.path.join(_root, "src")
sys.path.insert(0, _src)

from PyInstaller.utils.hooks import collect_submodules

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
    pathex=[_src],
    binaries=binaries,
    datas=datas,
    # Wszystkie submoduły pakietu jawnie — importy w app.py są wewnątrz funkcji
    # (leniwe rozgałęzienie GUI/CLI), więc nie polegamy na samej analizie bytecode'u.
    hiddenimports=["imageio_ffmpeg", *collect_submodules("piro_overlay")],
    hookspath=[],
    runtime_hooks=[],
    excludes=["soundfile", "_soundfile"],
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
