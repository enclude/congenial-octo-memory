"""Custom widgets built on ttk and Canvas that follow the design tokens.

Drop-in helpers for inspector-style desktop UIs: section headers instead
of LabelFrame, a form grid with aligned labels, a Switch, a segmented
control, a color swatch button, numeric and path fields, tooltips, a
scrollable frame, a status bar and an inline message.

Works together with theme_template.py (apply_theme). When that module is
missing, every widget accepts a `tokens` dict in its constructor and a
minimal fallback palette is used.

Standard library only. Python 3.10+.
"""
from __future__ import annotations

import os
import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import colorchooser, filedialog, ttk
from typing import Any, Callable, Sequence

try:
    from theme_template import (SPACING, TOKENS, bind_mousewheel, current_tokens, px)
except ImportError:  # standalone fallback; source of truth: references/design-tokens.md
    TOKENS = {"dark": {
        "bg": "#1E1F22", "surface": "#26282C", "surface_alt": "#2E3136", "border": "#3A3D42",
        "border_strong": "#4A4E55", "text": "#E8E8E8", "text_muted": "#A0A4AB",
        "text_disabled": "#6B7078", "accent": "#FFC400", "accent_hover": "#FFD23F",
        "accent_pressed": "#E0AC00", "accent_text": "#1A1A1A", "accent_subtle": "#3A3218",
        "danger": "#F26D6D", "success": "#4CC38A", "warning": "#FFB020", "info": "#6CB4EE",
        "focus": "#FFC400", "selection_bg": "#3A3218", "selection_text": "#FFFFFF"}}
    SPACING = {"sp_1": 4, "sp_2": 8, "sp_3": 12, "sp_4": 16, "sp_5": 20, "sp_6": 24, "sp_8": 32}

    def current_tokens() -> dict[str, str]:
        return TOKENS["dark"]

    def px(root: tk.Misc, value: float) -> int:
        try:
            return max(1, int(round(value * root.winfo_fpixels("1i") / 96.0)))
        except tk.TclError:
            return int(value)

    bind_mousewheel = None  # type: ignore

IS_MAC = sys.platform == "darwin"
KIND_KEYS = {"info": "info", "success": "success", "warning": "warning", "danger": "danger"}


def _tok(tokens: dict[str, str] | None) -> dict[str, str]:
    """Return the given tokens or the active theme tokens."""
    return tokens if tokens is not None else current_tokens()


# ---------------------------------------------------------------------------
# Tooltip
# ---------------------------------------------------------------------------
class Tooltip:
    """Delayed tooltip shown in a borderless Toplevel under the pointer."""

    def __init__(self, widget: tk.Misc, text: str, delay: int = 500,
                 tokens: dict[str, str] | None = None) -> None:
        self.widget, self.text, self.delay, self.tokens = widget, text, delay, tokens
        self._after: str | None = None
        self._tip: tk.Toplevel | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")
        widget.bind("<Destroy>", self._hide, add="+")

    def set_text(self, text: str) -> None:
        self.text = text

    def _schedule(self, _event: tk.Event | None = None) -> None:
        self._cancel()
        self._after = self.widget.after(self.delay, self._show)

    def _cancel(self) -> None:
        if self._after is not None:
            try:
                self.widget.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None

    def _show(self) -> None:
        if self._tip is not None or not self.text:
            return
        t = _tok(self.tokens)
        x = self.widget.winfo_pointerx() + px(self.widget, 12)
        y = self.widget.winfo_pointery() + px(self.widget, 18)
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        try:
            tip.attributes("-topmost", True)
        except tk.TclError:
            pass
        tip.configure(background=t["border_strong"])
        label = tk.Label(tip, text=self.text, background=t["surface_alt"], foreground=t["text"],
                         font="TkTooltipFont", justify="left", padx=px(tip, 8), pady=px(tip, 4),
                         wraplength=px(tip, 360))
        label.pack(padx=1, pady=1)
        tip.wm_geometry("+%d+%d" % (x, y))
        self._tip = tip

    def _hide(self, _event: tk.Event | None = None) -> None:
        self._cancel()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None


# ---------------------------------------------------------------------------
# ScrollableFrame
# ---------------------------------------------------------------------------
class ScrollableFrame(ttk.Frame):
    """Vertically scrollable container. Put children into `.inner`.

    Canvas + inner ttk.Frame + thin scrollbar. The inner frame is kept as
    wide as the canvas, so grid weights inside behave normally.
    """

    def __init__(self, parent: tk.Misc, tokens: dict[str, str] | None = None, **kw: Any) -> None:
        super().__init__(parent, **kw)
        t = _tok(tokens)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, background=t["bg"], highlightthickness=0, borderwidth=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview,
                                 style="Thin.Vertical.TScrollbar")
        self.vsb.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.inner = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        if bind_mousewheel is not None:
            bind_mousewheel(self, self.canvas)
        else:
            self._bind_wheel_fallback()

    def apply_tokens(self, tokens: dict[str, str]) -> None:
        self.canvas.configure(background=tokens["bg"])

    def _on_inner_configure(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self._win, width=event.width)

    def _bind_wheel_fallback(self) -> None:
        def on_wheel(event: tk.Event) -> str:
            if getattr(event, "num", 0) == 4 or getattr(event, "delta", 0) > 0:
                self.canvas.yview_scroll(-1, "units")
            else:
                self.canvas.yview_scroll(1, "units")
            return "break"
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind("<Enter>", lambda e, s=seq: self.bind_all(s, on_wheel), add="+")
            self.bind("<Leave>", lambda e, s=seq: self.unbind_all(s), add="+")


