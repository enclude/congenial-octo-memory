"""Widżety UI sterowane tokenami motywu (warstwa UI — wolno importować Qt).

Towarzysz `ui_theme.py`; skopiowany ze skilla `python-desktop-ux`
(`scripts/qt_widgets.py`) bez sekcji demo. Każdy widżet przyjmuje opcjonalną mapę
`tokens`; gdy jej nie ma, bierze tokeny motywu nałożonego przez
`ui_theme.apply_theme` (fallback: wbudowany zestaw ciemny).

Widgets
    SectionHeader      bold title + optional collapse chevron + rule (replaces QGroupBox)
    FormSection        SectionHeader + QFormLayout with token spacing
    Switch             painted on/off toggle (QAbstractButton, animated)
    SegmentedControl   exclusive segment buttons (replaces a QRadioButton pair)
    ColorSwatchButton  RGBA swatch with checkerboard (API-compatible with gui.ColorButton)
    NumberField        QDoubleSpinBox without native buttons + "-" / "+" tool buttons
    PathField          elided path + browse button + drag and drop
    InlineMessage      one-line status under a field or section

    StatusDot          kropka statusu malowana kolorem roli z tokenów motywu

Helpers
    set_busy(button, busy, text=None)
    status_message(statusbar, text, kind, timeout_ms)
"""

from __future__ import annotations

from typing import Any, Iterable

from PySide6.QtCore import (QEasingCurve, QLocale, QRectF, QSize, Qt, QTimer,
                            QVariantAnimation, Signal)
from PySide6.QtGui import (QColor, QDragEnterEvent, QDropEvent, QFontMetrics, QPainter,
                           QPainterPath, QPen)
from PySide6.QtWidgets import (QAbstractButton, QAbstractSpinBox, QApplication, QButtonGroup,
                               QColorDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy,
                               QStatusBar, QToolButton, QVBoxLayout, QWidget)

try:  # theme module is optional so the widgets can be dropped in alone
    from .ui_theme import RADIUS, SPACING, TOKENS, current_tokens, repolish
    _HAVE_THEME = True
except ImportError:  # pragma: no cover - fallback when ui_theme.py is absent
    _HAVE_THEME = False
    SPACING = {"sp_1": 4, "sp_2": 8, "sp_3": 12, "sp_4": 16, "sp_5": 20, "sp_6": 24, "sp_8": 32}
    RADIUS = {"r_sm": 4, "r_md": 6, "r_lg": 8}
    TOKENS = {"dark": {
        "bg": "#1F1F1F", "surface": "#2A2A2C", "surface_alt": "#353538", "border": "#3F3F43",
        "border_strong": "#78787F", "text": "#F2F2F2", "text_muted": "#A0A0A8",
        "text_disabled": "#6E6E76", "accent": "#FFC400", "accent_hover": "#FFD033",
        "accent_pressed": "#E0AC00", "accent_text": "#1A1200", "accent_subtle": "#3F3821",
        "danger": "#F87171", "success": "#4ADE80", "warning": "#FB923C", "info": "#60A5FA",
        "focus": "#FFFFFF", "selection_bg": "#FFC400", "selection_text": "#1A1200"}}

    def current_tokens(app: Any) -> dict[str, str]:
        return TOKENS["dark"]

    def repolish(widget: Any) -> None:
        for w in [widget, *widget.findChildren(QWidget)]:
            w.style().unpolish(w)
            w.style().polish(w)
            w.update()

CONTROL_HEIGHT = 32


def _tokens(tokens: dict[str, str] | None) -> dict[str, str]:
    """Resolve the token mapping to paint with (explicit > applied theme)."""
    if tokens is not None:
        return tokens
    app = QApplication.instance()
    return current_tokens(app) if app is not None else TOKENS["dark"]


def set_role(widget: QWidget, role: str) -> None:
    """``setProperty("role", role)`` + repolish so QSS attribute selectors apply."""
    widget.setProperty("role", role)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def set_kind(widget: QWidget, kind: str) -> None:
    widget.setProperty("kind", kind)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def _focus_ring(p: QPainter, rect: QRectF, radius: float, tokens: dict[str, str]) -> None:
    p.setPen(QPen(QColor(tokens["focus"]), 2))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), radius, radius)


