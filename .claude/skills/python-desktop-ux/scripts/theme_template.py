"""Reusable ttk theme module for modern-looking Tkinter desktop apps.

Copy this file next to your application and call, in this order:

    enable_hidpi()                 # BEFORE tk.Tk()
    root = tk.Tk()
    tokens = apply_theme(root, mode="dark")
    set_windows_dark_titlebar(root, enabled=True)

Only the standard library is required. Pillow is optional (used by the
demo for a rounded button sample if available).

Color values below are WORKING values for development.
source of truth: references/design-tokens.md
"""
from __future__ import annotations

import ctypes
import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import Any, Callable

try:  # Pillow is optional
    from PIL import Image, ImageDraw, ImageTk  # type: ignore
    HAS_PIL = True
except Exception:  # pragma: no cover - optional dependency
    HAS_PIL = False

IS_WINDOWS = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

# ---------------------------------------------------------------------------
# Tokens
# source of truth: references/design-tokens.md
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

# Spacing in px at 96 dpi. Scale with px() when drawing on Canvas.
SPACING: dict[str, int] = {
    "sp_1": 4,
    "sp_2": 8,
    "sp_3": 12,
    "sp_4": 16,
    "sp_5": 20,
    "sp_6": 24,
    "sp_8": 32,
}

RADIUS: dict[str, int] = {"r_sm": 4, "r_md": 6, "r_lg": 8}

# Candidate families, first available wins.
FONT_FAMILIES: dict[str, list[str]] = {
    "ui": ["Segoe UI Variable Text", "Segoe UI", "TkDefaultFont"],
    "mono": ["Cascadia Mono", "Consolas", "TkFixedFont"],
}

FONT_SIZES: dict[str, int] = {
    "font_ui": 10,
    "font_ui_small": 9,
    "font_section": 11,
    "font_title": 13,
    "font_mono": 10,
}

# Module state so apply_theme() can be called repeatedly.
_STATE: dict[str, Any] = {"fonts_ready": False, "mode": None, "images": {}}


# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------
def pick_font_family(root: tk.Misc, candidates: list[str]) -> str:
    """Return the first candidate present in tkinter.font.families().

    Comparison is case-insensitive. Names starting with "Tk" (named fonts
    such as TkDefaultFont) are resolved to their actual family. Falls back
    to the last candidate.
    """
    available = {name.lower() for name in tkfont.families(root)}
    for name in candidates:
        if name.startswith("Tk"):
            try:
                return tkfont.nametofont(name).actual("family")
            except tk.TclError:
                continue
        if name.lower() in available:
            return name
    return candidates[-1]


def configure_named_fonts(root: tk.Misc, tokens: dict[str, str] | None = None) -> dict[str, tkfont.Font]:
    """Configure Tk named fonts and create the app fonts (font_ui, ...).

    Named fonts are the only fonts that update live everywhere when
    reconfigured, so widgets should reference them by name, not tuples.
    Returns a mapping token name -> tkfont.Font.
    """
    ui_family = pick_font_family(root, FONT_FAMILIES["ui"])
    mono_family = pick_font_family(root, FONT_FAMILIES["mono"])

    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont",
                 "TkCaptionFont", "TkIconFont"):
        try:
            tkfont.nametofont(name).configure(family=ui_family, size=FONT_SIZES["font_ui"])
        except tk.TclError:
            pass
    for name in ("TkTooltipFont", "TkSmallCaptionFont"):
        try:
            tkfont.nametofont(name).configure(family=ui_family, size=FONT_SIZES["font_ui_small"])
        except tk.TclError:
            pass
    try:
        tkfont.nametofont("TkFixedFont").configure(family=mono_family, size=FONT_SIZES["font_mono"])
    except tk.TclError:
        pass

    spec = {
        "font_ui": (ui_family, FONT_SIZES["font_ui"], "normal"),
        "font_ui_small": (ui_family, FONT_SIZES["font_ui_small"], "normal"),
        "font_section": (ui_family, FONT_SIZES["font_section"], "bold"),
        "font_title": (ui_family, FONT_SIZES["font_title"], "bold"),
        "font_mono": (mono_family, FONT_SIZES["font_mono"], "normal"),
    }
    fonts: dict[str, tkfont.Font] = {}
    for name, (family, size, weight) in spec.items():
        if _STATE["fonts_ready"]:
            try:
                font = tkfont.nametofont(name)
                font.configure(family=family, size=size, weight=weight)
                fonts[name] = font
                continue
            except tk.TclError:
                pass
        fonts[name] = tkfont.Font(root, name=name, family=family, size=size, weight=weight)
    _STATE["fonts_ready"] = True
    return fonts