# ---------------------------------------------------------------------------
# SectionHeader
# ---------------------------------------------------------------------------
class SectionHeader(ttk.Frame):
    """Flat section title with a rule, optional collapse chevron.

    Replacement for ttk.LabelFrame: put the header in one grid row and the
    section `content` frame in the next; the header hides/shows it.
    """

    def __init__(self, parent: tk.Misc, text: str, collapsible: bool = False,
                 content: tk.Widget | None = None, tokens: dict[str, str] | None = None,
                 expanded: bool = True) -> None:
        super().__init__(parent)
        self.tokens = tokens
        self.content = content
        self.expanded = tk.BooleanVar(value=expanded)
        self.columnconfigure(2, weight=1)
        self.chevron = ttk.Label(self, text="", style="Section.TLabel", width=2)
        self.label = ttk.Label(self, text=text, style="Section.TLabel",
                               takefocus=1 if collapsible else 0)
        self.label.grid(row=0, column=1, sticky="w", padx=(0, SPACING["sp_2"]))
        ttk.Separator(self, orient="horizontal").grid(row=0, column=2, sticky="ew")
        if collapsible:
            self.chevron.grid(row=0, column=0, sticky="w")
            for w in (self, self.chevron, self.label):
                w.bind("<Button-1>", lambda e: self.toggle(), add="+")
            self.label.bind("<space>", lambda e: self.toggle(), add="+")
            self.label.bind("<Return>", lambda e: self.toggle(), add="+")
            self.label.bind("<FocusIn>", lambda e: self._focus(True), add="+")
            self.label.bind("<FocusOut>", lambda e: self._focus(False), add="+")
            self.label.configure(cursor="hand2")
        self._refresh()

    def set_text(self, text: str) -> None:
        self.label.configure(text=text)

    def toggle(self) -> None:
        self.set_expanded(not self.expanded.get())

    def set_expanded(self, value: bool) -> None:
        self.expanded.set(bool(value))
        self._refresh()

    def _focus(self, on: bool) -> None:
        t = _tok(self.tokens)
        self.label.configure(foreground=t["focus"] if on else t["text"])

    def _refresh(self) -> None:
        open_ = self.expanded.get()
        self.chevron.configure(text="▾" if open_ else "▸")
        if self.content is None:
            return
        manager = self.content.winfo_manager()
        if open_:
            if manager == "":
                self.content.grid()
        elif manager == "grid":
            self.content.grid_remove()
        elif manager == "pack":
            self.content.pack_forget()


# ---------------------------------------------------------------------------
# FormGrid
# ---------------------------------------------------------------------------
class FormGrid(ttk.Frame):
    """Two-column form: labels (fixed min width) and stretching controls.

    row(label, factory_or_widget, unit, help_text) places one field.
    Column 2 holds the unit; help text goes under the control in muted type.
    """

    def __init__(self, parent: tk.Misc, label_width: int = 140, **kw: Any) -> None:
        super().__init__(parent, **kw)
        self.columnconfigure(0, minsize=px(self, label_width))
        self.columnconfigure(1, weight=1)
        self._row = 0

    def row(self, label: str, widget_factory_or_widget: Callable[[tk.Misc], tk.Widget] | tk.Widget,
            unit: str | None = None, help_text: str | None = None, sticky: str = "ew") -> tk.Widget:
        if isinstance(widget_factory_or_widget, tk.Widget):
            widget = widget_factory_or_widget
        else:
            widget = widget_factory_or_widget(self)
        pady = (SPACING["sp_1"], SPACING["sp_1"])
        ttk.Label(self, text=label).grid(row=self._row, column=0, sticky="w",
                                         padx=(0, SPACING["sp_3"]), pady=pady)
        widget.grid(row=self._row, column=1, sticky=sticky, pady=pady)
        if unit:
            ttk.Label(self, text=unit, style="Muted.TLabel").grid(
                row=self._row, column=2, sticky="w", padx=(SPACING["sp_2"], 0))
        self._row += 1
        if help_text:
            ttk.Label(self, text=help_text, style="Muted.TLabel", wraplength=px(self, 320),
                      justify="left").grid(row=self._row, column=1, columnspan=2, sticky="w",
                                           pady=(0, SPACING["sp_2"]))
            self._row += 1
        return widget

    def full(self, widget: tk.Widget, pady: tuple[int, int] | int = 0) -> tk.Widget:
        """Place a widget across all three columns."""
        widget.grid(row=self._row, column=0, columnspan=3, sticky="ew", pady=pady)
        self._row += 1
        return widget


