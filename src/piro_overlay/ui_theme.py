"""Warstwa motywu Qt (PySide6): tokeny, QPalette, QSS, HiDPI, integracja z Windows.

Moduł WYŁĄCZNIE UI — może importować PySide6, bo leży obok `gui.py`. Moduły
domenowe (`models`, `parser`, `api`, `render`, ...) nigdy go nie importują.

Źródło wartości: skill `python-desktop-ux`, `references/design-tokens.md`
(kopia `scripts/qt_theme.py` bez sekcji demo).

Użycie w `main()` (kolejność ma znaczenie — patrz `qt-pyside6.md` §2):

    setup_hidpi()                       # PRZED QApplication
    app = QApplication(sys.argv)
    load_app_fonts(Path(resources.font_path()).parent)
    theme = apply_theme(app, "dark")    # Fusion + QPalette + QSS + font
    win = MainWindow()
    win.show()
    set_windows_dark_titlebar(win, theme["mode"] == "dark")
"""

from __future__ import annotations

import ctypes
import os
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Tokens (source of truth: references/design-tokens.md)
# ---------------------------------------------------------------------------

TOKENS: dict[str, dict[str, str]] = {
    "dark": {
        "bg": "#1F1F1F",
        "surface": "#2A2A2C",
        "surface_alt": "#353538",
        "border": "#3F3F43",
        "border_strong": "#78787F",
        "text": "#F2F2F2",
        "text_muted": "#A0A0A8",
        "text_disabled": "#6E6E76",
        "accent": "#FFC400",
        "accent_hover": "#FFD033",
        "accent_pressed": "#E0AC00",
        "accent_text": "#1A1200",
        "accent_subtle": "#3F3821",
        "danger": "#F87171",
        "success": "#4ADE80",
        "warning": "#FB923C",
        "info": "#60A5FA",
        "focus": "#FFFFFF",
        "selection_bg": "#FFC400",
        "selection_text": "#1A1200",
    },
    "light": {
        "bg": "#F3F3F3",
        "surface": "#FFFFFF",
        "surface_alt": "#ECECEE",
        "border": "#D5D5D9",
        "border_strong": "#8A8A90",
        "text": "#1B1B1F",
        "text_muted": "#5C5C63",
        "text_disabled": "#9A9AA1",
        "accent": "#8A6100",
        "accent_hover": "#986A00",
        "accent_pressed": "#6B4B00",
        "accent_text": "#FFFFFF",
        "accent_subtle": "#FFF3CC",
        "danger": "#C42B1C",
        "success": "#0F7B0F",
        "warning": "#B45309",
        "info": "#0F6CBD",
        "focus": "#1B1B1F",
        "selection_bg": "#FFC400",
        "selection_text": "#1A1200",
    },
}

# Logical pixels at 100 %. Qt6 scales them with the screen DPI automatically.
SPACING: dict[str, int] = {
    "sp_1": 4,
    "sp_2": 8,
    "sp_3": 12,
    "sp_4": 16,
    "sp_5": 20,
    "sp_6": 24,
    "sp_8": 32,
}

RADIUS: dict[str, int] = {
    "r_sm": 4,
    "r_md": 6,
    "r_lg": 8,
}

# Point sizes; the first family present in QFontDatabase.families() is used.
FONT_FAMILIES: dict[str, dict[str, Any]] = {
    "font_ui": {
        "families": ["Segoe UI Variable Text", "Segoe UI", "Noto Sans", "DejaVu Sans"],
        "size": 10,
        "bold": False,
    },
    "font_ui_small": {
        "families": ["Segoe UI Variable Text", "Segoe UI", "Noto Sans", "DejaVu Sans"],
        "size": 9,
        "bold": False,
    },
    "font_section": {
        "families": ["Segoe UI Variable Text", "Segoe UI", "Noto Sans", "DejaVu Sans"],
        "size": 11,
        "bold": True,
    },
    "font_title": {
        "families": ["Segoe UI Variable Text", "Segoe UI", "Noto Sans", "DejaVu Sans"],
        "size": 13,
        "bold": True,
    },
    "font_mono": {
        "families": ["Cascadia Mono", "Consolas", "Menlo", "Noto Sans Mono", "DejaVu Sans Mono"],
        "size": 10,
        "bold": False,
    },
}