# ---------------------------------------------------------------------------
# SectionHeader / FormSection
# ---------------------------------------------------------------------------

class SectionHeader(QWidget):
    """Section title with a 1 px rule; optional chevron collapses ``set_content``.

    Replaces ``QGroupBox("Wejście")``: the title becomes a bold label
    (``role=section``), the frame becomes a single line under the title.
    """

    toggled = Signal(bool)   # True = expanded

    def __init__(self, title: str, collapsible: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self._content: QWidget | None = None
        self._expanded = True
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACING["sp_1"])
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACING["sp_1"])
        self.chevron = QToolButton()
        self.chevron.setProperty("kind", "ghost")
        self.chevron.setArrowType(Qt.DownArrow)
        self.chevron.setFixedSize(20, 20)
        self.chevron.setFocusPolicy(Qt.TabFocus)
        self.chevron.setVisible(collapsible)
        self.chevron.clicked.connect(self.toggle)
        row.addWidget(self.chevron)
        self.label = QLabel(title)
        self.label.setProperty("role", "section")
        row.addWidget(self.label)
        row.addStretch(1)
        self.trailing = QHBoxLayout()   # slot for small actions (reset, help)
        self.trailing.setSpacing(SPACING["sp_1"])
        row.addLayout(self.trailing)
        lay.addLayout(row)
        rule = QFrame()
        rule.setProperty("role", "separator")
        rule.setFrameShape(QFrame.NoFrame)
        rule.setFixedHeight(1)
        lay.addWidget(rule)

    def set_title(self, title: str) -> None:
        self.label.setText(title)

    def set_content(self, widget: QWidget) -> None:
        """Widget shown/hidden by the chevron (usually the section body)."""
        self._content = widget
        widget.setVisible(self._expanded)

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self.chevron.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        if self._content is not None:
            self._content.setVisible(expanded)
        self.toggled.emit(expanded)

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)


class FormSection(QWidget):
    """SectionHeader + QFormLayout body with token spacing.

    ``add_row(label, field, unit=None, help_text=None)`` appends a row; the
    optional unit label (``"s"``, ``"px"``) sits right of the field and the help
    text becomes a muted second line. Use ``add_widget_row`` for button rows.
    """

    LABEL_WIDTH = 132   # px at 100 %; keep one width for the whole inspector

    def __init__(self, title: str, collapsible: bool = True, parent: QWidget | None = None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACING["sp_3"])
        self.header = SectionHeader(title, collapsible)
        lay.addWidget(self.header)
        self.body = QWidget()
        self.form = QFormLayout(self.body)
        self.form.setContentsMargins(SPACING["sp_4"], 0, 0, 0)
        self.form.setHorizontalSpacing(SPACING["sp_2"])
        self.form.setVerticalSpacing(SPACING["sp_2"])
        self.form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        # AllNonFixedFieldsGrow (zamiast ExpandingFieldsGrow ze skryptu skilla):
        # ExpandingFieldsGrow rozciąga TYLKO pola z polityką Expanding, więc wiersze
        # z paskami przycisków (QSizePolicy.Ignored) kurczyły się do zera.
        self.form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.form.setRowWrapPolicy(QFormLayout.DontWrapRows)
        lay.addWidget(self.body)
        self.header.set_content(self.body)

    def add_row(self, label: str, field: QWidget, unit: str | None = None,
                help_text: str | None = None) -> QLabel:
        lab = QLabel(label)
        lab.setMinimumWidth(self.LABEL_WIDTH)
        lab.setBuddy(field)
        holder: QWidget = field
        if unit or help_text:
            holder = QWidget()
            v = QVBoxLayout(holder)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(SPACING["sp_1"])
            if unit:
                h = QHBoxLayout()
                h.setContentsMargins(0, 0, 0, 0)
                h.setSpacing(SPACING["sp_2"])
                h.addWidget(field, 1)
                u = QLabel(unit)
                u.setProperty("role", "muted")
                h.addWidget(u)
                v.addLayout(h)
            else:
                v.addWidget(field)
            if help_text:
                hint = QLabel(help_text)
                hint.setProperty("role", "muted")
                hint.setWordWrap(True)
                v.addWidget(hint)
        self.form.addRow(lab, holder)
        return lab

    def add_widget_row(self, widget: QWidget) -> None:
        """Full-width row (button bars, InlineMessage)."""
        self.form.addRow(widget)

    def add_pair_row(self, label: str, first: QWidget, second: QWidget,
                     separator: str = "/") -> None:
        """Two fields in one row, e.g. "Offset X / Y" or "Trim from / to"."""
        holder = QWidget()
        h = QHBoxLayout(holder)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(SPACING["sp_2"])
        h.addWidget(first, 1)
        sep = QLabel(separator)
        sep.setProperty("role", "muted")
        h.addWidget(sep)
        h.addWidget(second, 1)
        self.add_row(label, holder)