# ---------------------------------------------------------------------------
# DPI
# ---------------------------------------------------------------------------
def enable_hidpi() -> bool:
    """Make the process DPI aware on Windows. Call BEFORE tk.Tk().

    Tries per-monitor awareness, then system awareness. Returns True when
    any call succeeded. Safe no-op on other platforms.
    """
    if not IS_WINDOWS:
        return False
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor
        return True
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # system
        return True
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
        return True
    except Exception:
        return False


def get_scale(root: tk.Misc) -> float:
    """Return the UI scale factor (DPI / 96), e.g. 1.25 at 125 %."""
    try:
        dpi = float(root.winfo_fpixels("1i"))
    except tk.TclError:
        dpi = 96.0
    return max(0.5, dpi / 96.0)


def px(root: tk.Misc, value: float) -> int:
    """Scale a 96 dpi pixel value to the current DPI (rounded, min 1)."""
    return max(1, int(round(value * get_scale(root))))


def apply_tk_scaling(root: tk.Misc) -> float:
    """Sync Tk's own scaling with the real DPI so point sizes are right."""
    try:
        dpi = float(root.winfo_fpixels("1i"))
        root.tk.call("tk", "scaling", dpi / 72.0)
        return dpi / 72.0
    except tk.TclError:
        return 1.0


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------
def _fixed_map(style: ttk.Style, option: str) -> list:
    """Work around Tk versions where Treeview tag colors were ignored.

    Removes the ('!disabled', '!selected') entries from the default map so
    tag_configure() colors show again.
    """
    return [elm for elm in style.map("Treeview", query_opt=option)
            if elm[:2] != ("!disabled", "!selected")]


def _apply_option_db(root: tk.Misc, t: dict[str, str], fonts: dict[str, tkfont.Font]) -> None:
    """Set defaults for classic tk widgets that ttk.Style does not reach."""
    add = root.option_add
    # Combobox dropdown list (a tk.Listbox inside the popdown Toplevel)
    add("*TCombobox*Listbox.background", t["surface"])
    add("*TCombobox*Listbox.foreground", t["text"])
    add("*TCombobox*Listbox.selectBackground", t["selection_bg"])
    add("*TCombobox*Listbox.selectForeground", t["selection_text"])
    add("*TCombobox*Listbox.font", "font_ui")
    add("*TCombobox*Listbox.borderWidth", 0)
    # Plain tk widgets
    add("*Listbox.background", t["surface"])
    add("*Listbox.foreground", t["text"])
    add("*Listbox.selectBackground", t["selection_bg"])
    add("*Listbox.selectForeground", t["selection_text"])
    add("*Listbox.borderWidth", 0)
    add("*Listbox.highlightThickness", 0)
    add("*Text.background", t["surface"])
    add("*Text.foreground", t["text"])
    add("*Text.insertBackground", t["text"])
    add("*Text.selectBackground", t["selection_bg"])
    add("*Text.selectForeground", t["selection_text"])
    add("*Text.borderWidth", 0)
    add("*Text.highlightThickness", 0)
    add("*Text.font", "font_ui")
    add("*Canvas.background", t["bg"])
    add("*Canvas.highlightThickness", 0)
    add("*Toplevel.background", t["bg"])
    add("*Frame.background", t["bg"])
    add("*Label.background", t["bg"])
    add("*Label.foreground", t["text"])
    # Menus (tk only; the menubar itself is drawn natively on Windows)
    add("*Menu.background", t["surface"])
    add("*Menu.foreground", t["text"])
    add("*Menu.activeBackground", t["accent_subtle"])
    add("*Menu.activeForeground", t["text"])
    add("*Menu.disabledForeground", t["text_disabled"])
    add("*Menu.selectColor", t["accent"])
    add("*Menu.borderWidth", 0)
    add("*Menu.activeBorderWidth", 0)
    add("*Menu.relief", "flat")
    add("*Menu.tearOff", 0)
    add("*Menu.font", "font_ui")


def _retint_tk_widgets(widget: tk.Misc, t: dict[str, str]) -> None:
    """Re-color already created tk (non-ttk) widgets after a theme switch."""
    try:
        cls = widget.winfo_class()
        if cls in ("Frame", "Toplevel", "Tk", "Canvas"):
            widget.configure(background=t["bg"])
        elif cls in ("Listbox", "Text"):
            widget.configure(background=t["surface"], foreground=t["text"],
                             selectbackground=t["selection_bg"],
                             selectforeground=t["selection_text"])
            if cls == "Text":
                widget.configure(insertbackground=t["text"])
        elif cls == "Label":
            widget.configure(background=t["bg"], foreground=t["text"])
        elif cls == "Menu":
            widget.configure(background=t["surface"], foreground=t["text"],
                             activebackground=t["accent_subtle"],
                             activeforeground=t["text"])
    except tk.TclError:
        pass
    for child in widget.winfo_children():
        _retint_tk_widgets(child, t)