CONTROL_HEIGHT = 32   # px, buttons and single-line fields
INDICATOR_SIZE = 18   # px, QCheckBox / QRadioButton indicator
SCROLLBAR_WIDTH = 8   # px, thin scrollbars


# ---------------------------------------------------------------------------
# HiDPI and fonts
# ---------------------------------------------------------------------------

def setup_hidpi() -> None:
    """Configure HiDPI behaviour. Call BEFORE creating QApplication.

    Qt6 enables per-screen DPI scaling by default; the only useful knob is the
    rounding policy. PassThrough keeps fractional factors (125 %, 150 %) so the
    UI is neither blurry nor oversized. ``QT_ENABLE_HIGHDPI_SCALING`` is left
    untouched (default on).
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )


def pick_font_family(candidates: list[str]) -> str:
    """Return the first family installed on this system, else the app default.

    Requires a live QGuiApplication (QFontDatabase needs one).
    """
    from PySide6.QtGui import QFont, QFontDatabase

    installed = set(QFontDatabase.families())
    for fam in candidates:
        if fam in installed:
            return fam
    return QFont().defaultFamily()


def make_font(name: str) -> Any:
    """Build a QFont for a named token (``font_ui``, ``font_mono`` ...)."""
    from PySide6.QtGui import QFont

    spec = FONT_FAMILIES[name]
    f = QFont(pick_font_family(spec["families"]), spec["size"])
    f.setBold(bool(spec["bold"]))
    return f


def load_app_fonts(dir_path: str | os.PathLike[str]) -> list[str]:
    """Register every *.ttf / *.otf in ``dir_path`` with QFontDatabase.

    Returns the family names that became available. Bundled fonts (assets/fonts)
    are usable in QSS and QFont only after this call; call it after QApplication
    exists and before ``apply_theme``.
    """
    from PySide6.QtGui import QFontDatabase

    families: list[str] = []
    if not os.path.isdir(dir_path):
        return families
    for entry in sorted(os.listdir(dir_path)):
        if not entry.lower().endswith((".ttf", ".otf")):
            continue
        font_id = QFontDatabase.addApplicationFont(os.path.join(dir_path, entry))
        if font_id >= 0:
            families.extend(QFontDatabase.applicationFontFamilies(font_id))
    return families


# ---------------------------------------------------------------------------
# QPalette
# ---------------------------------------------------------------------------

def build_palette(tokens: dict[str, str]) -> Any:
    """Build a QPalette from tokens. Fusion honours it wherever QSS is silent.

    Covers every role the app touches, plus the Disabled group so that
    disabled widgets drawn by Fusion (not by QSS) use ``text_disabled``.
    """
    from PySide6.QtGui import QColor, QPalette

    c = {k: QColor(v) for k, v in tokens.items()}
    pal = QPalette()
    roles = {
        QPalette.Window: c["bg"],
        QPalette.WindowText: c["text"],
        QPalette.Base: c["surface_alt"],
        QPalette.AlternateBase: c["surface"],
        QPalette.Text: c["text"],
        QPalette.Button: c["surface"],
        QPalette.ButtonText: c["text"],
        QPalette.BrightText: c["focus"],
        QPalette.Highlight: c["selection_bg"],
        QPalette.HighlightedText: c["selection_text"],
        QPalette.ToolTipBase: c["surface_alt"],
        QPalette.ToolTipText: c["text"],
        QPalette.PlaceholderText: c["text_muted"],
        QPalette.Link: c["info"],
        QPalette.LinkVisited: c["info"],
        QPalette.Light: c["surface_alt"],
        QPalette.Midlight: c["border"],
        QPalette.Mid: c["border_strong"],
        QPalette.Dark: c["bg"],
        QPalette.Shadow: c["bg"],
    }
    for role, color in roles.items():
        pal.setColor(role, color)
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText,
                 QPalette.HighlightedText):
        pal.setColor(QPalette.Disabled, role, c["text_disabled"])
    pal.setColor(QPalette.Disabled, QPalette.Base, c["surface"])
    pal.setColor(QPalette.Disabled, QPalette.Button, c["surface"])
    pal.setColor(QPalette.Disabled, QPalette.Highlight, c["accent_subtle"])
    return pal


# ---------------------------------------------------------------------------
# QSS
# ---------------------------------------------------------------------------

# Template uses $name placeholders (string.Template) so literal braces need no
# escaping. Every colour comes from a token; sizes from SPACING / RADIUS.
_QSS_TEMPLATE = r"""
/* ---- base ------------------------------------------------------------ */
QWidget {
    font-family: "$font_family";
    font-size: ${font_size}pt;
    color: $text;
    selection-background-color: $selection_bg;
    selection-color: $selection_text;
}
QMainWindow, QDialog { background: $bg; }
QWidget:disabled { color: $text_disabled; }