# ---------------------------------------------------------------------------
# Switch
# ---------------------------------------------------------------------------

class Switch(QAbstractButton):
    """Painted toggle switch. Checkable, keyboard operable (Space), focus ring.

    Track 40 x 20 px, knob 14 px; the knob position is animated with
    QVariantAnimation. Colours come from tokens, so it follows theme changes.
    """

    TRACK_W, TRACK_H, KNOB = 40, 20, 14

    def __init__(self, text: str = "", tokens: dict[str, str] | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._tokens = tokens
        self._pos = 0.0   # 0 = off, 1 = on
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)
        self.toggled.connect(self._animate)

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self.font())
        text_w = fm.horizontalAdvance(self.text()) + (SPACING["sp_2"] if self.text() else 0)
        return QSize(self.TRACK_W + text_w + 4, max(self.TRACK_H + 4, fm.height() + 4))

    def _animate(self, checked: bool) -> None:
        self._anim.stop()
        if not self.isVisible():   # initial state or hidden: jump, do not animate
            self._pos = 1.0 if checked else 0.0
            self.update()
            return
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def _on_anim(self, value: Any) -> None:
        self._pos = float(value)
        self.update()

    def paintEvent(self, _event: Any) -> None:
        t = _tokens(self._tokens)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        y = (self.height() - self.TRACK_H) / 2
        track = QRectF(2, y, self.TRACK_W, self.TRACK_H)
        on = QColor(t["accent"])
        off = QColor(t["border_strong"])
        if not self.isEnabled():
            on, off = QColor(t["border"]), QColor(t["border"])
        fill = QColor(off)
        fill.setRedF(off.redF() + (on.redF() - off.redF()) * self._pos)
        fill.setGreenF(off.greenF() + (on.greenF() - off.greenF()) * self._pos)
        fill.setBlueF(off.blueF() + (on.blueF() - off.blueF()) * self._pos)
        p.setPen(Qt.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(track, self.TRACK_H / 2, self.TRACK_H / 2)
        margin = (self.TRACK_H - self.KNOB) / 2
        kx = track.left() + margin + self._pos * (self.TRACK_W - self.KNOB - 2 * margin)
        knob_color = QColor(t["accent_text"] if self._pos > 0.5 else t["text"])
        if not self.isEnabled():
            knob_color = QColor(t["text_disabled"])
        p.setBrush(knob_color)
        p.drawEllipse(QRectF(kx, track.top() + margin, self.KNOB, self.KNOB))
        if self.text():
            p.setPen(QColor(t["text"] if self.isEnabled() else t["text_disabled"]))
            p.drawText(QRectF(track.right() + SPACING["sp_2"], 0,
                              self.width() - track.right() - SPACING["sp_2"], self.height()),
                       Qt.AlignVCenter | Qt.AlignLeft, self.text())
        if self.hasFocus():
            _focus_ring(p, track.adjusted(-2, -2, 2, 2), self.TRACK_H / 2 + 2, t)


# ---------------------------------------------------------------------------
# SegmentedControl
# ---------------------------------------------------------------------------

class SegmentedControl(QWidget):
    """Exclusive segment buttons; replaces a pair of QRadioButton.

    ``items`` are ``(key, label)`` pairs; ``value()`` returns the key of the
    checked segment. Keys stay stable across languages, labels are translated.
    """

    currentChanged = Signal(str)

    def __init__(self, items: Iterable[tuple[str, str]], parent: QWidget | None = None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACING["sp_1"])
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for key, label in items:
            b = QPushButton(label)
            b.setCheckable(True)
            b.setProperty("kind", "segment")
            b.setProperty("segment_key", key)
            b.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            self._group.addButton(b)
            self._buttons[key] = b
            lay.addWidget(b)
        lay.addStretch(1)
        self._group.buttonToggled.connect(self._on_toggled)
        if self._buttons:
            next(iter(self._buttons.values())).setChecked(True)

    def _on_toggled(self, button: QAbstractButton, checked: bool) -> None:
        if checked:
            self.currentChanged.emit(button.property("segment_key"))

    def value(self) -> str:
        b = self._group.checkedButton()
        return b.property("segment_key") if b is not None else ""

    def set_value(self, key: str) -> None:
        if key in self._buttons:
            self._buttons[key].setChecked(True)

    def set_label(self, key: str, label: str) -> None:
        """Retranslate one segment without touching its key."""
        self._buttons[key].setText(label)

    def button(self, key: str) -> QPushButton:
        return self._buttons[key]


# ---------------------------------------------------------------------------
# ColorSwatchButton
# ---------------------------------------------------------------------------

class ColorSwatchButton(QAbstractButton):
    """RGBA colour picker button: checkerboard + colour swatch + hex and alpha.

    Drop-in for ``gui.ColorButton``: same constructor ``(rgba)``, ``rgba()``
    accessor and ``changed`` signal, so settings format and callers stay as
    they are. Painted in ``paintEvent`` instead of an f-string stylesheet.
    """

    changed = Signal()

    def __init__(self, rgba: tuple[int, int, int, int] = (0, 0, 0, 255),
                 tokens: dict[str, str] | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self._rgba = tuple(int(v) for v in rgba)
        self._tokens = tokens
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumHeight(CONTROL_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.clicked.connect(self._pick)
        self._update_tooltip()

    # -- API compatible with gui.ColorButton --------------------------------
    def rgba(self) -> tuple[int, int, int, int]:
        return self._rgba

    def set_rgba(self, rgba: tuple[int, int, int, int], emit: bool = True) -> None:
        self._rgba = tuple(int(v) for v in rgba)
        self._update_tooltip()
        self.update()
        if emit:
            self.changed.emit()

    def sizeHint(self) -> QSize:
        return QSize(132, CONTROL_HEIGHT)

    def _update_tooltip(self) -> None:
        r, g, b, a = self._rgba
        self.setToolTip(f"RGBA {r}, {g}, {b}, {a}")

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor(*self._rgba), self, options=QColorDialog.ShowAlphaChannel)
        if c.isValid():
            self.set_rgba((c.red(), c.green(), c.blue(), c.alpha()))

    def paintEvent(self, _event: Any) -> None:
        t = _tokens(self._tokens)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r_md = RADIUS["r_md"]
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        # button body
        p.setPen(QPen(QColor(t["border_strong"] if self.isEnabled() else t["border"]), 1))
        p.setBrush(QColor(t["surface_alt"] if self.underMouse() and self.isEnabled() else t["surface"]))
        p.drawRoundedRect(rect, r_md, r_md)
        # swatch with checkerboard (alpha must be visible)
        sw = self.height() - 2 * SPACING["sp_2"] + 2
        swatch = QRectF(SPACING["sp_2"] - 1, SPACING["sp_2"] - 1, sw, sw)
        path = QPainterPath()
        path.addRoundedRect(swatch, RADIUS["r_sm"], RADIUS["r_sm"])
        p.save()
        p.setClipPath(path)
        p.setPen(Qt.NoPen)
        light, dark = QColor(t["text_muted"]), QColor(t["border"])
        cell = 5
        cols = int(sw // cell) + 1
        for i in range(cols):
            for j in range(cols):
                p.setBrush(light if (i + j) % 2 == 0 else dark)
                p.drawRect(QRectF(swatch.left() + i * cell, swatch.top() + j * cell, cell, cell))
        p.setBrush(QColor(*self._rgba))
        p.drawRect(swatch)
        p.restore()
        p.setPen(QPen(QColor(t["border_strong"]), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(swatch, RADIUS["r_sm"], RADIUS["r_sm"])
        # text: hex + alpha percent
        r, g, b, a = self._rgba
        label = f"#{r:02X}{g:02X}{b:02X}"
        alpha = f"{round(a / 255 * 100)} %"
        text_rect = QRectF(swatch.right() + SPACING["sp_2"], 0,
                           self.width() - swatch.right() - 2 * SPACING["sp_2"], self.height())
        p.setPen(QColor(t["text"] if self.isEnabled() else t["text_disabled"]))
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, label)
        p.setPen(QColor(t["text_muted"]))
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignRight, alpha)
        if self.hasFocus():
            _focus_ring(p, rect, r_md, t)


# ---------------------------------------------------------------------------
# NumberField
# ---------------------------------------------------------------------------

class NumberField(QWidget):
    """QDoubleSpinBox with suffix, locale and separate "-" / "+" buttons.

    The native up/down arrows are hidden (``NoButtons``); two QToolButton at
    the side are easier to hit and align with the 32 px control height. The
    spin box keeps keyboard behaviour (arrows, Page Up/Down) and the app's
    WheelGuard still applies because it filters QAbstractSpinBox.
    """

    valueChanged = Signal(float)

    def __init__(self, minimum: float = 0.0, maximum: float = 100.0, step: float = 1.0,
                 decimals: int = 2, suffix: str = "", value: float | None = None,
                 locale: QLocale | None = None, buttons: bool = True,
                 parent: QWidget | None = None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACING["sp_1"])
        self.spin = QDoubleSpinBox()
        self.spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.spin.setRange(minimum, maximum)
        self.spin.setSingleStep(step)
        self.spin.setDecimals(decimals)
        self.spin.setKeyboardTracking(False)   # emit once, after editing
        # QDoubleSpinBox derives its minimum width from the widest value text
        # ("100000,00 s"), which blows up narrow inspectors. Ignore that hint
        # and let the form layout distribute width; 56 px still shows "9999,9".
        self.spin.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.spin.setMinimumWidth(64)
        if suffix:
            self.spin.setSuffix(suffix)
        if locale is not None:
            self.spin.setLocale(locale)
        if value is not None:
            self.spin.setValue(value)
        self.minus = QToolButton()
        self.minus.setText("-")
        self.minus.setAutoRepeat(True)
        self.minus.setFocusPolicy(Qt.NoFocus)
        self.minus.setToolTip("Decrease")
        self.plus = QToolButton()
        self.plus.setText("+")
        self.plus.setAutoRepeat(True)
        self.plus.setFocusPolicy(Qt.NoFocus)
        self.plus.setToolTip("Increase")
        for b in (self.minus, self.plus):
            b.setFixedSize(CONTROL_HEIGHT, CONTROL_HEIGHT)
            b.setVisible(buttons)   # buttons=False for tight pair rows (X / Y)
        self.minus.clicked.connect(self.spin.stepDown)
        self.plus.clicked.connect(self.spin.stepUp)
        lay.addWidget(self.minus)
        lay.addWidget(self.spin, 1)
        lay.addWidget(self.plus)
        self.spin.valueChanged.connect(self.valueChanged)
        self.setFocusProxy(self.spin)

    # proxies, so callers can treat NumberField like a spin box
    def value(self) -> float:
        return self.spin.value()

    def setValue(self, v: float) -> None:
        self.spin.setValue(v)

    def setRange(self, lo: float, hi: float) -> None:
        self.spin.setRange(lo, hi)

    def setSingleStep(self, step: float) -> None:
        self.spin.setSingleStep(step)

    def setDecimals(self, n: int) -> None:
        self.spin.setDecimals(n)

    def setSuffix(self, s: str) -> None:
        self.spin.setSuffix(s)

    def setInvalid(self, invalid: bool) -> None:
        self.spin.setProperty("invalid", "true" if invalid else "false")
        self.spin.style().unpolish(self.spin)
        self.spin.style().polish(self.spin)


# ---------------------------------------------------------------------------
# PathField
# ---------------------------------------------------------------------------

class PathField(QWidget):
    """File/folder path: elided display, browse button, drag and drop.

    The line edit shows the path elided from the left (the file name stays
    visible) while unfocused and the full path while editing. ``path()`` always
    returns the full value. ``mode`` is "open", "save" or "dir".
    """

    changed = Signal(str)

    def __init__(self, mode: str = "open", filter: str = "", placeholder: str = "",
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._path = ""
        self._mode = mode
        self._filter = filter
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACING["sp_1"])
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.editingFinished.connect(self._commit_edit)
        self.edit.installEventFilter(self)
        self.browse = QToolButton()
        self.browse.setText("...")
        self.browse.setToolTip("Browse")
        self.browse.setFixedSize(CONTROL_HEIGHT + 4, CONTROL_HEIGHT)
        self.browse.clicked.connect(self._browse)
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.browse)
        self.setAcceptDrops(True)
        self.setFocusProxy(self.edit)

    def path(self) -> str:
        return self._path

    def set_path(self, path: str, emit: bool = True) -> None:
        self._path = path or ""
        self.edit.setToolTip(self._path)
        self._show_elided()
        if emit:
            self.changed.emit(self._path)

    def _show_elided(self) -> None:
        if self.edit.hasFocus():
            self.edit.setText(self._path)
            return
        fm = QFontMetrics(self.edit.font())
        avail = max(40, self.edit.width() - 2 * SPACING["sp_2"] - 4)
        self.edit.setText(fm.elidedText(self._path, Qt.ElideLeft, avail))

    def _commit_edit(self) -> None:
        text = self.edit.text().strip()
        if text and text != self._path and "…" not in text:
            self.set_path(text)

    def eventFilter(self, obj: Any, event: Any) -> bool:
        if obj is self.edit:
            et = event.type()
            if et == event.Type.FocusIn:
                self.edit.setText(self._path)
            elif et in (event.Type.FocusOut, event.Type.Resize):
                QTimer.singleShot(0, self._show_elided)
        return super().eventFilter(obj, event)

    def _browse(self) -> None:
        start = self._path or ""
        if self._mode == "dir":
            chosen = QFileDialog.getExistingDirectory(self, "", start)
        elif self._mode == "save":
            chosen, _ = QFileDialog.getSaveFileName(self, "", start, self._filter)
        else:
            chosen, _ = QFileDialog.getOpenFileName(self, "", start, self._filter)
        if chosen:
            self.set_path(chosen)

    def dragEnterEvent(self, e: QDragEnterEvent) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent) -> None:
        for url in e.mimeData().urls():
            local = url.toLocalFile()
            if local:
                self.set_path(local)
                break


# ---------------------------------------------------------------------------
# InlineMessage
# ---------------------------------------------------------------------------

class InlineMessage(QWidget):
    """One-line message under a field or section, with a coloured left bar.

    ``kind`` is one of info, success, warning, danger (token names). Hidden when
    empty so it takes no space in the form. Optional ``action_text`` shows a
    ghost button next to the message; clicking it emits ``actionClicked`` —
    the caller decides what the action does (e.g. "apply the new value").
    """

    KINDS = ("info", "success", "warning", "danger")

    actionClicked = Signal()

    def __init__(self, tokens: dict[str, str] | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self._tokens = tokens
        self._kind = "info"
        lay = QHBoxLayout(self)
        lay.setContentsMargins(SPACING["sp_3"], SPACING["sp_1"], SPACING["sp_2"], SPACING["sp_1"])
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.label, 1)
        self.action_btn = QPushButton()
        self.action_btn.setProperty("kind", "ghost")
        self.action_btn.clicked.connect(self.actionClicked.emit)
        self.action_btn.hide()
        lay.addWidget(self.action_btn)
        self.hide()

    def show_message(self, text: str, kind: str = "info",
                      action_text: str | None = None) -> None:
        if kind not in self.KINDS:
            kind = "info"
        self._kind = kind
        set_role(self.label, kind)
        self.label.setText(text)
        if action_text:
            self.action_btn.setText(action_text)
            if _HAVE_THEME:
                repolish(self.action_btn)
            self.action_btn.show()
        else:
            self.action_btn.hide()
        self.setVisible(bool(text))
        self.update()

    def clear(self) -> None:
        self.label.clear()
        self.action_btn.hide()
        self.hide()

    def paintEvent(self, _event: Any) -> None:
        t = _tokens(self._tokens)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(t["surface_alt"]))
        p.drawRoundedRect(QRectF(self.rect()), RADIUS["r_sm"], RADIUS["r_sm"])
        p.setBrush(QColor(t[self._kind]))
        p.drawRoundedRect(QRectF(0, 0, 3, self.height()), 1.5, 1.5)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def set_busy(button: QAbstractButton, busy: bool, text: str | None = None) -> None:
    """Disable a button while a worker runs and show a progress caption.

    Stores the original text in a dynamic property so ``set_busy(btn, False)``
    restores it. Pair with an indeterminate QProgressBar (``setRange(0, 0)``).
    """
    if busy:
        if button.property("idle_text") is None:
            button.setProperty("idle_text", button.text())
        if text:
            button.setText(text)
        button.setEnabled(False)
        button.setProperty("busy", "true")
    else:
        idle = button.property("idle_text")
        if idle is not None:
            button.setText(idle)
            button.setProperty("idle_text", None)
        button.setEnabled(True)
        button.setProperty("busy", "false")
    button.style().unpolish(button)
    button.style().polish(button)