# ---------------------------------------------------------------------------
# Switch
# ---------------------------------------------------------------------------
class Switch(ttk.Frame):
    """Canvas toggle bound to a BooleanVar. Space/Enter toggle, focus ring visible."""

    def __init__(self, parent: tk.Misc, variable: tk.BooleanVar, text: str = "",
                 command: Callable[[], None] | None = None,
                 tokens: dict[str, str] | None = None) -> None:
        super().__init__(parent)
        self.variable, self.command, self.tokens = variable, command, tokens
        self._enabled = True
        self._hover = False
        self.w, self.h = px(self, 36), px(self, 20)
        self.canvas = tk.Canvas(self, width=self.w, height=self.h, highlightthickness=0,
                                background=_tok(tokens)["bg"], takefocus=1, cursor="hand2")
        self.canvas.grid(row=0, column=0)
        self.label = ttk.Label(self, text=text)
        if text:
            self.label.grid(row=0, column=1, padx=(SPACING["sp_2"], 0), sticky="w")
        for w in (self.canvas, self.label):
            w.bind("<Button-1>", self._click, add="+")
            w.bind("<Enter>", lambda e: self._set_hover(True), add="+")
            w.bind("<Leave>", lambda e: self._set_hover(False), add="+")
        self.canvas.bind("<space>", self._click, add="+")
        self.canvas.bind("<Return>", self._click, add="+")
        self.canvas.bind("<FocusIn>", lambda e: self._draw(), add="+")
        self.canvas.bind("<FocusOut>", lambda e: self._draw(), add="+")
        self._trace = variable.trace_add("write", lambda *a: self._draw())
        self.bind("<Destroy>", self._on_destroy, add="+")
        self._draw()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self.canvas.configure(takefocus=1 if enabled else 0,
                              cursor="hand2" if enabled else "arrow")
        self.label.state(["!disabled"] if enabled else ["disabled"])
        self._draw()

    def apply_tokens(self, tokens: dict[str, str]) -> None:
        self.tokens = tokens
        self.canvas.configure(background=tokens["bg"])
        self._draw()

    def _on_destroy(self, _event: tk.Event) -> None:
        try:
            self.variable.trace_remove("write", self._trace)
        except tk.TclError:
            pass

    def _set_hover(self, on: bool) -> None:
        self._hover = on
        self._draw()

    def _click(self, _event: tk.Event | None = None) -> str:
        if self._enabled:
            self.variable.set(not self.variable.get())
            self.canvas.focus_set()
            if self.command:
                self.command()
        return "break"

    def _draw(self) -> None:
        t = _tok(self.tokens)
        c = self.canvas
        c.delete("all")
        on = bool(self.variable.get())
        w, h = self.w, self.h
        pad = px(self, 2)
        if not self._enabled:
            track, knob = t["surface_alt"], t["text_disabled"]
        elif on:
            track = t["accent_hover"] if self._hover else t["accent"]
            knob = t["accent_text"]
        else:
            track = t["border_strong"] if self._hover else t["border"]
            knob = t["text_muted"]
        r = h // 2
        c.create_oval(0, 0, h, h, fill=track, outline=track, tags="track")
        c.create_oval(w - h, 0, w, h, fill=track, outline=track, tags="track")
        c.create_rectangle(r, 0, w - r, h, fill=track, outline=track, tags="track")
        kx = (w - h + pad) if on else pad
        c.create_oval(kx, pad, kx + h - 2 * pad, h - pad, fill=knob, outline=knob, tags="knob")
        if c.focus_get() is c:
            c.create_rectangle(0, 0, w - 1, h - 1, outline=t["focus"], dash=(2, 2), tags="focus")


# ---------------------------------------------------------------------------
# SegmentedControl
# ---------------------------------------------------------------------------
class SegmentedControl(ttk.Frame):
    """Row of exclusive buttons bound to a variable; replaces radio groups.

    options: list of (value, label). Uses ttk.Radiobutton with a custom
    Toolbutton style so the selected segment is drawn in accent color.
    """

    STYLE = "Segment.Toolbutton"

    def __init__(self, parent: tk.Misc, options: Sequence[tuple[str, str]], variable: tk.Variable,
                 command: Callable[[], None] | None = None,
                 tokens: dict[str, str] | None = None) -> None:
        super().__init__(parent, style="Segmented.TFrame", padding=1)
        self.variable, self.options = variable, list(options)
        self.tokens = tokens
        self.apply_tokens(_tok(tokens))
        self.buttons: list[ttk.Radiobutton] = []
        for i, (value, label) in enumerate(self.options):
            b = ttk.Radiobutton(self, text=label, value=value, variable=variable, style=self.STYLE,
                                command=command, takefocus=1)
            b.grid(row=0, column=i, sticky="nsew", padx=(0, 1 if i < len(self.options) - 1 else 0))
            self.columnconfigure(i, weight=1, uniform="seg")
            b.bind("<Left>", lambda e, i=i: self._select(i - 1), add="+")
            b.bind("<Right>", lambda e, i=i: self._select(i + 1), add="+")
            self.buttons.append(b)

    def apply_tokens(self, t: dict[str, str]) -> None:
        style = ttk.Style(self)
        style.configure("Segmented.TFrame", background=t["border"])
        style.configure(self.STYLE, background=t["surface_alt"], foreground=t["text"],
                        bordercolor=t["surface_alt"], lightcolor=t["surface_alt"],
                        darkcolor=t["surface_alt"], focuscolor=t["surface_alt"], borderwidth=0,
                        padding=(SPACING["sp_3"], SPACING["sp_1"] + 1), anchor="center", relief="flat")
        style.map(self.STYLE,
                  background=[("disabled", t["surface"]), ("selected", t["accent"]),
                              ("active", t["border"])],
                  bordercolor=[("selected", t["accent"]), ("active", t["border"])],
                  lightcolor=[("selected", t["accent"]), ("active", t["border"])],
                  darkcolor=[("selected", t["accent"]), ("active", t["border"])],
                  foreground=[("disabled", t["text_disabled"]), ("selected", t["accent_text"])],
                  focuscolor=[("focus", t["focus"])],
                  relief=[("disabled", "flat"), ("selected", "flat"), ("pressed", "flat"),
                          ("active", "flat")])

    def set_enabled(self, enabled: bool) -> None:
        for b in self.buttons:
            b.state(["!disabled"] if enabled else ["disabled"])

    def _select(self, index: int) -> str:
        index = max(0, min(len(self.options) - 1, index))
        self.buttons[index].focus_set()
        self.buttons[index].invoke()  # sets the variable and runs command
        return "break"