QToolTip {
    background: $surface_alt;
    color: $text;
    border: 1px solid $border_strong;
    border-radius: ${r_md}px;
    padding: ${sp_1}px ${sp_2}px;
}

/* ---- labels by role --------------------------------------------------- */
QLabel[role="title"]   { font-size: ${font_title}pt; font-weight: bold; }
QLabel[role="section"] { font-size: ${font_section}pt; font-weight: bold; }
QLabel[role="muted"]   { color: $text_muted; font-size: ${font_small}pt; }
QLabel[role="mono"], QPlainTextEdit[role="mono"] { font-family: "$mono_family"; }
QLabel[role="danger"]  { color: $danger; }
QLabel[role="success"] { color: $success; }
QLabel[role="warning"] { color: $warning; }
QLabel[role="info"]    { color: $info; }

/* ---- QGroupBox: borderless section with bold title -------------------- */
QGroupBox {
    border: none;
    border-top: 1px solid $border;
    margin-top: ${sp_5}px;
    padding: ${sp_3}px 0 0 0;
    font-weight: bold;
    font-size: ${font_section}pt;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 0;
    padding: 0 ${sp_1}px 0 0;
    color: $text;
    background: $bg;
}

/* ---- buttons ---------------------------------------------------------- */
QPushButton, QToolButton {
    background: $surface;
    color: $text;
    border: 1px solid $border_strong;
    border-radius: ${r_md}px;
    padding: 0 ${sp_3}px;
    min-height: ${control_h}px;
}
QToolButton { padding: 0 ${sp_2}px; min-width: ${control_h}px; }
QPushButton:hover, QToolButton:hover { background: $surface_alt; }
QPushButton:pressed, QToolButton:pressed { background: $surface_alt; border-color: $text_muted; }
QPushButton:focus, QToolButton:focus { border: 2px solid $focus; padding: 0 ${sp_3_minus_1}px; }
QPushButton:disabled, QToolButton:disabled {
    background: $surface; color: $text_disabled; border-color: $border;
}
QPushButton:checked, QToolButton:checked {
    background: $accent_subtle; border-color: $accent;
}
QPushButton[kind="primary"] {
    background: $accent; color: $accent_text; border: none; font-weight: bold;
    padding: 0 ${sp_4}px;
}
QPushButton[kind="primary"]:hover   { background: $accent_hover; }
QPushButton[kind="primary"]:pressed { background: $accent_pressed; }
QPushButton[kind="primary"]:focus   { border: 2px solid $focus; padding: 0 ${sp_4_minus_2}px; }
QPushButton[kind="primary"]:disabled { background: $surface_alt; color: $text_disabled; }
QToolButton[kind="primary"] {
    background: $accent; color: $accent_text; border: none; font-weight: bold;
    padding: 0 ${sp_4}px;
}
QToolButton[kind="primary"]:hover   { background: $accent_hover; }
QToolButton[kind="primary"]:pressed { background: $accent_pressed; }
QToolButton[kind="primary"]:focus   { border: 2px solid $focus; padding: 0 ${sp_4_minus_2}px; }
QToolButton[kind="primary"]:disabled { background: $surface_alt; color: $text_disabled; }
QPushButton[kind="ghost"], QToolButton[kind="ghost"] {
    background: transparent; border: 1px solid transparent;
}
QPushButton[kind="ghost"]:hover, QToolButton[kind="ghost"]:hover { background: $surface_alt; }
QPushButton[kind="danger"] { color: $danger; border-color: $danger; }
QPushButton[kind="danger"]:hover { background: $accent_subtle; }
QPushButton[kind="segment"] {
    border-radius: ${r_sm}px; padding: 0 ${sp_3}px; min-height: ${segment_h}px;
}
QPushButton[kind="segment"]:checked {
    background: $accent_subtle; border-color: $accent; color: $text;
}
QPushButton[kind="busy"] { color: $text_muted; }
/* focus must not change geometry: 2 px ring, padding reduced by the extra
   border width; rules below win over the generic :focus rule by order */