def status_message(statusbar: QStatusBar, text: str, kind: str = "info",
                   timeout_ms: int = 5000) -> None:
    """Coloured status message: a QLabel with ``role=kind`` in the status bar.

    ``QStatusBar.showMessage`` cannot be coloured per message, so the message
    lives in a dedicated label (created on first use, object name
    ``statusMessage``). ``timeout_ms`` <= 0 keeps it until the next call.
    """
    label = statusbar.findChild(QLabel, "statusMessage")
    if label is None:
        label = QLabel()
        label.setObjectName("statusMessage")
        statusbar.addWidget(label, 1)
    label.setText(text)
    set_role(label, kind if kind in InlineMessage.KINDS else "muted")
    timer = getattr(label, "_clear_timer", None)
    if timer is None:
        timer = QTimer(label)
        timer.setSingleShot(True)
        timer.timeout.connect(label.clear)
        label._clear_timer = timer
    timer.stop()
    if timeout_ms > 0:
        timer.start(timeout_ms)


# ---------------------------------------------------------------------------
# StatusDot
# ---------------------------------------------------------------------------

class StatusDot(QWidget):
    """Kropka statusu w kolorze roli (`success`/`warning`/`danger`/`info`/`muted`).

    Zastępuje `QLabel.setStyleSheet(f"background:{kolor}; border-radius:7px;")` —
    kolor pochodzi z tokenów bieżącego motywu, więc przełączenie dark↔light
    nie zostawia starych barw.
    """

    def __init__(self, role: str = "muted", size: int = 14,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._role = role
        self.setFixedSize(size, size)

    def role(self) -> str:
        return self._role

    def set_role(self, role: str) -> None:
        self._role = role
        self.update()

    def paintEvent(self, _event: Any) -> None:
        tokens = _tokens(None)
        color = tokens.get(self._role, tokens["text_muted"])
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        r = QRectF(0.0, 0.0, float(self.width()), float(self.height()))
        p.drawEllipse(r.adjusted(1, 1, -1, -1))