# ---------------------------------------------------------------------------
# ColorSwatchButton
# ---------------------------------------------------------------------------
def parse_color(value: str) -> tuple[int, int, int, int]:
    """Parse "R,G,B,A", "R,G,B", "#RRGGBBAA" or "#RRGGBB" into an RGBA tuple."""
    s = value.strip()
    if s.startswith("#"):
        h = s[1:]
        if len(h) == 6:
            h += "FF"
        if len(h) != 8:
            raise ValueError("bad hex color: %r" % value)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4, 6))  # type: ignore[return-value]
    parts = [int(float(p)) for p in s.replace(";", ",").split(",") if p.strip()]
    if len(parts) == 3:
        parts.append(255)
    if len(parts) != 4:
        raise ValueError("bad color: %r" % value)
    return tuple(max(0, min(255, p)) for p in parts)  # type: ignore[return-value]


def format_color(rgba: tuple[int, int, int, int], like: str = "0,0,0,255") -> str:
    """Format RGBA in the same notation as `like` (hex or comma list)."""
    r, g, b, a = rgba
    if like.strip().startswith("#"):
        return "#%02X%02X%02X%02X" % (r, g, b, a)
    return "%d,%d,%d,%d" % (r, g, b, a)


def _blend(fg: tuple[int, int, int], alpha: int, bg_hex: str) -> str:
    """Blend fg over an opaque hex background using alpha 0-255."""
    bg = tuple(int(bg_hex[i:i + 2], 16) for i in (1, 3, 5))
    k = alpha / 255.0
    return "#%02X%02X%02X" % tuple(int(round(f * k + b * (1 - k))) for f, b in zip(fg, bg))