QPushButton[kind="segment"]:focus { border: 2px solid $focus; padding: 0 ${sp_3_minus_1}px; }
QPushButton[kind="ghost"]:focus, QToolButton[kind="ghost"]:focus { border: 2px solid $focus; }
QPushButton[kind="danger"]:focus { border-color: $focus; }
QToolButton:focus { padding: 0 ${sp_2_minus_1}px; }

/* ---- text fields ------------------------------------------------------ */
QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox, QComboBox {
    background: $field_bg;
    color: $text;
    border: 1px solid $border_strong;
    border-radius: ${r_sm}px;
    padding: 0 ${sp_2}px;
    min-height: ${field_h}px;
    selection-background-color: $selection_bg;
    selection-color: $selection_text;
}
QPlainTextEdit, QTextEdit { padding: ${sp_1}px ${sp_2}px; font-family: "$mono_family"; }
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QAbstractSpinBox:focus, QComboBox:focus {
    border: 2px solid $focus; padding: 0 ${sp_2_minus_1}px;
}
QLineEdit:read-only { background: $surface; border-color: $border; }
QLineEdit:disabled, QAbstractSpinBox:disabled, QComboBox:disabled, QPlainTextEdit:disabled {
    background: $surface; color: $text_disabled; border-color: $border;
}
QLineEdit[invalid="true"], QAbstractSpinBox[invalid="true"],
QPlainTextEdit[invalid="true"] { border: 2px solid $danger; }
QLineEdit::placeholder { color: $text_muted; }

/* ---- spin boxes ------------------------------------------------------- */
QAbstractSpinBox { padding-right: ${spin_btn_w}px; }
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {
    subcontrol-origin: border;
    width: ${spin_btn_w}px;
    border: none;
    background: transparent;
}
QAbstractSpinBox::up-button   { subcontrol-position: top right; }
QAbstractSpinBox::down-button { subcontrol-position: bottom right; }
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover { background: $surface_alt; }
QAbstractSpinBox::up-arrow, QAbstractSpinBox::down-arrow { width: 8px; height: 8px; }
$spin_arrows

/* ---- combo box -------------------------------------------------------- */
QComboBox { padding-right: ${combo_btn_w}px; }
QComboBox::drop-down {
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: ${combo_btn_w}px;
    border: none;
    border-left: 1px solid $border;
}
QComboBox::down-arrow { width: 10px; height: 10px; $combo_arrow }
QComboBox QAbstractItemView {
    background: $surface;
    color: $text;
    border: 1px solid $border_strong;
    border-radius: ${r_sm}px;
    padding: ${sp_1}px;
    outline: 0;
    selection-background-color: $accent_subtle;
    selection-color: $text;
}
QComboBox QAbstractItemView::item { min-height: ${segment_h}px; padding: 0 ${sp_2}px; }

/* ---- check / radio ---------------------------------------------------- */
QCheckBox, QRadioButton { spacing: ${sp_2}px; min-height: ${segment_h}px; }
QCheckBox::indicator, QRadioButton::indicator {
    width: ${indicator}px; height: ${indicator}px;
    border: 1px solid $border_strong;
    background: $field_bg;
}
QCheckBox::indicator    { border-radius: ${r_sm}px; }
QRadioButton::indicator { border-radius: ${indicator_half}px; }
QCheckBox::indicator:hover, QRadioButton::indicator:hover { border-color: $text_muted; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background: $accent; border-color: $accent; $check_image
}
QRadioButton::indicator:checked { $radio_image }
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {
    background: $surface; border-color: $border;
}
QCheckBox:focus, QRadioButton:focus { outline: none; }
QCheckBox::indicator:focus, QRadioButton::indicator:focus { border: 2px solid $focus; }

