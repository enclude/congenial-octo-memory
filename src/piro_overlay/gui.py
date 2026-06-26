"""Aplikacja desktop (PySide6) dla Piro Overlay.

Warstwa UI — całość logiki domenowej pochodzi z modułów `parser`, `api`, `audio_sync`,
`overlay`, `render`. Operacje ciężkie (render, analiza audio) biegną w wątkach roboczych
(QThread), aby nie blokować interfejsu.

Funkcje UI: drag&drop pliku, widok ścieżki audio (klik = kotwica T0, uchwyty = przycięcie),
przycinanie fragmentu z eksportem tylko jego, podgląd na żywo w obniżonej jakości,
konfiguracja wyglądu nakładki, domyślny plik wyjściowy z sufiksem _PiRoOverlay.
"""

from __future__ import annotations

import math
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QColorDialog, QComboBox, QCheckBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QRadioButton, QScrollArea, QSpinBox,
    QPlainTextEdit, QVBoxLayout, QWidget,
)

from PIL import Image
from PIL.ImageQt import ImageQt

from . import __version__, api, audio_sync, ffmpeg, overlay, render, resources
from .models import ANCHOR_POSITIONS, AnchorMode, Lang, OverlayStyle, Session
from .parser import parse_timeline

PREVIEW_HEIGHT = 360  # obniżona jakość podglądu — szybciej i lżej dla dużych plików
_HANDLE_PX = 8        # tolerancja trafienia uchwytu przycięcia (px)
_AXIS_H = 22          # wysokość paska osi czasu (px)

# Kandydaci na krok głównych kresek (major ticks) — od 0.05 s do 1 godziny.
_TICK_STEPS = (0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600)

# Krok kresek pośrednich (minor ticks) dla każdego kroku głównego.
_MINOR_STEP: dict[float, float | None] = {
    0.05:  None,   # przy 0.05 s minor byłyby za gęste
    0.1:   0.05,
    0.2:   0.1,
    0.5:   0.1,
    1.0:   0.2,
    2.0:   0.5,
    5.0:   1.0,
    10.0:  2.0,
    15.0:  5.0,
    30.0:  5.0,
    60.0:  10.0,
    120.0: 30.0,
    300.0: 60.0,
    600.0: 60.0,
    900.0: 300.0,
    1800.0: 300.0,
    3600.0: 600.0,
}


def _fmt_axis_time(t: float) -> str:
    """Etykieta czasu na osi: 's' dla < 60 s, 'M:SS' dla dłuższych nagrań."""
    if t < 60:
        # :g usuwa zbędne zera (0.10 → 0.1, 1.00 → 1)
        return f"{t:g}s"
    m, s = divmod(int(round(t)), 60)
    return f"{m}:{s:02d}"


def _nice_tick_step(span: float, width: int, target_px: int = 100) -> float:
    """Dobiera krok głównych kresek tak, by etykiety były co ~target_px pikseli."""
    if span <= 0 or width <= 0:
        return 1.0
    raw = target_px * span / width
    for step in _TICK_STEPS:
        if step >= raw - 1e-9:
            return step
    return _TICK_STEPS[-1]


# ----------------------------- wątki robocze -----------------------------
class RenderWorker(QThread):
    progress = Signal(float)
    finished_ok = Signal(str)
    failed = Signal(str)
    encoder_used = Signal(str)
    warn = Signal(str)

    def __init__(self, kwargs: dict):
        super().__init__()
        self._kwargs = kwargs

    def run(self):
        try:
            render.render_video(progress_cb=self.progress.emit,
                                on_encoder=self.encoder_used.emit,
                                on_warn=self.warn.emit, **self._kwargs)
            self.finished_ok.emit(str(self._kwargs["out_path"]))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class FrameExtractWorker(QThread):
    """Wyciąga jedną klatkę z wideo w tle — FFmpeg nie blokuje UI."""
    done = Signal(object, float)   # (PIL.Image, anchor_t)

    def __init__(self, video_path: str, anchor_t: float):
        super().__init__()
        self.video_path = video_path
        self.anchor_t = anchor_t

    def run(self):
        try:
            with tempfile.TemporaryDirectory() as tmp:
                frame_png = ffmpeg.extract_frame(
                    self.video_path, self.anchor_t,
                    Path(tmp) / "f.png", scale_height=PREVIEW_HEIGHT)
                frame = Image.open(frame_png).convert("RGBA")
                frame.load()  # wczytaj do pamięci zanim katalog tymczasowy zniknie
            self.done.emit(frame, self.anchor_t)
        except Exception:  # noqa: BLE001 — podgląd nie krytyczny
            pass


class WaveformWorker(QThread):
    """Liczy obwiednię audio + onsety poza wątkiem UI."""
    done = Signal(list, float, list)
    failed = Signal(str)

    def __init__(self, video_path: str):
        super().__init__()
        self.video_path = video_path

    def run(self):
        try:
            env, dur = audio_sync.compute_waveform(self.video_path)
            onsets = audio_sync.detect_onsets(self.video_path)
            self.done.emit(env, dur, onsets)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