def apply_theme(root: tk.Misc, mode: str = "dark") -> dict[str, str]:
    """Apply the flat theme to the whole Tk interpreter.

    Safe to call repeatedly (e.g. to switch dark/light at runtime).
    Returns the active token dictionary.
    """
    if mode not in TOKENS:
        raise ValueError("mode must be one of: " + ", ".join(TOKENS))
    t = TOKENS[mode]
    _STATE["mode"] = mode
    apply_tk_scaling(root)
    fonts = configure_named_fonts(root, t)
    style = ttk.Style(root)
    style.theme_use("clam")
    s = get_scale(root)
    p1, p2, p3 = px(root, 4), px(root, 8), px(root, 12)

    # --- base -------------------------------------------------------------
    style.configure(".", background=t["bg"], foreground=t["text"],
                    fieldbackground=t["surface"], bordercolor=t["border"],
                    lightcolor=t["surface"], darkcolor=t["surface"],
                    troughcolor=t["surface_alt"], selectbackground=t["selection_bg"],
                    selectforeground=t["selection_text"], insertcolor=t["text"],
                    focuscolor=t["focus"], font="font_ui", borderwidth=1, relief="flat")
    style.map(".", foreground=[("disabled", t["text_disabled"])])

    # --- frames and labels ------------------------------------------------
    style.configure("TFrame", background=t["bg"])
    style.configure("Card.TFrame", background=t["surface"], bordercolor=t["border"],
                    relief="solid", borderwidth=1)
    style.configure("Sidebar.TFrame", background=t["surface"])
    style.configure("TLabel", background=t["bg"], foreground=t["text"], padding=0)
    style.configure("Title.TLabel", font="font_title")
    style.configure("Section.TLabel", font="font_section", foreground=t["text"])
    style.configure("Muted.TLabel", foreground=t["text_muted"], font="font_ui_small")
    style.configure("Card.TLabel", background=t["surface"])
    style.configure("Sidebar.TLabel", background=t["surface"])

    # --- buttons ----------------------------------------------------------
    btn_pad = (p3, p2 - 2 if p2 > 2 else p2)
    style.configure("TButton", background=t["surface_alt"], foreground=t["text"],
                    bordercolor=t["border"], lightcolor=t["surface_alt"],
                    darkcolor=t["surface_alt"], focuscolor=t["surface_alt"],
                    focusthickness=1, borderwidth=1, relief="flat",
                    padding=btn_pad, anchor="center", width=-8)
    style.map("TButton",
              background=[("disabled", t["surface"]), ("pressed", t["border_strong"]),
                          ("active", t["border"])],
              lightcolor=[("pressed", t["border_strong"]), ("active", t["border"])],
              darkcolor=[("pressed", t["border_strong"]), ("active", t["border"])],
              bordercolor=[("disabled", t["border"]), ("focus", t["focus"])],
              focuscolor=[("focus", t["focus"])],
              foreground=[("disabled", t["text_disabled"])])
    style.configure("Accent.TButton", background=t["accent"], foreground=t["accent_text"],
                    bordercolor=t["accent"], lightcolor=t["accent"], darkcolor=t["accent"],
                    focuscolor=t["accent"], font="font_ui")
    style.map("Accent.TButton",
              background=[("disabled", t["surface_alt"]), ("pressed", t["accent_pressed"]),
                          ("active", t["accent_hover"])],
              lightcolor=[("pressed", t["accent_pressed"]), ("active", t["accent_hover"])],
              darkcolor=[("pressed", t["accent_pressed"]), ("active", t["accent_hover"])],
              bordercolor=[("disabled", t["border"]), ("focus", t["text"]),
                           ("pressed", t["accent_pressed"]), ("active", t["accent_hover"])],
              focuscolor=[("focus", t["accent_text"])],
              foreground=[("disabled", t["text_disabled"])])
    style.configure("Ghost.TButton", background=t["bg"], bordercolor=t["bg"],
                    lightcolor=t["bg"], darkcolor=t["bg"], focuscolor=t["bg"])
    style.map("Ghost.TButton",
              background=[("disabled", t["bg"]), ("pressed", t["surface_alt"]),
                          ("active", t["surface"])],
              lightcolor=[("pressed", t["surface_alt"]), ("active", t["surface"])],
              darkcolor=[("pressed", t["surface_alt"]), ("active", t["surface"])],
              bordercolor=[("focus", t["focus"]), ("pressed", t["surface_alt"]),
                           ("active", t["surface"])],
              focuscolor=[("focus", t["focus"])])
    style.configure("Danger.TButton", background=t["surface"], foreground=t["danger"],
                    bordercolor=t["danger"], lightcolor=t["surface"], darkcolor=t["surface"],
                    focuscolor=t["surface"])
    style.map("Danger.TButton",
              background=[("disabled", t["surface"]), ("pressed", t["danger"]),
                          ("active", t["danger"])],
              lightcolor=[("pressed", t["danger"]), ("active", t["danger"])],
              darkcolor=[("pressed", t["danger"]), ("active", t["danger"])],
              foreground=[("disabled", t["text_disabled"]), ("pressed", "#FFFFFF"),
                          ("active", "#FFFFFF")],
              focuscolor=[("focus", t["focus"])])
    style.configure("Toolbutton", background=t["bg"], foreground=t["text"], padding=p1,
                    relief="flat", borderwidth=0)
    style.map("Toolbutton",
              background=[("disabled", t["bg"]), ("selected", t["accent_subtle"]),
                          ("pressed", t["surface_alt"]), ("active", t["surface"])])
    style.configure("TMenubutton", background=t["surface_alt"], foreground=t["text"],
                    bordercolor=t["border"], lightcolor=t["surface_alt"],
                    darkcolor=t["surface_alt"], arrowcolor=t["text_muted"], padding=btn_pad,
                    relief="flat")
    style.map("TMenubutton", background=[("active", t["border"])])

    # --- entries ----------------------------------------------------------
    field_pad = (p2, p1 + 1)
    for name in ("TEntry", "TSpinbox", "TCombobox"):
        style.configure(name, fieldbackground=t["surface"], foreground=t["text"],
                        bordercolor=t["border"], lightcolor=t["surface"],
                        darkcolor=t["surface"], insertcolor=t["text"], padding=field_pad,
                        selectbackground=t["selection_bg"], selectforeground=t["selection_text"],
                        arrowcolor=t["text_muted"], arrowsize=px(root, 14),
                        background=t["surface"])
        style.map(name,
                  fieldbackground=[("disabled", t["bg"]), ("readonly", t["surface_alt"])],
                  foreground=[("disabled", t["text_disabled"])],
                  bordercolor=[("invalid", t["danger"]), ("focus", t["focus"]),
                               ("hover", t["border_strong"])],
                  lightcolor=[("focus", t["focus"])],
                  darkcolor=[("focus", t["focus"])],
                  arrowcolor=[("disabled", t["text_disabled"]), ("pressed", t["accent"]),
                              ("active", t["text"])],
                  background=[("pressed", t["surface_alt"]), ("active", t["surface_alt"])])
    style.configure("Invalid.TEntry", bordercolor=t["danger"], lightcolor=t["danger"],
                    darkcolor=t["danger"])
    style.map("Invalid.TEntry", bordercolor=[("focus", t["danger"])],
              lightcolor=[("focus", t["danger"])], darkcolor=[("focus", t["danger"])])

    # --- check / radio ------------------------------------------------------
    for name in ("TCheckbutton", "TRadiobutton"):
        style.configure(name, background=t["bg"], foreground=t["text"], padding=(0, p1),
                        indicatorbackground=t["surface"], indicatorforeground=t["accent_text"],
                        indicatorcolor=t["surface"], indicatormargin=(0, 0, p2, 0),
                        upperbordercolor=t["border_strong"], lowerbordercolor=t["border_strong"],
                        focuscolor=t["bg"])
        style.map(name,
                  indicatorbackground=[("disabled", t["bg"]), ("selected", t["accent"]),
                                       ("active", t["surface_alt"])],
                  indicatorcolor=[("disabled", t["bg"]), ("selected", t["accent"])],
                  indicatorforeground=[("disabled", t["text_disabled"])],
                  upperbordercolor=[("selected", t["accent"]), ("focus", t["focus"])],
                  lowerbordercolor=[("selected", t["accent"]), ("focus", t["focus"])],
                  background=[("active", t["bg"])],
                  foreground=[("disabled", t["text_disabled"])],
                  focuscolor=[("focus", t["focus"])])

    # --- labelframe (kept flat for legacy code; prefer widgets.SectionHeader)
    style.configure("TLabelframe", background=t["bg"], bordercolor=t["border"],
                    lightcolor=t["bg"], darkcolor=t["bg"], borderwidth=0, relief="flat",
                    labelmargins=(0, 0, 0, p1), padding=(0, p1, 0, p2))
    style.configure("TLabelframe.Label", background=t["bg"], foreground=t["text"],
                    font="font_section")

    # --- notebook -----------------------------------------------------------
    style.configure("TNotebook", background=t["bg"], bordercolor=t["bg"], lightcolor=t["bg"],
                    darkcolor=t["bg"], borderwidth=0, tabmargins=(0, 0, 0, 0))
    style.configure("TNotebook.Tab", background=t["bg"], foreground=t["text_muted"],
                    bordercolor=t["bg"], lightcolor=t["bg"], darkcolor=t["bg"],
                    padding=(p3, p2), focuscolor=t["bg"], borderwidth=0)
    style.map("TNotebook.Tab",
              background=[("selected", t["surface"]), ("active", t["surface_alt"])],
              foreground=[("selected", t["text"]), ("disabled", t["text_disabled"])],
              lightcolor=[("selected", t["surface"])],
              bordercolor=[("selected", t["accent"])],
              expand=[("selected", (0, 0, 0, 0))])

    # --- treeview -----------------------------------------------------------
    row_h = px(root, 26)
    style.configure("Treeview", background=t["surface"], fieldbackground=t["surface"],
                    foreground=t["text"], bordercolor=t["border"], lightcolor=t["surface"],
                    darkcolor=t["surface"], borderwidth=0, rowheight=row_h, font="font_ui")
    style.map("Treeview",
              background=[("selected", t["selection_bg"])] + _fixed_map(style, "background"),
              foreground=[("selected", t["selection_text"])] + _fixed_map(style, "foreground"))
    style.configure("Treeview.Heading", background=t["surface_alt"], foreground=t["text_muted"],
                    bordercolor=t["border"], lightcolor=t["surface_alt"],
                    darkcolor=t["surface_alt"], relief="flat", padding=(p2, p1 + 2),
                    font="font_ui_small")
    style.map("Treeview.Heading", background=[("active", t["border"])],
              foreground=[("active", t["text"])])
    style.configure("Treeview.Item", indicatormargins=(p1, 0, p1, 0))

    # --- scrollbars ---------------------------------------------------------
    for orient in ("Vertical", "Horizontal"):
        base = orient + ".TScrollbar"
        style.configure(base, background=t["border_strong"], troughcolor=t["bg"],
                        bordercolor=t["bg"], lightcolor=t["border_strong"],
                        darkcolor=t["border_strong"], arrowcolor=t["text_muted"],
                        arrowsize=px(root, 12), gripcount=0, relief="flat", borderwidth=0)
        style.map(base, background=[("disabled", t["surface_alt"]), ("pressed", t["accent"]),
                                    ("active", t["text_muted"])],
                  lightcolor=[("pressed", t["accent"]), ("active", t["text_muted"])],
                  darkcolor=[("pressed", t["accent"]), ("active", t["text_muted"])])
        thin = "Thin." + base
        style.configure(thin, arrowsize=px(root, 8), gripcount=0, borderwidth=0)
        # No arrow buttons, just a trough with a thumb (works in clam).
        trough = orient + ".Scrollbar.trough"
        thumb = orient + ".Scrollbar.thumb"
        sticky = "ns" if orient == "Vertical" else "ew"
        style.layout(thin, [(trough, {"sticky": sticky,
                                      "children": [(thumb, {"expand": 1, "sticky": "nswe"})]})])

    # --- progressbar, scale, separator, paned, sizegrip ---------------------
    for orient in ("Horizontal", "Vertical"):
        style.configure(orient + ".TProgressbar", background=t["accent"],
                        troughcolor=t["surface_alt"], bordercolor=t["surface_alt"],
                        lightcolor=t["accent"], darkcolor=t["accent"], borderwidth=0,
                        thickness=px(root, 6), pbarrelief="flat")
        style.configure(orient + ".TScale", background=t["accent"], troughcolor=t["surface_alt"],
                        bordercolor=t["surface_alt"], lightcolor=t["accent"],
                        darkcolor=t["accent"], sliderlength=px(root, 18), borderwidth=0,
                        sliderrelief="flat", troughrelief="flat")
        style.map(orient + ".TScale", background=[("disabled", t["border_strong"]),
                                                  ("pressed", t["accent_pressed"]),
                                                  ("active", t["accent_hover"])])
    style.configure("TSeparator", background=t["border"])
    style.configure("TPanedwindow", background=t["bg"])
    style.configure("Sash", sashthickness=px(root, 6), gripcount=0, handlesize=0,
                    sashpad=0, bordercolor=t["bg"], lightcolor=t["bg"])
    style.configure("TSizegrip", background=t["bg"])

    # --- classic tk widgets ------------------------------------------------
    _apply_option_db(root, t, fonts)
    try:
        root.configure(bg=t["bg"])
    except tk.TclError:
        pass
    _retint_tk_widgets(root, t)
    return t