/* ---- slider ----------------------------------------------------------- */
QSlider::groove:horizontal { height: 4px; background: $border_strong; border-radius: 2px; }
QSlider::sub-page:horizontal { background: $accent; border-radius: 2px; }
QSlider::handle:horizontal {
    width: 16px; height: 16px; margin: -6px 0;
    background: $text; border: 2px solid $surface; border-radius: 8px;
}
QSlider::handle:horizontal:hover { background: $focus; }

/* ---- progress bar ----------------------------------------------------- */
QProgressBar {
    background: $surface_alt; color: $text;
    border: none; border-radius: ${r_sm}px;
    min-height: 8px; max-height: 8px; text-align: center;
}
/* pasek z widocznym „%p%" musi być wyższy niż 8 px, inaczej tekst jest ucięty */
QProgressBar[kind="labeled"] { min-height: 18px; max-height: 18px; }
QProgressBar::chunk { background: $accent; border-radius: ${r_sm}px; }
QProgressBar[role="danger"]::chunk  { background: $danger; }
QProgressBar[role="success"]::chunk { background: $success; }

/* ---- scroll bars ------------------------------------------------------ */
QScrollBar:vertical {
    background: transparent; width: ${scrollbar}px; margin: 0;
}
QScrollBar::handle:vertical {
    background: $border_strong; border-radius: ${scrollbar_half}px; min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: $text_muted; }
QScrollBar:horizontal {
    background: transparent; height: ${scrollbar}px; margin: 0;
}
QScrollBar::handle:horizontal {
    background: $border_strong; border-radius: ${scrollbar_half}px; min-width: 24px;
}
QScrollBar::handle:horizontal:hover { background: $text_muted; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; border: none; background: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }

/* ---- scroll area / splitter ------------------------------------------ */
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QSplitter::handle { background: $border; }
QSplitter::handle:horizontal { width: 1px; margin: 0 ${sp_1}px; }
QSplitter::handle:vertical   { height: 1px; margin: ${sp_1}px 0; }
QSplitter::handle:hover { background: $accent; }

/* ---- tabs ------------------------------------------------------------- */
QTabWidget::pane { border: none; border-top: 1px solid $border; top: -1px; }
QTabBar::tab {
    background: transparent; color: $text_muted;
    border: none; border-bottom: 2px solid transparent;
    padding: ${sp_2}px ${sp_3}px; margin-right: ${sp_1}px;
}
QTabBar::tab:hover    { color: $text; }
QTabBar::tab:selected { color: $text; border-bottom: 2px solid $accent; }
QTabBar::tab:focus    { border: 2px solid $focus; border-radius: ${r_sm}px; }

/* ---- menu / status bar / toolbar ------------------------------------- */
QMenu {
    background: $surface; color: $text;
    border: 1px solid $border_strong; border-radius: ${r_lg}px; padding: ${sp_1}px;
}
QMenu::item { padding: ${sp_1}px ${sp_6}px ${sp_1}px ${sp_3}px; border-radius: ${r_sm}px; }
QMenu::item:selected { background: $accent_subtle; }
QMenu::item:disabled { color: $text_disabled; }
QMenu::separator { height: 1px; background: $border; margin: ${sp_1}px ${sp_2}px; }
QStatusBar { background: $surface; color: $text_muted; border-top: 1px solid $border; }
QStatusBar::item { border: none; }
QStatusBar QLabel[role="danger"]  { color: $danger; }
QStatusBar QLabel[role="success"] { color: $success; }
QStatusBar QLabel[role="warning"] { color: $warning; }
QToolBar { background: $surface; border: none; border-bottom: 1px solid $border; spacing: ${sp_2}px; padding: ${sp_1}px ${sp_3}px; }
QToolBar::separator { width: 1px; background: $border; margin: ${sp_1}px ${sp_2}px; }