# ----------------------------- waveform -----------------------------
class WaveformWidget(QWidget):
    """Wizualizacja ścieżki audio z interakcją:

    - lewy klik (poza uchwytami) → ustawia kotwicę T0,
    - przeciągnięcie uchwytu (zielony=start, czerwony=koniec) → przycięcie fragmentu,
    - cienkie znaczniki = wykryte onsety (pomoc w trafieniu sygnału/strzału).
    """

    anchorChanged = Signal(float)
    trimChanged = Signal(float, float)

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(140)
        self.env: list[float] = []
        self.duration = 0.0
        self.onsets: list[float] = []
        self.anchor: float | None = None
        self.anchor_label = "T0"      # "T0" (beep) lub "T1" (pierwszy strzał) wg trybu
        self.trim_start = 0.0
        self.trim_end = 0.0
        # okno widoku (zoom): widoczny zakres czasu [view_start, view_end]
        self.view_start = 0.0
        self.view_end = 0.0
        self._drag: str | None = None  # "start" | "end" | None
        self._pan = None               # (x0, vs, ve) podczas przesuwania
        self.setCursor(Qt.CrossCursor)
        self.setToolTip("Klik = ustaw kotwicę (snap do strzału) · kółko = zoom · "
                        "prawy przycisk = przesuń · dwuklik = reset zoomu")

    def set_data(self, env, duration, onsets):
        self.env = env
        self.duration = duration
        self.onsets = onsets
        self.trim_start = 0.0
        self.trim_end = duration
        self.anchor = None
        self.view_start = 0.0
        self.view_end = duration
        self.update()

    def set_anchor(self, t: float):
        self.anchor = t
        self.update()

    def set_trim(self, start: float, end: float):
        self.trim_start, self.trim_end = start, end
        self.update()

    # --- okno widoku ---
    def _span(self) -> float:
        return max(self.view_end - self.view_start, 1e-6)

    def _in_view(self, t: float) -> bool:
        return self.view_start <= t <= self.view_end

    # --- mapowanie czas <-> px (względem okna widoku) ---
    def _t2x(self, t: float) -> float:
        return (t - self.view_start) / self._span() * self.width()

    def _x2t(self, x: float) -> float:
        if self.width() <= 0:
            return self.view_start
        t = self.view_start + x / self.width() * self._span()
        return max(self.view_start, min(self.view_end, t))

    # --- rysowanie ---
    def paintEvent(self, _):
        p = QPainter(self)
        w, h = self.width(), self.height()
        plot_h = h - _AXIS_H          # obszar waveformu (nad osią)
        mid = plot_h / 2
        p.fillRect(self.rect(), QColor(24, 26, 34))
        if not self.env or self.duration <= 0:
            p.setPen(QColor(150, 150, 150))
            p.drawText(self.rect(), Qt.AlignCenter, "Ścieżka audio pojawi się po wczytaniu wideo")
            return

        # przyciemnienie poza fragmentem przycięcia
        xs, xe = self._t2x(self.trim_start), self._t2x(self.trim_end)
        if xs > 0:
            p.fillRect(0, 0, int(xs), plot_h, QColor(0, 0, 0, 120))
        if xe < w:
            p.fillRect(int(xe), 0, w - int(xe), plot_h, QColor(0, 0, 0, 120))

        # waveform — tylko kubełki w widoku
        p.setPen(QColor(90, 170, 230))
        n = len(self.env)
        i_lo = max(0, int(self.view_start / self.duration * n))
        i_hi = min(n, int(self.view_end / self.duration * n) + 1)
        for i in range(i_lo, i_hi):
            t = i / n * self.duration
            x = self._t2x(t)
            half = self.env[i] * (mid - 4)
            p.drawLine(int(x), int(mid - half), int(x), int(mid + half))

        # onsety (w widoku)
        p.setPen(QPen(QColor(255, 196, 0, 120), 1))
        for t in self.onsets:
            if self._in_view(t):
                x = int(self._t2x(t))
                p.drawLine(x, 0, x, plot_h)

        # uchwyty przycięcia
        p.setPen(QPen(QColor(80, 220, 120), 2))
        p.drawLine(int(xs), 0, int(xs), plot_h)
        p.setPen(QPen(QColor(235, 80, 80), 2))
        p.drawLine(int(xe), 0, int(xe), plot_h)

        # kotwica
        if self.anchor is not None and self._in_view(self.anchor):
            p.setPen(QPen(QColor(0, 230, 230), 2))
            xa = int(self._t2x(self.anchor))
            p.drawLine(xa, 0, xa, plot_h)

        self._paint_markers(p, w, plot_h)
        self._paint_axis(p, w, h, plot_h)

    def _tag(self, p: QPainter, x: int, text: str, color: QColor, align: str, y: int = 0):
        """Rysuje kolorową etykietę-znacznik (align: left/center/right, y: góra prostokąta)."""
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(text)
        pad = 4
        bw = tw + 2 * pad
        if align == "left":
            bx = x
        elif align == "right":
            bx = x - bw
        else:
            bx = x - bw // 2
        bx = max(0, min(bx, self.width() - bw))
        p.fillRect(bx, y, bw, 16, color)
        p.setPen(QColor(15, 16, 22))
        p.drawText(bx + pad, y + 12, text)

    def _paint_markers(self, p: QPainter, w: int, plot_h: int):
        """Kolorowe znaczniki: szary=krawędzie wideo, cyjan=T0/T1, zielony/czerwony=przycięcie."""
        edge = QColor(150, 160, 180)   # szary — krawędzie wideo
        cyan = QColor(0, 210, 210)     # T0/T1
        green = QColor(80, 220, 120)   # początek przycięcia
        red = QColor(235, 80, 80)      # koniec przycięcia

        # krawędzie wideo — szare, przerywane (tylko gdy w widoku)
        p.setPen(QPen(edge, 1, Qt.DashLine))
        if self._in_view(0.0):
            x0 = int(self._t2x(0.0))
            p.drawLine(x0, 0, x0, plot_h)
            self._tag(p, x0, f"Start {_fmt_axis_time(0)}", edge, "left")
        if self._in_view(self.duration):
            xd = int(self._t2x(self.duration))
            p.drawLine(xd, 0, xd, plot_h)
            self._tag(p, xd, f"Koniec {_fmt_axis_time(self.duration)}", edge, "right")

        if self.anchor is not None and self._in_view(self.anchor):
            self._tag(p, int(self._t2x(self.anchor)),
                      f"{self.anchor_label} {_fmt_axis_time(self.anchor)}", cyan, "center")

        # dolny rząd (nad osią): zakres przycięcia, zgodnie z kolorami uchwytów
        ty = plot_h - 16
        if self._in_view(self.trim_start):
            self._tag(p, int(self._t2x(self.trim_start)),
                      f"Od {_fmt_axis_time(self.trim_start)}", green, "center", y=ty)
        if self._in_view(self.trim_end):
            self._tag(p, int(self._t2x(self.trim_end)),
                      f"Do {_fmt_axis_time(self.trim_end)}", red, "center", y=ty)

    def _paint_axis(self, p: QPainter, w: int, h: int, plot_h: int):
        """Rysuje oś czasu (podziałka + etykiety) dla aktualnego okna widoku."""
        p.fillRect(0, plot_h, w, _AXIS_H, QColor(18, 19, 26))
        p.setPen(QPen(QColor(90, 95, 110), 1))
        p.drawLine(0, plot_h, w, plot_h)

        step = _nice_tick_step(self._span(), w)
        t = math.ceil(self.view_start / step) * step
        while t <= self.view_end + 1e-6:
            x = int(self._t2x(t))
            p.setPen(QPen(QColor(90, 95, 110), 1))
            p.drawLine(x, plot_h, x, plot_h + 4)
            p.setPen(QColor(170, 175, 190))
            label = _fmt_axis_time(round(t, 3))
            if x <= 1:
                p.drawText(x + 2, h - 5, label)
            elif x >= w - 2:
                p.drawText(x - 4 * len(label) - 2, h - 5, label)
            else:
                p.drawText(x - 4 * len(label), h - 5, label)
            t += step

    def _snap_to_onset(self, t: float) -> float:
        """Dostraja kliknięcie do najbliższego wykrytego onsetu (jeśli blisko)."""
        if not self.onsets:
            return t
        tol = 15 / max(self.width(), 1) * self._span()  # ~15 px tolerancji w czasie
        best = min(self.onsets, key=lambda o: abs(o - t))
        return best if abs(best - t) <= tol else t

    # --- interakcja ---
    def wheelEvent(self, e):
        if self.duration <= 0:
            return
        cursor_t = self._x2t(e.position().x())
        factor = 0.8 if e.angleDelta().y() > 0 else 1.25  # do wewnątrz / na zewnątrz
        span = self._span()
        new_span = max(0.05, min(self.duration, span * factor))
        frac = (cursor_t - self.view_start) / span
        ns = cursor_t - frac * new_span
        ne = ns + new_span
        if ns < 0:
            ns, ne = 0.0, new_span
        if ne > self.duration:
            ne, ns = self.duration, self.duration - new_span
        self.view_start, self.view_end = max(0.0, ns), min(self.duration, ne)
        self.update()
        e.accept()

    def mouseDoubleClickEvent(self, _):
        self.view_start, self.view_end = 0.0, self.duration
        self.update()

    def mousePressEvent(self, e):
        if self.duration <= 0:
            return
        if e.button() == Qt.RightButton:
            self._pan = (e.position().x(), self.view_start, self.view_end)
            self.setCursor(Qt.ClosedHandCursor)
            return
        x = e.position().x()
        if abs(x - self._t2x(self.trim_start)) <= _HANDLE_PX:
            self._drag = "start"
        elif abs(x - self._t2x(self.trim_end)) <= _HANDLE_PX:
            self._drag = "end"
        else:
            self.set_anchor(self._snap_to_onset(self._x2t(x)))
            self.anchorChanged.emit(self.anchor)

    def mouseMoveEvent(self, e):
        if self._pan is not None:
            x0, vs, ve = self._pan
            span = ve - vs
            dt = (e.position().x() - x0) / max(self.width(), 1) * span
            ns, ne = vs - dt, ve - dt
            if ns < 0:
                ns, ne = 0.0, span
            if ne > self.duration:
                ne, ns = self.duration, self.duration - span
            self.view_start, self.view_end = max(0.0, ns), min(self.duration, ne)
            self.update()
            return
        if not self._drag:
            return
        t = self._x2t(e.position().x())
        if self._drag == "start":
            self.trim_start = min(t, self.trim_end - 0.05)
        else:
            self.trim_end = max(t, self.trim_start + 0.05)
        self.update()
        self.trimChanged.emit(self.trim_start, self.trim_end)

    def mouseReleaseEvent(self, _):
        self._drag = None
        if self._pan is not None:
            self._pan = None
            self.setCursor(Qt.CrossCursor)