def current_tokens() -> dict[str, str]:
    """Tokens of the last applied mode (defaults to dark before apply_theme)."""
    return TOKENS[_STATE["mode"] or "dark"]


# ---------------------------------------------------------------------------
# Windows integration
# ---------------------------------------------------------------------------
def set_windows_dark_titlebar(root: tk.Tk | tk.Toplevel, enabled: bool = True) -> bool:
    """Switch the native title bar to dark (or light) on Windows 10/11.

    Call after the window is mapped (e.g. after root.update_idletasks()).
    Uses DwmSetWindowAttribute with DWMWA_USE_IMMERSIVE_DARK_MODE (20, or
    19 on older builds). Returns True on success, False elsewhere.
    """
    if not IS_WINDOWS:
        return False
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        if not hwnd:
            hwnd = root.winfo_id()
        value = ctypes.c_int(1 if enabled else 0)
        ok = False
        for attr in (20, 19):
            res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
            if res == 0:
                ok = True
                break
        if ok:
            # Force the non-client area to repaint.
            w, h = root.winfo_width(), root.winfo_height()
            if w > 1 and h > 1:
                root.geometry("%dx%d" % (w + 1, h))
                root.update_idletasks()
                root.geometry("%dx%d" % (w, h))
        return ok
    except Exception:
        return False