/* ---- lists / tables --------------------------------------------------- */
QListView, QTreeView, QTableView {
    background: $surface; alternate-background-color: $surface_alt;
    border: 1px solid $border; border-radius: ${r_sm}px; outline: 0;
}
QListView::item:selected, QTreeView::item:selected, QTableView::item:selected {
    background: $accent_subtle; color: $text;
}
QListView::item:selected:active, QTreeView::item:selected:active, QTableView::item:selected:active {
    background: $selection_bg; color: $selection_text;
}
QHeaderView::section {
    background: $surface_alt; color: $text_muted; border: none;
    border-bottom: 1px solid $border; padding: ${sp_1}px ${sp_2}px;
}

/* ---- dialogs ---------------------------------------------------------- */
QMessageBox { background: $surface; }
QDialogButtonBox QPushButton { min-width: 80px; }

/* ---- generic surfaces / role containers ------------------------------- */
QFrame[role="panel"] { background: $surface; border: 1px solid $border; border-radius: ${r_lg}px; }
QFrame[role="separator"] { background: $border; max-height: 1px; min-height: 1px; border: none; }
QWidget[role="inspector"] { background: $surface; }
/* podgląd wideo: ciemne/neutralne płótno pod letterboxem, tekst zastępczy muted */
QLabel[role="preview"] { background: $bg; color: $text_muted; }
"""


def _svg_data(kind: str, color: str) -> str:
    """Return SVG markup for a small monochrome glyph."""
    if kind == "check":
        return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
                f'<path d="M3 8.5l3.2 3.2L13 4.8" fill="none" stroke="{color}" '
                'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>')
    if kind == "dot":
        return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
                f'<circle cx="8" cy="8" r="3.2" fill="{color}"/></svg>')
    if kind == "down":
        return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
                f'<path d="M3.5 6l4.5 4.5L12.5 6" fill="none" stroke="{color}" '
                'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>')
    if kind == "up":
        return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
                f'<path d="M3.5 10l4.5-4.5L12.5 10" fill="none" stroke="{color}" '
                'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>')
    raise ValueError(kind)


def write_indicator_svgs(tokens: dict[str, str], mode: str) -> dict[str, str]:
    """Write tiny SVG glyphs (check, radio dot, arrows) to a temp dir.

    QSS ``image: url(...)`` accepts file paths (data: URLs do not work), so the
    glyphs are materialised on disk once per theme mode. Returns a mapping
    glyph -> path with forward slashes. Rendering them requires the Qt SVG
    image format plugin (PyInstaller: include ``imageformats/qsvg``). If the
    plugin is missing, the indicators still show state by colour alone.
    """
    import tempfile

    out: dict[str, str] = {}
    try:
        base = os.path.join(tempfile.gettempdir(), f"qt_theme_glyphs_{mode}")
        os.makedirs(base, exist_ok=True)
        glyphs = {
            "check": _svg_data("check", tokens["accent_text"]),
            "dot": _svg_data("dot", tokens["accent_text"]),
            "down": _svg_data("down", tokens["text_muted"]),
            "up": _svg_data("up", tokens["text_muted"]),
        }
        for name, svg in glyphs.items():
            path = os.path.join(base, f"{name}.svg")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(svg)
            out[name] = path.replace("\\", "/")
    except OSError:
        return {}
    return out


def build_qss(tokens: dict[str, str], spacing: dict[str, int] | None = None,
              radius: dict[str, int] | None = None, font_family: str = "Segoe UI",
              font_size: int = 10, mono_family: str = "Consolas",
              glyphs: dict[str, str] | None = None, mode: str = "dark") -> str:
    """Render the application stylesheet from tokens.

    ``glyphs`` is the mapping returned by :func:`write_indicator_svgs`; when
    empty, indicators rely on colour only and combo arrows stay Fusion's.
    """
    from string import Template

    sp = dict(SPACING if spacing is None else spacing)
    rd = dict(RADIUS if radius is None else radius)
    g = glyphs or {}
    # In DARK fields are lighter than the panel; in LIGHT they are white like it.
    field_bg = tokens["surface_alt"] if mode == "dark" else tokens["surface"]

    values: dict[str, Any] = dict(tokens)
    values.update(sp)
    values.update(rd)
    values.update({
        "font_family": font_family,
        "mono_family": mono_family,
        "font_size": font_size,
        "font_small": FONT_FAMILIES["font_ui_small"]["size"],
        "font_section": FONT_FAMILIES["font_section"]["size"],
        "font_title": FONT_FAMILIES["font_title"]["size"],
        "field_bg": field_bg,
        "control_h": CONTROL_HEIGHT - 2,       # border adds 2 px
        "field_h": CONTROL_HEIGHT - 2,
        "segment_h": CONTROL_HEIGHT - 6,
        "indicator": INDICATOR_SIZE,
        "indicator_half": INDICATOR_SIZE // 2,
        "scrollbar": SCROLLBAR_WIDTH,
        "scrollbar_half": SCROLLBAR_WIDTH // 2,
        "spin_btn_w": 18,
        "combo_btn_w": 24,
        "sp_2_minus_1": sp["sp_2"] - 1,
        "sp_3_minus_1": sp["sp_3"] - 1,
        "sp_4_minus_2": sp["sp_4"] - 2,
        "check_image": f'image: url("{g["check"]}");' if "check" in g else "",
        "radio_image": f'image: url("{g["dot"]}");' if "dot" in g else "",
        "combo_arrow": f'image: url("{g["down"]}");' if "down" in g else "",
        "spin_arrows": (
            f'QAbstractSpinBox::up-arrow {{ image: url("{g["up"]}"); }}\n'
            f'QAbstractSpinBox::down-arrow {{ image: url("{g["down"]}"); }}'
            if "up" in g and "down" in g else ""
        ),
    })
    return Template(_QSS_TEMPLATE).substitute(values)


# ---------------------------------------------------------------------------
# Applying the theme
# ---------------------------------------------------------------------------

def ensure_svg_support() -> bool:
    """Make the SVG image-format plugin loadable (QSS ``image: url(x.svg)``,
    ``QIcon("x.svg")``).

    With pip-installed PySide6 the ``qsvg`` imageformat plugin resolves its
    Qt6Svg dependency only after ``PySide6.QtSvg`` has been imported once;
    without this import ``QImageReader.supportedImageFormats()`` lacks "svg"
    and every SVG silently renders as nothing. PyInstaller builds need the
    plugin bundled (see references/qt-pyside6.md §10).
    """
    try:
        import PySide6.QtSvg  # noqa: F401
        return True
    except ImportError:
        return False


def apply_theme(app: Any, mode: str = "dark") -> dict[str, Any]:
    """Apply Fusion + QPalette + QSS + default font to ``app``.

    Safe to call again at runtime to switch modes; existing widgets restyle on
    the next paint because the stylesheet lives on QApplication. Returns a dict
    with ``mode``, ``tokens``, ``qss``, ``font_family``, ``mono_family``.
    """
    if mode not in TOKENS:
        raise ValueError(f"unknown theme mode: {mode!r}")
    tokens = TOKENS[mode]
    ensure_svg_support()
    ui_family = pick_font_family(FONT_FAMILIES["font_ui"]["families"])
    mono_family = pick_font_family(FONT_FAMILIES["font_mono"]["families"])
    glyphs = write_indicator_svgs(tokens, mode)
    qss = build_qss(tokens, SPACING, RADIUS, ui_family,
                    FONT_FAMILIES["font_ui"]["size"], mono_family, glyphs, mode)

    app.setStyle("Fusion")
    app.setPalette(build_palette(tokens))
    app.setFont(make_font("font_ui"))
    app.setStyleSheet(qss)
    app.setProperty("theme_mode", mode)
    for w in app.topLevelWidgets():
        repolish(w)
        if w.isVisible():
            set_windows_dark_titlebar(w, mode == "dark")
    return {"mode": mode, "tokens": tokens, "qss": qss,
            "font_family": ui_family, "mono_family": mono_family}


def current_tokens(app: Any) -> dict[str, str]:
    """Tokens of the mode last applied with :func:`apply_theme` (default dark)."""
    return TOKENS[app.property("theme_mode") or "dark"]


def repolish(widget: Any) -> None:
    """Re-run style polishing on ``widget`` and all descendants.

    Required after ``setProperty("kind"/"role"/"invalid", ...)`` so that QSS
    attribute selectors are re-evaluated; a plain ``update()`` is not enough.
    """
    from PySide6.QtWidgets import QWidget

    for w in [widget, *widget.findChildren(QWidget)]:
        st = w.style()
        st.unpolish(w)
        st.polish(w)
        w.update()


def set_property_and_repolish(widget: Any, name: str, value: Any) -> None:
    """``setProperty`` + repolish of that widget only (cheap, use in handlers)."""
    widget.setProperty(name, value)
    st = widget.style()
    st.unpolish(widget)
    st.polish(widget)
    widget.update()


# ---------------------------------------------------------------------------
# Windows integration
# ---------------------------------------------------------------------------

def set_windows_dark_titlebar(widget: Any, enabled: bool = True) -> bool:
    """Ask DWM to draw a dark (or light) title bar for a top-level widget.

    Uses DWMWA_USE_IMMERSIVE_DARK_MODE = 20 (Windows 10 20H1+) with fallback
    to the pre-release value 19. Call after ``widget.show()`` (the native
    handle must exist) and again after every theme switch. Returns True when
    the attribute was accepted. No-op on other platforms.
    """
    if sys.platform != "win32":
        return False
    try:
        hwnd = int(widget.winId())
        value = ctypes.c_int(1 if enabled else 0)
        dwm = ctypes.windll.dwmapi
        for attr in (20, 19):
            res = dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), ctypes.c_uint(attr),
                                            ctypes.byref(value), ctypes.sizeof(value))
            if res == 0:
                return True
    except (AttributeError, OSError):
        pass
    return False


def set_app_user_model_id(app_id: str) -> bool:
    """Set the Windows AppUserModelID so the taskbar shows the app's own icon
    (not python.exe's) and groups windows correctly. Call before any window
    is shown. No-op elsewhere.
    """
    if sys.platform != "win32":
        return False
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        return True
    except (AttributeError, OSError):
        return False


def system_prefers_dark() -> bool:
    """Best-effort detection of the OS colour scheme.

    Prefers ``QGuiApplication.styleHints().colorScheme()`` (Qt >= 6.5; the
    exact availability depends on the Qt version, check the docs), then the
    Windows registry key ``AppsUseLightTheme``. Defaults to True because the
    tool's default theme is dark.
    """
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication

        hints = QGuiApplication.styleHints()
        scheme = hints.colorScheme()  # version dependent
        if scheme == Qt.ColorScheme.Dark:
            return True
        if scheme == Qt.ColorScheme.Light:
            return False
    except (ImportError, AttributeError):
        pass
    if sys.platform == "win32":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return int(value) == 0
        except OSError:
            pass
    return True


# ---------------------------------------------------------------------------
# Window geometry persistence
# ---------------------------------------------------------------------------

def save_window_state(win: Any, settings: Any, splitter: Any = None,
                      prefix: str = "ui") -> None:
    """Persist geometry (and splitter sizes) into a QSettings instance."""
    settings.setValue(f"{prefix}/geometry", win.saveGeometry())
    if hasattr(win, "saveState"):
        settings.setValue(f"{prefix}/state", win.saveState())
    if splitter is not None:
        settings.setValue(f"{prefix}/splitter", splitter.saveState())


def restore_window_state(win: Any, settings: Any, splitter: Any = None,
                         prefix: str = "ui") -> bool:
    """Restore what :func:`save_window_state` stored. Returns True if geometry
    was found. Call before ``show()``; keep a sane ``resize`` fallback."""
    geo = settings.value(f"{prefix}/geometry")
    ok = bool(geo) and bool(win.restoreGeometry(geo))
    state = settings.value(f"{prefix}/state")
    if state and hasattr(win, "restoreState"):
        win.restoreState(state)
    if splitter is not None:
        sp = settings.value(f"{prefix}/splitter")
        if sp:
            splitter.restoreState(sp)
    return ok