# ----------------------------- okno główne -----------------------------
class ColorButton(QPushButton):
    changed = Signal()

    def __init__(self, rgba):
        super().__init__()
        self._rgba = rgba
        self.clicked.connect(self._pick)
        self._refresh()

    def rgba(self):
        return self._rgba

    def _pick(self):
        c = QColorDialog.getColor(QColor(*self._rgba), self,
                                  options=QColorDialog.ShowAlphaChannel)
        if c.isValid():
            self._rgba = (c.red(), c.green(), c.blue(), c.alpha())
            self._refresh()
            self.changed.emit()

    def _refresh(self):
        r, g, b, a = self._rgba
        self.setText(f"RGBA {r},{g},{b},{a}")
        self.setStyleSheet(
            f"QPushButton {{"
            f"background-color: #3c3c3c;"
            f"color: #e0e0e0;"
            f"border-left: 20px solid rgba({r},{g},{b},{a});"
            f"border-top: 1px solid #555; border-bottom: 1px solid #555; border-right: 1px solid #555;"
            f"padding: 3px 8px;"
            f"}}"
        )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.session: Session | None = None
        self.video_path: str | None = None
        self.worker: RenderWorker | None = None
        self.wave_worker: WaveformWorker | None = None
        self.last_output: str | None = None
        self._used_encoder: str | None = None
        # Podgląd — cache klatki + timer debouncujący ekstrakcję FFmpeg
        self._cached_frame: Image.Image | None = None
        self._cached_frame_t: float = -1.0
        self._frame_worker: FrameExtractWorker | None = None
        self._preview_timer = QTimer()
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._do_request_frame)
        self.setWindowTitle(f"Piro Overlay v{__version__}")
        self.setWindowIcon(QIcon(resources.icon_path()))
        self.setAcceptDrops(True)  # drag&drop pliku
        self._build_ui()

    # ---------- drag & drop ----------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            path = url.toLocalFile()
            if path:
                self._set_video(path)
                break

    # ---------- UI ----------
    def _build_ui(self):
        central = QWidget()
        root = QHBoxLayout(central)

        left = QVBoxLayout()
        left.addWidget(self._input_group())
        left.addWidget(self._sync_group())
        left.addWidget(self._appearance_group())
        left.addWidget(self._output_group())
        left.addStretch(1)
        # Przewijanie lewej kolumny — przy wielu sekcjach nic nie wypada poza okno.
        left_container = QWidget()
        left_container.setLayout(left)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setWidget(left_container)
        left_scroll.setMinimumWidth(420)
        root.addWidget(left_scroll, 2)

        right = QVBoxLayout()
        self.preview_label = QLabel("Przeciągnij tu plik wideo lub użyj „…”")
        self.preview_label.setMinimumSize(480, 270)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("background:#222;color:#aaa;")
        right.addWidget(self.preview_label, 3)

        self.waveform = WaveformWidget()
        self.waveform.anchorChanged.connect(self._on_wave_anchor)
        self.waveform.trimChanged.connect(self._on_wave_trim)
        right.addWidget(self.waveform, 1)
        root.addLayout(right, 3)

        # Etykieta kotwicy (T0/T1) zależy od trybu — podłączamy po utworzeniu waveformu.
        self.anchor_combo.currentIndexChanged.connect(self._on_anchor_mode_changed)
        self._on_anchor_mode_changed()

        self.setCentralWidget(central)

    def _anchor_mode(self) -> AnchorMode:
        """Bezpieczny odczyt trybu kotwicy — konwertuje wartość Qt z powrotem do AnchorMode."""
        return AnchorMode(self.anchor_combo.currentData())

    def _on_anchor_mode_changed(self, *_):
        mode = self._anchor_mode()
        self.waveform.anchor_label = "T0" if mode == AnchorMode.START_SIGNAL else "T1"
        self.waveform.update()
        self._update_preview()

    def _input_group(self):
        box = QGroupBox("Wejście")
        form = QFormLayout(box)
        self.video_edit = QLineEdit()
        browse = QPushButton("…")
        browse.clicked.connect(self._choose_video)
        row = QHBoxLayout(); row.addWidget(self.video_edit); row.addWidget(browse)
        form.addRow("Wideo", _wrap(row))

        self.rb_text = QRadioButton("Tekst")
        self.rb_id = QRadioButton("ID (API)")
        self.rb_text.setChecked(True)
        grp = QButtonGroup(self); grp.addButton(self.rb_text); grp.addButton(self.rb_id)
        srow = QHBoxLayout(); srow.addWidget(self.rb_text); srow.addWidget(self.rb_id)
        form.addRow("Źródło", _wrap(srow))

        self.timeline_edit = QPlainTextEdit()
        self.timeline_edit.setPlaceholderText("1: 2.81s | 2: 4.63s (+1.82s) | ...")
        self.timeline_edit.setMaximumHeight(80)
        self.timeline_edit.textChanged.connect(self._update_preview)
        form.addRow("Oś czasu", self.timeline_edit)

        self.id_spin = QSpinBox(); self.id_spin.setRange(1, 10_000_000)
        fetch = QPushButton("Pobierz"); fetch.clicked.connect(self._fetch_id)
        idrow = QHBoxLayout(); idrow.addWidget(self.id_spin); idrow.addWidget(fetch)
        form.addRow("ID", _wrap(idrow))
        return box

    def _sync_group(self):
        box = QGroupBox("Synchronizacja i przycięcie")
        form = QFormLayout(box)

        self.anchor_combo = QComboBox()
        # Przechowujemy .value (czysty str) — PySide6 konwertuje str-subclassy
        # (enum dziedziczący po str) do plain str w QVariant, co łamie porównania is.
        self.anchor_combo.addItem("Sygnał startu", AnchorMode.START_SIGNAL.value)
        self.anchor_combo.addItem("Pierwszy strzał", AnchorMode.FIRST_SHOT.value)
        form.addRow("Typ kotwicy", self.anchor_combo)

        detect = QPushButton("Wykryj kotwicę (w zaznaczonym fragmencie)")
        detect.clicked.connect(self._detect)
        nextc = QPushButton("Następna proponowana kotwica")
        nextc.clicked.connect(self._next_candidate)
        drow = QHBoxLayout(); drow.addWidget(detect); drow.addWidget(nextc)
        form.addRow(_wrap(drow))

        self.t0_spin = _dspin(0, 100000, 0.05, " s")
        self.t0_spin.valueChanged.connect(self._on_t0_spin)
        form.addRow("Kotwica (czas)", self.t0_spin)

        self.trim_start_spin = _dspin(0, 100000, 0.1, " s")
        self.trim_end_spin = _dspin(0, 100000, 0.1, " s")
        self.trim_start_spin.valueChanged.connect(self._on_trim_spin)
        self.trim_end_spin.valueChanged.connect(self._on_trim_spin)
        trow = QHBoxLayout(); trow.addWidget(self.trim_start_spin); trow.addWidget(self.trim_end_spin)
        form.addRow("Przytnij od / do", _wrap(trow))

        self.tail_spin = _dspin(0.0, 60.0, 0.5, " s", 5.0)
        form.addRow("Margines po ostatnim strzale", self.tail_spin)
        autotrim_btn = QPushButton("Auto-przycięcie (ustaw zakres: 5 s przed startem → ostatni strzał + margines)")
        autotrim_btn.clicked.connect(self._apply_auto_trim)
        form.addRow(autotrim_btn)
        return box

    def _appearance_group(self):
        box = QGroupBox("Wygląd nakładki")
        form = QFormLayout(box)

        self.lang_combo = QComboBox()
        self.lang_combo.addItem("Polski", Lang.PL)
        self.lang_combo.addItem("English", Lang.EN)
        self.lang_combo.currentIndexChanged.connect(self._update_preview)
        form.addRow("Język", self.lang_combo)

        self.scale_spin = _dspin(0.3, 5.0, 0.1, "", 1.0)
        self.scale_spin.valueChanged.connect(self._update_preview)
        form.addRow("Rozmiar (skala)", self.scale_spin)

        self.pos_combo = QComboBox(); self.pos_combo.addItems(list(ANCHOR_POSITIONS))
        self.pos_combo.setCurrentText("bottom-left")
        self.pos_combo.currentIndexChanged.connect(self._update_preview)
        form.addRow("Pozycja", self.pos_combo)

        self.off_x = _ispin(0, 2000, 32); self.off_y = _ispin(0, 2000, 32)
        self.off_x.valueChanged.connect(self._update_preview)
        self.off_y.valueChanged.connect(self._update_preview)
        orow = QHBoxLayout(); orow.addWidget(self.off_x); orow.addWidget(self.off_y)
        form.addRow("Offset X / Y", _wrap(orow))

        self.bg_btn = ColorButton((0, 0, 0, 170))
        self.text_btn = ColorButton((255, 255, 255, 255))
        self.accent_btn = ColorButton((255, 196, 0, 255))
        self.border_btn = ColorButton((255, 255, 255, 220))
        for b in (self.bg_btn, self.text_btn, self.accent_btn, self.border_btn):
            b.changed.connect(self._update_preview)
        form.addRow("Tło", self.bg_btn)
        form.addRow("Tekst", self.text_btn)
        form.addRow("Akcent", self.accent_btn)
        form.addRow("Obramowanie", self.border_btn)

        self.border_chk = QCheckBox("Włącz obramowanie"); self.border_chk.setChecked(True)
        self.border_chk.stateChanged.connect(self._update_preview)
        form.addRow(self.border_chk)
        self.border_w = _ispin(1, 30, 3)
        self.border_w.valueChanged.connect(self._update_preview)
        form.addRow("Grubość obramowania", self.border_w)

        self.banner_spin = _dspin(0.0, 10.0, 0.5, " s", 1.0)
        form.addRow("Czas planszy START", self.banner_spin)

        self.banner_scale_spin = _dspin(0.3, 5.0, 0.1, "", 1.0)
        self.banner_scale_spin.valueChanged.connect(self._update_preview)
        form.addRow("Rozmiar planszy START (skala)", self.banner_scale_spin)

        self.banner_bg_btn = ColorButton((0, 0, 0, 200))
        self.banner_bg_btn.changed.connect(self._update_preview)
        form.addRow("Tło / przezroczystość START", self.banner_bg_btn)

        self.banner_text_btn = ColorButton((255, 196, 0, 255))
        self.banner_text_btn.changed.connect(self._update_preview)
        form.addRow("Kolor tekstu START", self.banner_text_btn)

        self.banner_border_btn = ColorButton((255, 196, 0, 220))
        self.banner_border_btn.changed.connect(self._update_preview)
        form.addRow("Obramowanie START", self.banner_border_btn)

        self.banner_border_chk = QCheckBox("Włącz obramowanie START")
        self.banner_border_chk.setChecked(True)
        self.banner_border_chk.stateChanged.connect(self._update_preview)
        form.addRow(self.banner_border_chk)

        self.banner_border_w = _ispin(1, 30, 3)
        self.banner_border_w.valueChanged.connect(self._update_preview)
        form.addRow("Grubość obramowania START", self.banner_border_w)

        return box

    def _output_group(self):
        box = QGroupBox("Wyjście")
        v = QVBoxLayout(box)
        self.out_edit = QLineEdit()
        out_browse = QPushButton("…"); out_browse.clicked.connect(self._choose_output)
        orow = QHBoxLayout(); orow.addWidget(self.out_edit); orow.addWidget(out_browse)
        v.addLayout(orow)
        self.gpu_chk = QCheckBox("Akceleracja GPU (NVENC, jeśli dostępna)")
        self.gpu_chk.setChecked(True)
        v.addWidget(self.gpu_chk)
        self.nvenc_label = QLabel()
        self._refresh_nvenc_status()
        v.addWidget(self.nvenc_label)
        diag = QPushButton("Diagnostyka NVENC")
        diag.clicked.connect(self._show_nvenc_diag)
        v.addWidget(diag)
        self.progress = QProgressBar(); v.addWidget(self.progress)
        brow = QHBoxLayout()
        self.render_btn = QPushButton("Renderuj"); self.render_btn.clicked.connect(self._start_render)
        self.open_btn = QPushButton("Otwórz folder z wynikiem")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_output_folder)
        brow.addWidget(self.render_btn); brow.addWidget(self.open_btn)
        v.addLayout(brow)
        return box

    # ---------- logika ----------
    def current_style(self):
        return OverlayStyle(
            lang=self.lang_combo.currentData(),
            scale=self.scale_spin.value(),
            position=self.pos_combo.currentText(),
            offset_x=self.off_x.value(), offset_y=self.off_y.value(),
            bg_color=self.bg_btn.rgba(), text_color=self.text_btn.rgba(),
            accent_color=self.accent_btn.rgba(), border_color=self.border_btn.rgba(),
            border_enabled=self.border_chk.isChecked(), border_width=self.border_w.value(),
            start_banner_duration=self.banner_spin.value(),
            start_banner_scale=self.banner_scale_spin.value(),
            start_banner_bg_color=self.banner_bg_btn.rgba(),
            start_banner_text_color=self.banner_text_btn.rgba(),
            start_banner_border_enabled=self.banner_border_chk.isChecked(),
            start_banner_border_color=self.banner_border_btn.rgba(),
            start_banner_border_width=self.banner_border_w.value(),
        )

    def _choose_video(self):
        path, _ = QFileDialog.getOpenFileName(self, "Wybierz wideo", "",
                                              "Wideo (*.mp4 *.mov *.mkv *.avi)")
        if path:
            self._set_video(path)

    def _set_video(self, path: str):
        self.video_path = path
        self.video_edit.setText(path)
        p = Path(path)
        self.out_edit.setText(str(p.with_name(p.stem + "_PiRoOverlay.mp4")))
        # Inwaliduj cache — nowe wideo, stara klatka nieaktualna
        self._cached_frame = None
        self._cached_frame_t = -1.0
        self.preview_label.setText("Analiza audio…")
        self.wave_worker = WaveformWorker(path)
        self.wave_worker.done.connect(self._on_wave_done)
        self.wave_worker.failed.connect(lambda m: self.preview_label.setText("Błąd audio: " + m))
        self.wave_worker.start()
        self._request_frame()

    def _on_wave_done(self, env, dur, onsets):
        self.waveform.set_data(env, dur, onsets)
        for s in (self.trim_start_spin, self.trim_end_spin, self.t0_spin):
            s.setMaximum(max(dur, 1.0))
        self.trim_start_spin.blockSignals(True); self.trim_end_spin.blockSignals(True)
        self.trim_start_spin.setValue(0.0); self.trim_end_spin.setValue(dur)
        self.trim_start_spin.blockSignals(False); self.trim_end_spin.blockSignals(False)
        self._update_preview()

    def _choose_output(self):
        path, _ = QFileDialog.getSaveFileName(self, "Plik wyjściowy",
                                              self.out_edit.text() or "output.mp4",
                                              "Wideo (*.mp4)")
        if path:
            self.out_edit.setText(path)

    def _build_session(self):
        if self.rb_id.isChecked():
            return api.fetch_session(self.id_spin.value())
        shots = parse_timeline(self.timeline_edit.toPlainText())
        if self.session is not None:
            return replace(self.session, shots=shots)
        return Session(shots=shots)

    def _fetch_id(self):
        try:
            self.session = api.fetch_session(self.id_spin.value())
            self.timeline_edit.setPlainText(
                " | ".join(self._shot_to_text(s) for s in self.session.shots))
            self._update_preview()  # sukces = bez okna potwierdzenia, po prostu wypełnij dane
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Błąd API", str(exc))

    @staticmethod
    def _shot_to_text(shot):
        if shot.split is None:
            return f"{shot.numer}: {shot.czas:.2f}s"
        return f"{shot.numer}: {shot.czas:.2f}s (+{shot.split:.2f}s)"

    def _detect(self):
        if not self.video_path:
            QMessageBox.warning(self, "Brak wideo", "Najpierw wybierz plik wideo.")
            return
        detected = audio_sync.detect_start(
            self.video_path, start=self.trim_start_spin.value(),
            end=self.trim_end_spin.value() or None)
        if detected is None:
            QMessageBox.warning(self, "Detekcja", "Nie wykryto sygnału — ustaw ręcznie.")
            return
        self.t0_spin.setValue(detected)  # wywoła _on_t0_spin → waveform + podgląd

    def _next_candidate(self):
        """Proponuje kolejny wykryty onset (po aktualnej kotwicy) jako kotwicę."""
        onsets = self.waveform.onsets
        if not onsets:
            QMessageBox.warning(self, "Brak kandydatów",
                                "Najpierw wczytaj wideo (analiza audio wyznaczy kandydatów).")
            return
        cur = self.t0_spin.value()
        nxt = next((o for o in onsets if o > cur + 1e-3), onsets[0])  # wrap do pierwszego
        self.t0_spin.setValue(nxt)

    # --- synchronizacja waveform <-> spinboxy ---
    def _on_wave_anchor(self, t: float):
        self.t0_spin.setValue(t)

    def _on_wave_trim(self, start: float, end: float):
        self.trim_start_spin.blockSignals(True); self.trim_end_spin.blockSignals(True)
        self.trim_start_spin.setValue(start); self.trim_end_spin.setValue(end)
        self.trim_start_spin.blockSignals(False); self.trim_end_spin.blockSignals(False)

    def _on_t0_spin(self, v: float):
        self.waveform.set_anchor(v)
        self._request_frame()  # nowy czas → nowa klatka w tle (debounced)

    def _apply_auto_trim(self, *_):
        """Przycisk: ustaw przycięcie od (T0 − 5 s) do (ostatni strzał + margines)."""
        if not self.video_path:
            QMessageBox.warning(self, "Brak wideo", "Najpierw wybierz plik wideo.")
            return
        session = self.session or self._safe_session()
        if session is None or not session.shots:
            QMessageBox.warning(self, "Brak osi czasu",
                                "Podaj oś czasu strzałów (tekst lub pobierz po ID).")
            return
        mode = self._anchor_mode()
        real_t0 = audio_sync.resolve_t0(self.t0_spin.value(), mode, session.shots[0].czas)
        dur = self.waveform.duration or None
        start, end = render.auto_trim_window(
            real_t0, session.shots[-1].czas, tail=self.tail_spin.value(), duration=dur)
        self.trim_start_spin.setValue(start)
        self.trim_end_spin.setValue(end)

    def _on_trim_spin(self):
        self.waveform.set_trim(self.trim_start_spin.value(), self.trim_end_spin.value())

    def _request_frame(self):
        """Kotwica się zmieniła → wyciągnij nową klatkę w tle (debounce 250 ms)."""
        self._preview_timer.start(250)

    def _do_request_frame(self):
        """Uruchamiane przez timer — startuje workera jeśli nie ma aktywnego."""
        if not self.video_path:
            return
        anchor_t = max(0.0, self.t0_spin.value())
        if (self._frame_worker and self._frame_worker.isRunning()):
            if abs(self._frame_worker.anchor_t - anchor_t) < 0.01:
                return  # ten sam timestamp, poczekaj na wynik
            self._preview_timer.start(150)  # inny czas — retry gdy worker skończy
            return
        self._frame_worker = FrameExtractWorker(self.video_path, anchor_t)
        self._frame_worker.done.connect(self._on_frame_ready)
        self._frame_worker.start()

    def _on_frame_ready(self, frame: Image.Image, anchor_t: float):
        """Klatka gotowa → zapisz do cache i odśwież overlay."""
        current_t = max(0.0, self.t0_spin.value())
        self._cached_frame = frame
        self._cached_frame_t = anchor_t
        if abs(anchor_t - current_t) > 0.1:
            # Kotwica się zmieniła podczas ekstrakcji → poproś o nową
            self._request_frame()
            return
        self._update_preview()

    def _update_preview(self):
        """Szybka ścieżka: przerysuj overlay na skeszowanej klatce (zero FFmpeg).

        Wywoływana przy każdej zmianie stylu, trybu, sesji. Jeśli klatka nie jest
        skeszowana (np. pierwsze uruchomienie), poprosi o jej wyciągnięcie w tle.
        """
        if not self.video_path:
            return
        if self._cached_frame is None:
            self._request_frame()  # brak cache → zainicjuj ekstrakcję
            return
        try:
            session = self.session or self._safe_session()
            if session is None or not session.shots:
                return
            style = self.current_style()
            mode = self._anchor_mode()
            frame = self._cached_frame.copy()
            if mode == AnchorMode.START_SIGNAL:
                panel = overlay.render_start_banner(style, frame.size)
                x = (frame.size[0] - panel.size[0]) // 2
                y = (frame.size[1] - panel.size[1]) // 2
            else:
                panel = overlay.render_shot_panel(session, 0, style, frame.size)
                x, y = overlay.panel_origin(panel.size, frame.size, style)
            frame.alpha_composite(panel, (x, y))
            self._show_image(frame)
        except Exception:  # noqa: BLE001
            pass

    def _safe_session(self):
        try:
            return self._build_session()
        except Exception:  # noqa: BLE001
            return None

    def _show_image(self, pil_img):
        qim = ImageQt(pil_img.convert("RGBA"))
        pix = QPixmap.fromImage(QImage(qim)).scaled(
            self.preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview_label.setPixmap(pix)

    def _start_render(self):
        if not self.video_path:
            QMessageBox.warning(self, "Brak wideo", "Wybierz plik wideo."); return
        if not self.out_edit.text():
            QMessageBox.warning(self, "Brak wyjścia", "Podaj plik wyjściowy."); return
        try:
            session = self._build_session()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Błąd danych", str(exc)); return

        mode = self._anchor_mode()
        t0 = audio_sync.resolve_t0(self.t0_spin.value(), mode, session.shots[0].czas)
        ts = self.trim_start_spin.value()
        te = self.trim_end_spin.value()

        self.render_btn.setEnabled(False)
        self.worker = RenderWorker(dict(
            video_path=self.video_path, session=session, t0=t0,
            style=self.current_style(), mode=mode, out_path=self.out_edit.text(),
            trim_start=ts if ts > 0 else None,
            trim_end=te if te > 0 else None,
            encoder="auto" if self.gpu_chk.isChecked() else "cpu",
        ))
        self._used_encoder = None
        self._render_warn = None
        self.worker.progress.connect(lambda p: self.progress.setValue(int(p * 100)))
        self.worker.encoder_used.connect(self._on_encoder_used)
        self.worker.warn.connect(self._on_warn)
        self.worker.finished_ok.connect(self._on_done)
        self.worker.failed.connect(self._on_fail)
        self.worker.start()

    def _on_encoder_used(self, enc: str):
        self._used_encoder = enc

    def _on_warn(self, msg: str):
        self._render_warn = msg

    def _show_nvenc_diag(self):
        """Pokazuje pełną diagnostykę NVENC: status, użyta binarka, błąd FFmpeg."""
        works = render.nvenc_works()
        lines = [
            f"NVENC działa: {'TAK' if works else 'NIE'}",
            f"h264_nvenc na liście FFmpeg: {'TAK' if ffmpeg.has_nvenc() else 'NIE'}",
            f"Używana binarka FFmpeg:\n{ffmpeg.ffmpeg_exe()}",
        ]
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information if works else QMessageBox.Warning)
        box.setWindowTitle("Diagnostyka NVENC")
        if works:
            args = render.working_nvenc_args()
            lines.append(f"Działające argumenty:\n{' '.join(args)}")
            box.setText("\n\n".join(lines))
        else:
            lines.append("Najczęstsza przyczyna na laptopie: ffmpeg startuje na iGPU.\n"
                         "Wymuś NVIDIA dla ffmpeg.exe i PiroOverlay.exe w:\n"
                         "Ustawienia → System → Ekran → Grafika (Wysoka wydajność),\n"
                         "albo NVIDIA Control Panel → Ustawienia 3D → Ustawienia programu.\n"
                         "Sprawdź też sterownik: nvidia-smi.")
            box.setText("\n\n".join(lines))
            box.setDetailedText(render.nvenc_diagnostic(full=True) or "(brak szczegółów)")
        box.exec()

    def _refresh_nvenc_status(self):
        try:
            ok = render.nvenc_works()  # realny test kodowania (próbuje kilka wariantów)
        except Exception:  # noqa: BLE001
            ok = False
        self.nvenc_label.setToolTip("")
        if ok:
            self.nvenc_label.setText("NVENC: działa ✓ (render na GPU)")
            self.nvenc_label.setStyleSheet("color:#3ad17a;")
        elif ffmpeg.has_nvenc():
            self.nvenc_label.setText("NVENC: wykryty, ale test nie przeszedł — render na CPU (najedź, by zobaczyć powód)")
            self.nvenc_label.setStyleSheet("color:#e0a030;")
            self.nvenc_label.setToolTip(render.nvenc_diagnostic() or "")
        else:
            self.nvenc_label.setText("NVENC: niedostępny — render na CPU (zainstaluj pełny FFmpeg)")
            self.nvenc_label.setStyleSheet("color:#e0a030;")

    def _on_done(self, path: str):
        self.render_btn.setEnabled(True)
        self.last_output = path
        self.open_btn.setEnabled(True)
        enc = {"h264_nvenc": "GPU (NVENC)", "libx264": "CPU (x264)"}.get(self._used_encoder, "")
        msg = f"Zapisano:\n{path}"
        if enc:
            msg += f"\n\nEnkoder: {enc}"
        if self._render_warn:
            msg += f"\n\n⚠ {self._render_warn}"
        QMessageBox.information(self, "Gotowe", msg)

    def _on_fail(self, msg: str):
        self.render_btn.setEnabled(True)
        QMessageBox.critical(self, "Błąd renderowania", msg)

    def _open_output_folder(self):
        """Otwiera folder z wynikiem; na Windows zaznacza plik w eksploratorze."""
        if not self.last_output:
            return
        path = Path(self.last_output)
        if sys.platform == "win32" and path.exists():
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


# ----------------------------- helpery -----------------------------
def _wrap(layout):
    w = QWidget(); w.setLayout(layout); return w


def _dspin(lo, hi, step, suffix="", value=None):
    s = QDoubleSpinBox(); s.setRange(lo, hi); s.setSingleStep(step)
    if suffix:
        s.setSuffix(suffix)
    if value is not None:
        s.setValue(value)
    return s


def _ispin(lo, hi, value):
    s = QSpinBox(); s.setRange(lo, hi); s.setValue(value); return s


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("PiroOverlay")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(QIcon(resources.icon_path()))
    win = MainWindow()
    win.resize(1180, 760)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