def system_prefers_dark() -> bool:
    """True when Windows apps are set to dark mode. False on other systems."""
    if not IS_WINDOWS:
        return False
    try:
        import winreg  # type: ignore
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return int(value) == 0
    except Exception:
        return False


def set_window_icon(root: tk.Tk, ico_path: str | None = None, png_path: str | None = None) -> None:
    """Set the window icon: .ico on Windows, PNG via iconphoto elsewhere."""
    try:
        if ico_path and IS_WINDOWS:
            root.iconbitmap(ico_path)
        elif png_path:
            img = tk.PhotoImage(file=png_path)
            root.iconphoto(True, img)
            _STATE["images"]["window_icon"] = img  # keep a reference
    except tk.TclError:
        pass


# ---------------------------------------------------------------------------
# Mouse wheel helper
# ---------------------------------------------------------------------------
def bind_mousewheel(widget: tk.Misc, canvas: tk.Canvas, horizontal_with_shift: bool = True) -> None:
    """Scroll `canvas` with the wheel while the pointer is over `widget`.

    Windows/macOS deliver <MouseWheel> (delta 120 per notch on Windows,
    small values on macOS), X11 delivers <Button-4>/<Button-5>. Binding is
    done with bind_all on <Enter> and released on <Leave> so nested
    scrollable areas do not fight each other.
    """
    def _units(event: tk.Event) -> int:
        delta = getattr(event, "delta", 0)
        if IS_MAC:
            return -1 if delta > 0 else 1
        if delta:
            return -int(delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
        num = getattr(event, "num", 0)
        return -1 if num == 4 else 1

    def _on_wheel(event: tk.Event) -> str:
        units = _units(event)
        shift = bool(getattr(event, "state", 0) & 0x0001)
        if horizontal_with_shift and shift:
            canvas.xview_scroll(units, "units")
        else:
            canvas.yview_scroll(units, "units")
        return "break"

    def _on_enter(_event: tk.Event) -> None:
        widget.bind_all("<MouseWheel>", _on_wheel, add="+")
        widget.bind_all("<Button-4>", _on_wheel, add="+")
        widget.bind_all("<Button-5>", _on_wheel, add="+")

    def _on_leave(_event: tk.Event) -> None:
        widget.unbind_all("<MouseWheel>")
        widget.unbind_all("<Button-4>")
        widget.unbind_all("<Button-5>")

    widget.bind("<Enter>", _on_enter, add="+")
    widget.bind("<Leave>", _on_leave, add="+")


# ---------------------------------------------------------------------------
# Optional: rounded image buttons (needs Pillow)
# ---------------------------------------------------------------------------
def _rounded_image(size: tuple[int, int], radius: int, fill: str, outline: str | None = None,
                   scale: int = 4) -> Any:
    """Draw a rounded rectangle with supersampling and return a PhotoImage."""
    w, h = size
    big = Image.new("RGBA", (w * scale, h * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(big)
    draw.rounded_rectangle((0, 0, w * scale - 1, h * scale - 1), radius=radius * scale,
                           fill=fill, outline=outline, width=scale if outline else 0)
    small = big.resize((w, h), Image.LANCZOS)
    return ImageTk.PhotoImage(small)


def register_rounded_button_style(root: tk.Misc, style_name: str = "Rounded.Accent.TButton",
                                  base_key: str = "accent", text_key: str = "accent_text") -> bool:
    """Create an image-based rounded button style with hover/pressed/disabled.

    Returns False when Pillow is missing. The element name embeds the mode
    so calling again after switching themes registers a fresh element.
    """
    if not HAS_PIL:
        return False
    t = current_tokens()
    style = ttk.Style(root)
    r = px(root, RADIUS["r_md"])
    size = (px(root, 40), px(root, 32))
    key = "%s.%s" % (style_name, _STATE["mode"])
    images = {
        "normal": _rounded_image(size, r, t[base_key]),
        "hover": _rounded_image(size, r, t.get(base_key + "_hover", t["border"])),
        "pressed": _rounded_image(size, r, t.get(base_key + "_pressed", t["border_strong"])),
        "disabled": _rounded_image(size, r, t["surface_alt"]),
    }
    _STATE["images"][key] = images  # keep references alive
    element = "RoundedBtn.%s.%s" % (base_key, _STATE["mode"])
    try:
        style.element_create(element, "image", images["normal"],
                             ("disabled", images["disabled"]),
                             ("pressed", images["pressed"]),
                             ("active", images["hover"]),
                             border=r + 2, sticky="nswe", padding=(px(root, 12), px(root, 6)))
    except tk.TclError:
        pass  # element already exists for this mode
    style.layout(style_name, [(element, {"sticky": "nswe", "children": [
        ("Button.label", {"sticky": "nswe"})]})])
    style.configure(style_name, foreground=t[text_key], background=t["bg"], anchor="center")
    style.map(style_name, foreground=[("disabled", t["text_disabled"])])
    return True


# ---------------------------------------------------------------------------
# Demo gallery
# ---------------------------------------------------------------------------
def _build_demo(root: tk.Tk) -> Callable[[], None]:
    """Build a gallery of every style. Returns a callback that refreshes it."""
    t = current_tokens()
    outer = ttk.Frame(root, padding=SPACING["sp_4"])
    outer.pack(fill="both", expand=True)
    outer.columnconfigure(0, weight=1)

    ttk.Label(outer, text="Theme gallery", style="Title.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Label(outer, text="All ttk styles configured by apply_theme()", style="Muted.TLabel").grid(
        row=1, column=0, sticky="w", pady=(0, SPACING["sp_3"]))

    nb = ttk.Notebook(outer)
    nb.grid(row=2, column=0, sticky="nsew")
    outer.rowconfigure(2, weight=1)

    # Tab 1: controls
    tab1 = ttk.Frame(nb, padding=SPACING["sp_4"])
    nb.add(tab1, text="Controls")
    tab1.columnconfigure(1, weight=1)
    ttk.Label(tab1, text="Buttons", style="Section.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
    row = ttk.Frame(tab1)
    row.grid(row=1, column=0, columnspan=2, sticky="w", pady=(SPACING["sp_1"], SPACING["sp_3"]))
    ttk.Button(row, text="Default").pack(side="left", padx=(0, SPACING["sp_2"]))
    ttk.Button(row, text="Accent", style="Accent.TButton").pack(side="left", padx=(0, SPACING["sp_2"]))
    ttk.Button(row, text="Ghost", style="Ghost.TButton").pack(side="left", padx=(0, SPACING["sp_2"]))
    ttk.Button(row, text="Danger", style="Danger.TButton").pack(side="left", padx=(0, SPACING["sp_2"]))
    ttk.Button(row, text="Disabled", state="disabled").pack(side="left", padx=(0, SPACING["sp_2"]))
    if register_rounded_button_style(root):
        ttk.Button(row, text="Rounded", style="Rounded.Accent.TButton").pack(side="left")

    ttk.Label(tab1, text="Fields", style="Section.TLabel").grid(row=2, column=0, columnspan=2, sticky="w")
    ttk.Label(tab1, text="Entry").grid(row=3, column=0, sticky="w", padx=(0, SPACING["sp_3"]))
    ttk.Entry(tab1).grid(row=3, column=1, sticky="ew", pady=SPACING["sp_1"])
    ttk.Label(tab1, text="Invalid").grid(row=4, column=0, sticky="w")
    ttk.Entry(tab1, style="Invalid.TEntry").grid(row=4, column=1, sticky="ew", pady=SPACING["sp_1"])
    ttk.Label(tab1, text="Spinbox").grid(row=5, column=0, sticky="w")
    ttk.Spinbox(tab1, from_=0, to=100).grid(row=5, column=1, sticky="ew", pady=SPACING["sp_1"])
    ttk.Label(tab1, text="Combobox").grid(row=6, column=0, sticky="w")
    cb = ttk.Combobox(tab1, values=["Small", "Medium", "Large"], state="readonly")
    cb.current(1)
    cb.grid(row=6, column=1, sticky="ew", pady=SPACING["sp_1"])

    ttk.Label(tab1, text="Choices", style="Section.TLabel").grid(row=7, column=0, columnspan=2,
                                                                 sticky="w", pady=(SPACING["sp_3"], 0))
    chk = tk.BooleanVar(value=True)
    ttk.Checkbutton(tab1, text="Show waveform", variable=chk).grid(row=8, column=0, columnspan=2, sticky="w")
    rad = tk.StringVar(value="a")
    rrow = ttk.Frame(tab1)
    rrow.grid(row=9, column=0, columnspan=2, sticky="w")
    ttk.Radiobutton(rrow, text="Left", variable=rad, value="a").pack(side="left", padx=(0, SPACING["sp_3"]))
    ttk.Radiobutton(rrow, text="Center", variable=rad, value="b").pack(side="left", padx=(0, SPACING["sp_3"]))
    ttk.Radiobutton(rrow, text="Right", variable=rad, value="c").pack(side="left")

    ttk.Separator(tab1).grid(row=10, column=0, columnspan=2, sticky="ew", pady=SPACING["sp_3"])
    ttk.Label(tab1, text="Progress and scale", style="Section.TLabel").grid(row=11, column=0, columnspan=2, sticky="w")
    ttk.Progressbar(tab1, value=65).grid(row=12, column=0, columnspan=2, sticky="ew", pady=SPACING["sp_1"])
    ttk.Scale(tab1, from_=0, to=100, value=40).grid(row=13, column=0, columnspan=2, sticky="ew")

    # Tab 2: treeview + scrollbars
    tab2 = ttk.Frame(nb, padding=SPACING["sp_4"])
    nb.add(tab2, text="Data")
    tab2.columnconfigure(0, weight=1)
    tab2.rowconfigure(0, weight=1)
    tree = ttk.Treeview(tab2, columns=("time", "kind"), show="headings", height=8)
    tree.heading("time", text="Time")
    tree.heading("kind", text="Marker")
    tree.column("time", width=px(root, 120), anchor="w")
    tree.column("kind", width=px(root, 200), anchor="w")
    tree.tag_configure("odd", background=t["surface_alt"])
    for i in range(20):
        tree.insert("", "end", values=("%02d:%02d.%03d" % (i // 60, i % 60, i * 37 % 1000),
                                       "START" if i == 0 else "shot %d" % i),
                    tags=("odd",) if i % 2 else ())
    tree.grid(row=0, column=0, sticky="nsew")
    vsb = ttk.Scrollbar(tab2, orient="vertical", command=tree.yview, style="Thin.Vertical.TScrollbar")
    vsb.grid(row=0, column=1, sticky="ns")
    tree.configure(yscrollcommand=vsb.set)
    hsb = ttk.Scrollbar(tab2, orient="horizontal", command=tree.xview)
    hsb.grid(row=1, column=0, sticky="ew")
    tree.configure(xscrollcommand=hsb.set)

    # Footer with mode toggle
    footer = ttk.Frame(outer)
    footer.grid(row=3, column=0, sticky="ew", pady=(SPACING["sp_3"], 0))
    mode_var = tk.StringVar(value=_STATE["mode"] or "dark")
    status = ttk.Label(footer, text="Mode: %s" % mode_var.get(), style="Muted.TLabel")
    status.pack(side="left")

    def toggle() -> None:
        new_mode = "light" if _STATE["mode"] == "dark" else "dark"
        tokens = apply_theme(root, new_mode)
        set_windows_dark_titlebar(root, enabled=(new_mode == "dark"))
        tree.tag_configure("odd", background=tokens["surface_alt"])
        register_rounded_button_style(root)
        status.configure(text="Mode: %s" % new_mode)

    ttk.Button(footer, text="Toggle dark / light", command=toggle, style="Accent.TButton").pack(side="right")
    return toggle


def main() -> None:
    enable_hidpi()
    root = tk.Tk()
    root.title("theme_template demo")
    mode = "dark" if system_prefers_dark() or not IS_WINDOWS else "light"
    apply_theme(root, mode)
    root.minsize(px(root, 560), px(root, 520))
    _build_demo(root)
    root.update_idletasks()
    set_windows_dark_titlebar(root, enabled=(mode == "dark"))
    root.mainloop()


if __name__ == "__main__":
    main()