class ColorSwatchButton(ttk.Frame):
    """Swatch with alpha checkerboard, hex label, picker button and alpha spinbox.

    `variable` is a StringVar holding "R,G,B,A" or "#RRGGBBAA"; the input
    notation is preserved when writing back.
    """

    def __init__(self, parent: tk.Misc, variable: tk.StringVar,
                 on_change: Callable[[str], None] | None = None,
                 tokens: dict[str, str] | None = None) -> None:
        super().__init__(parent)
        self.variable, self.on_change, self.tokens = variable, on_change, tokens
        self._updating = False
        t = _tok(tokens)
        self.sw, self.sh = px(self, 28), px(self, 20)
        self.swatch = tk.Canvas(self, width=self.sw, height=self.sh, highlightthickness=1,
                                highlightbackground=t["border_strong"], cursor="hand2",
                                background=t["surface"])
        self.swatch.grid(row=0, column=0)
        self.hex_label = ttk.Label(self, font="font_mono", width=13)
        self.hex_label.grid(row=0, column=1, padx=(SPACING["sp_2"], SPACING["sp_1"]), sticky="w")
        self.pick_btn = ttk.Button(self, text="...", width=3, style="Ghost.TButton", command=self.pick)
        self.pick_btn.grid(row=0, column=2)
        ttk.Label(self, text="A", style="Muted.TLabel").grid(row=0, column=3, padx=(SPACING["sp_2"], 2))
        self.alpha_var = tk.IntVar(value=255)
        self.alpha_spin = ttk.Spinbox(self, from_=0, to=255, width=4, textvariable=self.alpha_var,
                                      command=self._alpha_changed)
        self.alpha_spin.grid(row=0, column=4)
        self.alpha_spin.bind("<Return>", lambda e: self._alpha_changed(), add="+")
        self.alpha_spin.bind("<FocusOut>", lambda e: self._alpha_changed(), add="+")
        self.swatch.bind("<Button-1>", lambda e: self.pick(), add="+")
        self._trace = variable.trace_add("write", lambda *a: self._refresh())
        self.bind("<Destroy>", lambda e: self._untrace(), add="+")
        self._refresh()

    def _untrace(self) -> None:
        try:
            self.variable.trace_remove("write", self._trace)
        except tk.TclError:
            pass

    def _current(self) -> tuple[int, int, int, int]:
        try:
            return parse_color(self.variable.get())
        except ValueError:
            return (0, 0, 0, 255)

    def _write(self, rgba: tuple[int, int, int, int]) -> None:
        self._updating = True
        try:
            self.variable.set(format_color(rgba, like=self.variable.get()))
        finally:
            self._updating = False
        self._refresh()
        if self.on_change:
            self.on_change(self.variable.get())

    def pick(self) -> None:
        r, g, b, a = self._current()
        result = colorchooser.askcolor(color="#%02X%02X%02X" % (r, g, b), parent=self)
        if result and result[1]:
            hx = result[1].lstrip("#")
            self._write((int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16), a))

    def _alpha_changed(self) -> None:
        try:
            a = max(0, min(255, int(self.alpha_var.get())))
        except (tk.TclError, ValueError):
            return
        r, g, b, _ = self._current()
        self._write((r, g, b, a))

    def _refresh(self) -> None:
        t = _tok(self.tokens)
        r, g, b, a = self._current()
        if not self._updating:
            self.alpha_var.set(a)
        self.hex_label.configure(text="#%02X%02X%02X %3d%%" % (r, g, b, round(a * 100 / 255)))
        c = self.swatch
        c.delete("all")
        light, dark = _blend((r, g, b), a, "#FFFFFF"), _blend((r, g, b), a, "#9A9A9A")
        cell = max(2, px(self, 5))
        for yy in range(0, self.sh + cell, cell):
            for xx in range(0, self.sw + cell, cell):
                color = light if ((xx // cell) + (yy // cell)) % 2 == 0 else dark
                c.create_rectangle(xx + 1, yy + 1, xx + cell + 1, yy + cell + 1, fill=color, outline=color)


# ---------------------------------------------------------------------------
# NumberField
# ---------------------------------------------------------------------------
class NumberField(ttk.Frame):
    """Entry with -/+ buttons, unit label, validation, clamping and wheel/arrow stepping.

    `variable` is a DoubleVar or IntVar. Values are shown with `fmt`
    (comma as decimal separator when decimal_comma=True) and always
    clamped to [minimum, maximum].
    """

    def __init__(self, parent: tk.Misc, variable: tk.Variable, minimum: float, maximum: float,
                 step: float = 1.0, unit: str = "", fmt: str = "{:.2f}", decimal_comma: bool = False,
                 width: int = 9, command: Callable[[float], None] | None = None) -> None:
        super().__init__(parent)
        self.variable, self.minimum, self.maximum, self.step = variable, minimum, maximum, step
        self.fmt, self.decimal_comma, self.command = fmt, decimal_comma, command
        self._updating = False
        self.text = tk.StringVar()
        vcmd = (self.register(self._validate_key), "%P")
        self.minus = ttk.Button(self, text="−", width=2, style="Ghost.TButton",
                                command=lambda: self.bump(-1), takefocus=0)
        self.minus.grid(row=0, column=0)
        self.entry = ttk.Entry(self, textvariable=self.text, width=width, justify="right",
                               validate="key", validatecommand=vcmd, font="font_mono")
        self.entry.grid(row=0, column=1, sticky="ew", padx=2)
        self.columnconfigure(1, weight=1)
        self.plus = ttk.Button(self, text="+", width=2, style="Ghost.TButton",
                               command=lambda: self.bump(1), takefocus=0)
        self.plus.grid(row=0, column=2)
        if unit:
            ttk.Label(self, text=unit, style="Muted.TLabel").grid(row=0, column=3, padx=(SPACING["sp_2"], 0))
        self.entry.bind("<Return>", lambda e: self.commit(), add="+")
        self.entry.bind("<KP_Enter>", lambda e: self.commit(), add="+")
        self.entry.bind("<FocusOut>", lambda e: self.commit(), add="+")
        self.entry.bind("<Up>", lambda e: self.bump(1, e), add="+")
        self.entry.bind("<Down>", lambda e: self.bump(-1, e), add="+")
        self.entry.bind("<MouseWheel>", self._wheel, add="+")
        self.entry.bind("<Button-4>", lambda e: self.bump(1, e), add="+")
        self.entry.bind("<Button-5>", lambda e: self.bump(-1, e), add="+")
        self._trace = variable.trace_add("write", lambda *a: self._from_variable())
        self.bind("<Destroy>", lambda e: self._untrace(), add="+")
        self._from_variable()

    def _untrace(self) -> None:
        try:
            self.variable.trace_remove("write", self._trace)
        except tk.TclError:
            pass

    def _validate_key(self, proposed: str) -> bool:
        allowed = set("0123456789-+.,eE")
        return all(ch in allowed for ch in proposed)

    def _format(self, value: float) -> str:
        s = self.fmt.format(value)
        return s.replace(".", ",") if self.decimal_comma else s

    def _clamp(self, value: float) -> float:
        value = max(self.minimum, min(self.maximum, value))
        return int(round(value)) if isinstance(self.variable, tk.IntVar) else value

    def _from_variable(self) -> None:
        if self._updating:
            return
        try:
            value = float(self.variable.get())
        except (tk.TclError, ValueError):
            return
        self.text.set(self._format(value))
        self.entry.state(["!invalid"])

    def commit(self) -> None:
        """Parse the entry text, clamp, write back to the variable."""
        raw = self.text.get().strip().replace(",", ".").replace(" ", "")
        try:
            value = float(raw)
        except ValueError:
            self.entry.state(["invalid"])
            return
        self.set(value)

    def set(self, value: float) -> None:
        value = self._clamp(value)
        self._updating = True
        try:
            self.variable.set(value)
        finally:
            self._updating = False
        self.text.set(self._format(value))
        self.entry.state(["!invalid"])
        if self.command:
            self.command(value)

    def bump(self, direction: int, event: tk.Event | None = None) -> str:
        factor = 10 if event is not None and (getattr(event, "state", 0) & 0x0001) else 1
        try:
            base = float(self.text.get().replace(",", "."))
        except ValueError:
            base = float(self.variable.get())
        self.set(base + direction * self.step * factor)
        return "break"

    def _wheel(self, event: tk.Event) -> str:
        return self.bump(1 if event.delta > 0 else -1, event)


# ---------------------------------------------------------------------------
# PathField
# ---------------------------------------------------------------------------
class PathField(ttk.Frame):
    """Stretching path entry with a "..." browse button.

    Displays the path shortened from the left ("...\\dir\\file.mp4") while
    unfocused; the full path lives in `variable`. mode: open, save or dir.
    """

    def __init__(self, parent: tk.Misc, variable: tk.StringVar, title: str = "",
                 filetypes: Sequence[tuple[str, str]] | None = None, mode: str = "open") -> None:
        super().__init__(parent)
        self.variable, self.title, self.filetypes, self.mode = variable, title, filetypes, mode
        self.display = tk.StringVar()
        self.columnconfigure(0, weight=1)
        self.entry = ttk.Entry(self, textvariable=self.display)
        self.entry.grid(row=0, column=0, sticky="ew")
        self.button = ttk.Button(self, text="...", width=3, command=self.browse)
        self.button.grid(row=0, column=1, padx=(SPACING["sp_1"], 0))
        self.tooltip = Tooltip(self.entry, "")
        self.entry.bind("<FocusIn>", lambda e: self.display.set(self.variable.get()), add="+")
        self.entry.bind("<FocusOut>", lambda e: self._commit(), add="+")
        self.entry.bind("<Return>", lambda e: self._commit(), add="+")
        self.entry.bind("<Configure>", lambda e: self._refresh(), add="+")
        self._trace = variable.trace_add("write", lambda *a: self._refresh())
        self.bind("<Destroy>", lambda e: self._untrace(), add="+")
        self._refresh()

    def _untrace(self) -> None:
        try:
            self.variable.trace_remove("write", self._trace)
        except tk.TclError:
            pass

    def _commit(self) -> None:
        typed = self.display.get()
        if typed and not typed.startswith("...") and typed != self.variable.get():
            self.variable.set(typed)
        self._refresh()

    def _shorten(self, path: str) -> str:
        if not path:
            return ""
        try:
            font = tkfont.nametofont(str(self.entry.cget("font") or "TkTextFont"))
        except tk.TclError:
            font = tkfont.nametofont("TkTextFont")
        avail = max(40, self.entry.winfo_width() - px(self, 16))
        if font.measure(path) <= avail:
            return path
        cut = path
        while len(cut) > 4 and font.measure("..." + cut) > avail:
            cut = cut[1:]
        return "..." + cut

    def _refresh(self) -> None:
        full = self.variable.get()
        self.tooltip.set_text(full)
        if self.focus_get() is self.entry:
            return
        self.display.set(self._shorten(full))

    def browse(self) -> None:
        current = self.variable.get()
        initial = os.path.dirname(current) if current else os.getcwd()
        kw: dict[str, Any] = {"parent": self, "title": self.title, "initialdir": initial}
        if self.mode == "dir":
            chosen = filedialog.askdirectory(**kw)
        elif self.mode == "save":
            chosen = filedialog.asksaveasfilename(filetypes=self.filetypes or [("All files", "*.*")], **kw)
        else:
            chosen = filedialog.askopenfilename(filetypes=self.filetypes or [("All files", "*.*")], **kw)
        if chosen:
            self.variable.set(chosen)


# ---------------------------------------------------------------------------
# StatusBar and InlineMessage
# ---------------------------------------------------------------------------
class StatusBar(ttk.Frame):
    """One-line status bar with a colored dot; set(text, kind, timeout_ms)."""

    def __init__(self, parent: tk.Misc, tokens: dict[str, str] | None = None) -> None:
        super().__init__(parent, style="Sidebar.TFrame", padding=(SPACING["sp_3"], SPACING["sp_1"]))
        self.tokens = tokens
        self._after: str | None = None
        t = _tok(tokens)
        d = px(self, 8)
        self.dot = tk.Canvas(self, width=d, height=d, highlightthickness=0, background=t["surface"])
        self.dot.pack(side="left", padx=(0, SPACING["sp_2"]))
        self.label = ttk.Label(self, text="", style="Sidebar.TLabel")
        self.label.pack(side="left", fill="x", expand=True)
        self.right = ttk.Label(self, text="", style="Muted.TLabel")
        self.right.pack(side="right")
        self.set("", "info")

    def set(self, text: str, kind: str = "info", timeout_ms: int | None = None) -> None:
        t = _tok(self.tokens)
        color = t[KIND_KEYS.get(kind, "info")] if text else t["surface"]
        self.dot.configure(background=t["surface"])
        self.dot.delete("all")
        d = px(self, 8)
        self.dot.create_oval(0, 0, d - 1, d - 1, fill=color, outline=color)
        self.label.configure(text=text, foreground=t["text"] if kind == "info" else color)
        if self._after is not None:
            self.after_cancel(self._after)
            self._after = None
        if timeout_ms:
            self._after = self.after(timeout_ms, lambda: self.set("", "info"))

    def clear(self) -> None:
        self.set("", "info")


class InlineMessage(ttk.Frame):
    """Hidden-by-default message strip with a colored bar; show(text, kind) / hide()."""

    def __init__(self, parent: tk.Misc, tokens: dict[str, str] | None = None) -> None:
        super().__init__(parent, style="Card.TFrame")
        self.tokens = tokens
        t = _tok(tokens)
        self.bar = tk.Frame(self, width=px(self, 3), background=t["info"])
        self.bar.pack(side="left", fill="y")
        self.label = ttk.Label(self, text="", style="Card.TLabel", wraplength=px(self, 320),
                               justify="left", padding=(SPACING["sp_2"], SPACING["sp_1"]))
        self.label.pack(side="left", fill="x", expand=True)
        self.close = ttk.Button(self, text="×", width=2, style="Ghost.TButton", command=self.hide)
        self.close.pack(side="right", padx=SPACING["sp_1"])
        self._grid_kw: dict[str, Any] | None = None
        self.after_idle(self.hide)

    def show(self, text: str, kind: str = "info") -> None:
        t = _tok(self.tokens)
        self.bar.configure(background=t[KIND_KEYS.get(kind, "info")])
        self.label.configure(text=text)
        if self.winfo_manager() == "":
            if self._grid_kw is not None:
                self.grid(**self._grid_kw)
            else:
                self.grid()

    def hide(self) -> None:
        if self.winfo_manager() == "grid":
            info = self.grid_info()
            self._grid_kw = {k: v for k, v in info.items() if k != "in"}
            self.grid_remove()
        elif self.winfo_manager() == "pack":
            self.pack_forget()


# ---------------------------------------------------------------------------
# Demo: inspector similar to the Piro Overlay left panel
# ---------------------------------------------------------------------------
def _demo() -> None:
    try:
        from theme_template import apply_theme, enable_hidpi, set_windows_dark_titlebar
    except ImportError:
        apply_theme = enable_hidpi = set_windows_dark_titlebar = None  # type: ignore

    # UI strings kept in one place so PL/EN switching stays trivial.
    S = {
        "title": "Inspektor (demo widgets.py)",
        "input": "Wej\u015bcie", "video": "Plik wideo", "audio": "\u015acie\u017cka audio",
        "sync": "Synchronizacja i przyci\u0119cie", "offset": "Przesuni\u0119cie",
        "trim_start": "Pocz\u0105tek", "trim_end": "Koniec", "detect": "Wykryj START z audio",
        "look": "Wygl\u0105d nakl\u0142adki", "position": "Pozycja", "bg": "T\u0142o",
        "fg": "Tekst", "show_wave": "Pokazuj fal\u0119 audio", "size": "Rozmiar czcionki",
        "render": "Renderuj", "ready": "Gotowe", "video_files": "Pliki wideo",
    }

    if enable_hidpi:
        enable_hidpi()
    root = tk.Tk()
    root.title(S["title"])
    tokens = apply_theme(root, "dark") if apply_theme else _tok(None)
    root.minsize(px(root, 720), px(root, 480))

    paned = ttk.PanedWindow(root, orient="horizontal")
    paned.pack(fill="both", expand=True)

    side = ttk.Frame(paned, style="Sidebar.TFrame", padding=(SPACING["sp_3"], SPACING["sp_3"], 0, 0))
    paned.add(side, weight=0)
    scroller = ScrollableFrame(side)
    scroller.pack(fill="both", expand=True)
    form_parent = scroller.inner
    form_parent.columnconfigure(0, weight=1)

    def section(row: int, title: str, collapsible: bool = True) -> FormGrid:
        grid = FormGrid(form_parent, label_width=120)
        grid.grid(row=row + 1, column=0, sticky="ew", padx=(SPACING["sp_1"], SPACING["sp_3"]),
                  pady=(0, SPACING["sp_4"]))
        SectionHeader(form_parent, title, collapsible=collapsible, content=grid).grid(
            row=row, column=0, sticky="ew", pady=(0, SPACING["sp_2"]), padx=(0, SPACING["sp_3"]))
        return grid

    video_var = tk.StringVar(value="C:/Users/demo/Videos/trening_2026-09-12_stage3.mp4")
    audio_var = tk.StringVar(value="auto")
    g1 = section(0, S["input"])
    g1.row(S["video"], lambda p: PathField(p, video_var, S["video"], [(S["video_files"], "*.mp4 *.mov")]))
    g1.row(S["audio"], lambda p: ttk.Combobox(p, textvariable=audio_var, state="readonly",
                                              values=["auto", "1", "2"]))

    offset = tk.DoubleVar(value=0.0)
    start = tk.DoubleVar(value=0.0)
    end = tk.DoubleVar(value=12.5)
    g2 = section(2, S["sync"])
    g2.row(S["offset"], lambda p: NumberField(p, offset, -10, 10, 0.05, unit="s", decimal_comma=True),
           help_text="Ujemne = nak\u0142adka wcze\u015bniej ni\u017c d\u017awi\u0119k.")
    g2.row(S["trim_start"], lambda p: NumberField(p, start, 0, 3600, 0.1, unit="s"))
    g2.row(S["trim_end"], lambda p: NumberField(p, end, 0, 3600, 0.1, unit="s"))
    msg = InlineMessage(g2)
    g2.full(ttk.Button(g2, text=S["detect"], style="Accent.TButton",
                       command=lambda: msg.show("Znaleziono START przy 1,32 s", "success")),
            pady=(SPACING["sp_2"], 0))
    g2.full(msg, pady=(SPACING["sp_2"], 0))

    pos = tk.StringVar(value="tl")
    bg_color = tk.StringVar(value="0,0,0,170")
    fg_color = tk.StringVar(value="#FFC400FF")
    show_wave = tk.BooleanVar(value=True)
    size = tk.IntVar(value=48)
    g3 = section(4, S["look"])
    g3.row(S["position"], lambda p: SegmentedControl(
        p, [("tl", "\u2196"), ("tr", "\u2197"), ("bl", "\u2199"), ("br", "\u2198")], pos))
    g3.row(S["bg"], lambda p: ColorSwatchButton(p, bg_color), sticky="w")
    g3.row(S["fg"], lambda p: ColorSwatchButton(p, fg_color), sticky="w")
    g3.row(S["size"], lambda p: NumberField(p, size, 8, 200, 2, unit="px", fmt="{:.0f}"))
    g3.row("", lambda p: Switch(p, show_wave, S["show_wave"]), sticky="w")

    # Right side: preview + timeline placeholders drawn on Canvas
    right = ttk.Frame(paned, padding=SPACING["sp_3"])
    paned.add(right, weight=1)
    right.columnconfigure(0, weight=1)
    right.rowconfigure(0, weight=1)
    preview = tk.Canvas(right, background="#000000", highlightthickness=0)
    preview.grid(row=0, column=0, sticky="nsew")
    timeline = tk.Canvas(right, height=px(root, 72), background=tokens["surface"], highlightthickness=0)
    timeline.grid(row=1, column=0, sticky="ew", pady=(SPACING["sp_2"], 0))
    overlay_font = tkfont.Font(root, family=tkfont.nametofont("TkHeadingFont").actual("family"),
                               size=24, weight="bold")

    def draw_preview(_event: tk.Event | None = None) -> None:
        preview.delete("all")
        w, h = preview.winfo_width(), preview.winfo_height()
        r, g, b, a = parse_color(bg_color.get())
        fr, fg, fb, _ = parse_color(fg_color.get())
        box_w, box_h = px(root, 180), px(root, 56)
        x = SPACING["sp_4"] if pos.get() in ("tl", "bl") else w - box_w - SPACING["sp_4"]
        y = SPACING["sp_4"] if pos.get() in ("tl", "tr") else h - box_h - SPACING["sp_4"]
        preview.create_rectangle(x, y, x + box_w, y + box_h, fill=_blend((r, g, b), a, "#000000"), width=0)
        overlay_font.configure(size=max(8, int(size.get() / 2)))
        preview.create_text(x + box_w / 2, y + box_h / 2, text="START", fill="#%02X%02X%02X" % (fr, fg, fb),
                            font=overlay_font)

    def draw_timeline(_event: tk.Event | None = None) -> None:
        timeline.delete("all")
        w, h = timeline.winfo_width(), timeline.winfo_height()
        mid = h // 2
        if show_wave.get():
            pts = []
            for i in range(0, w, 3):
                amp = (abs((i * 7919) % 97 - 48) / 48.0) * (mid - 6)
                pts.extend([i, mid - amp, i, mid + amp])
            for i in range(0, len(pts) - 3, 4):
                timeline.create_line(pts[i], pts[i + 1], pts[i + 2], pts[i + 3], fill=tokens["text_muted"])
        sx = int(w * 0.12)
        timeline.create_line(sx, 0, sx, h, fill=tokens["accent"], width=2, tags="marker")
        timeline.create_text(sx + 6, 10, text="START", anchor="w", fill=tokens["accent"], font="font_ui_small")

    preview.bind("<Configure>", draw_preview)
    timeline.bind("<Configure>", draw_timeline)
    for var in (pos, bg_color, fg_color, size):
        var.trace_add("write", lambda *a: draw_preview())
    show_wave.trace_add("write", lambda *a: draw_timeline())

    status = StatusBar(root)
    status.pack(fill="x", side="bottom")
    status.set(S["ready"], "success", timeout_ms=4000)
    Tooltip(timeline, "O\u015b czasu: przeci\u0105gnij marker START")

    root.update_idletasks()
    if set_windows_dark_titlebar:
        set_windows_dark_titlebar(root, True)
    root.mainloop()


if __name__ == "__main__":
    _demo()
