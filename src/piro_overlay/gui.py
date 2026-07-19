"""Aplikacja desktop (PySide6) dla Piro Overlay.

Warstwa UI — całość logiki domenowej pochodzi z modułów `parser`, `api`, `audio_sync`,
`overlay`, `render`. Operacje ciężkie (render, analiza audio) biegną w wątkach roboczych
(QThread), aby nie blokować interfejsu.

Funkcje UI: drag&drop pliku, widok ścieżki audio (klik = kotwica T0, uchwyty = przycięcie),
przycinanie fragmentu z eksportem tylko jego, podgląd na żywo w obniżonej jakości,
konfiguracja wyglądu nakładki, domyślny plik wyjściowy z sufiksem _PiRoOverlay.
"""

from __future__ import annotations

import faulthandler
import math
import re
import subprocess
import sys
import tempfile
import traceback
import unicodedata
import uuid
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from pathlib import Path

import urllib.request
import json

from PySide6.QtCore import QEvent, QObject, QRect, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QButtonGroup, QColorDialog, QComboBox, QCheckBox,
    QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton, QRadioButton,
    QScrollArea, QSizePolicy, QSpinBox, QSplitter, QPlainTextEdit, QVBoxLayout, QWidget,
)

from PIL import Image
from PIL.ImageQt import ImageQt

from . import __version__, api, audio_sync, config, ffmpeg, overlay, render, resources
from .models import ANCHOR_POSITIONS, AnchorMode, Lang, OverlayStyle, Session
from .parser import parse_timeline

PREVIEW_HEIGHT = 360  # obniżona jakość podglądu — szybciej i lżej dla dużych plików
_HANDLE_PX = 8        # tolerancja trafienia uchwytu przycięcia (px)
_AXIS_H = 22          # wysokość paska osi czasu (px)

_FORMAT_EXT = {"mp4": ".mp4", "webm": ".webm", "gif": ".gif"}  # format → rozszerzenie
_SESSION_ID_MAX = 10_000_000   # górny zakres ID sesji API (główne okno i wsad)
_DEFAULT_OFFSET_PX = 32        # domyślny offset panelu/zegara — musi zgadzać się
                               # z pominięciami w _build_cli_command (krótsza komenda)
_LEAD_IN_S = 5.0               # sekundy przed T0 przy auto-przycięciu
_TRIM_TAIL_S = 5.0             # margines po ostatnim strzale przy auto-przycięciu
_IMPORT_TAIL_S = 75.0          # okno po T0 przy detekcji po imporcie (brak osi czasu)
_THREAD_JOIN_MS = 3000         # limit oczekiwania na wątki robocze przy zamykaniu
_FRAME_DEBOUNCE_MS = 250       # debounce ekstrakcji klatki po zmianie kotwicy
_SCRUBBER_DEBOUNCE_MS = 200    # debounce podglądu Ctrl+klik na waveformie
_BUSY_RETRY_MS = 150           # ponowna próba, gdy worker klatki jeszcze pracuje
_STYLE_AUTOSAVE_MS = 1000      # debounce autozapisu stylu na dysk

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
    cancelled = Signal()
    encoder_used = Signal(str)
    warn = Signal(str)

    def __init__(self, kwargs: dict):
        super().__init__()
        self._kwargs = kwargs
        self._cancelled = False
        self._proc = None   # uchwyt aktywnego procesu FFmpeg (do natychmiastowego ubicia)

    def cancel(self) -> None:
        """Żądanie przerwania: ustawia flagę ORAZ od razu UBIJA proces FFmpeg.

        Samo czekanie na „najbliższą linię postępu" zawodziło, gdy FFmpeg długo nic
        nie wypisywał (ciężki filtergraph) — „Zatrzymaj" wisiało. Zabicie procesu
        odblokowuje pętlę czytającą stderr (EOF) → render kończy się jako anulowany."""
        self._cancelled = True
        p = self._proc
        if p is not None:
            try:
                p.kill()
            except Exception:  # noqa: BLE001
                pass

    def _is_cancelled(self) -> bool:
        return self._cancelled

    def _on_process(self, proc) -> None:
        self._proc = proc
        # Gdy „Zatrzymaj" kliknięto ZANIM proces wystartował — ubij go natychmiast.
        if self._cancelled and proc is not None:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass

    def run(self):
        try:
            kw = dict(self._kwargs)
            no_overlay = kw.pop("no_overlay", False)
            fmt = kw.pop("output_format", "mp4")
            callbacks = dict(progress_cb=self.progress.emit,
                             on_encoder=self.encoder_used.emit,
                             on_warn=self.warn.emit,
                             cancel_check=self._is_cancelled,
                             on_process=self._on_process)
            if no_overlay:
                render.trim_video(
                    video_path=kw["video_path"], out_path=kw["out_path"],
                    trim_start=kw.get("trim_start"), trim_end=kw.get("trim_end"),
                    encoder=kw.get("encoder", "auto"), **callbacks)
            elif fmt == "gif":
                render.render_gif(
                    video_path=kw["video_path"], session=kw["session"],
                    t0=kw["t0"], style=kw["style"], mode=kw["mode"],
                    out_path=kw["out_path"],
                    trim_start=kw.get("trim_start"), trim_end=kw.get("trim_end"),
                    progress_cb=self.progress.emit, cancel_check=self._is_cancelled,
                    on_process=self._on_process)
            elif fmt == "webm":
                render.render_webm(
                    video_path=kw["video_path"], session=kw["session"],
                    t0=kw["t0"], style=kw["style"], mode=kw["mode"],
                    out_path=kw["out_path"],
                    trim_start=kw.get("trim_start"), trim_end=kw.get("trim_end"),
                    progress_cb=self.progress.emit, cancel_check=self._is_cancelled,
                    on_process=self._on_process)
            else:
                render.render_video(**callbacks, **kw)
            self.finished_ok.emit(str(self._kwargs["out_path"]))
        except render.RenderCancelled:
            # Usuń niedokończony plik wyjściowy (jest uszkodzony).
            try:
                Path(str(self._kwargs.get("out_path", ""))).unlink(missing_ok=True)
            except OSError:
                pass
            self.cancelled.emit()
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class FrameExtractWorker(QThread):
    """Wyciąga jedną klatkę z wideo w tle — FFmpeg nie blokuje UI."""
    done = Signal(object, float)   # (PIL.Image, anchor_t)
    failed = Signal(str)

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
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class WaveformWorker(QThread):
    """Liczy obwiednię audio + onsety poza wątkiem UI."""
    done = Signal(list, float, list)
    failed = Signal(str)

    def __init__(self, video_path: str):
        super().__init__()
        self.video_path = video_path

    def run(self):
        try:
            env, dur, onsets = audio_sync.analyze_audio(self.video_path)
            self.done.emit(env, dur, onsets)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class StartDetectWorker(QThread):
    """Wykrywa bzyczek shot-timera (T0) w tle — FFT nie blokuje UI.

    `gen` to token pokolenia — handler odrzuca wyniki starszych detekcji, żeby
    wolniejsza, wcześniejsza detekcja nie nadpisała świeższej.
    """
    done = Signal(int, object)   # (gen, detected_t0 lub None)

    def __init__(self, video_path: str, gen: int,
                 win_start: float | None = None, win_end: float | None = None):
        super().__init__()
        self.video_path = video_path
        self.gen = gen
        # UWAGA: NIE nazywać tych pól `start`/`end` — przesłaniają QThread.start()
        # (worker.start() leciało wtedy jako None() → TypeError, detekcja T0 cicho padała).
        self.win_start = win_start
        self.win_end = win_end

    def run(self):
        try:
            t0 = audio_sync.detect_dji_start(self.video_path, start=self.win_start, end=self.win_end)
        except Exception:  # noqa: BLE001
            t0 = None
        self.done.emit(self.gen, t0)


# ----------------------------- kolejka renderów -----------------------------
class JobStatus(Enum):
    PENDING = auto()
    RUNNING = auto()
    DONE    = auto()
    FAILED  = auto()


@dataclass
class RenderJob:
    id:     str
    label:  str
    kwargs: dict
    status: JobStatus = field(default=JobStatus.PENDING, compare=False)


def _job_to_dict(job: "RenderJob") -> dict:
    """Serializuje zadanie renderu do JSON-owalnego słownika (zapis kolejki)."""
    kw = job.kwargs
    sess = kw.get("session")
    style = kw.get("style")
    mode = kw.get("mode")
    return {
        "id": job.id,
        "label": job.label,
        "status": job.status.name,
        "kwargs": {
            "video_path": str(kw.get("video_path", "")),
            "session": sess.to_dict() if sess is not None else None,
            "t0": kw.get("t0"),
            "style": style.to_dict() if style is not None else None,
            "mode": mode.value if isinstance(mode, AnchorMode) else mode,
            "out_path": str(kw.get("out_path", "")),
            "trim_start": kw.get("trim_start"),
            "trim_end": kw.get("trim_end"),
            "encoder": kw.get("encoder", "auto"),
            "no_overlay": kw.get("no_overlay", False),
            "output_format": kw.get("output_format", "mp4"),
        },
    }


def _job_from_dict(d: dict) -> "RenderJob":
    """Odtwarza zadanie renderu ze słownika; status zerowany do PENDING (do ponowienia)."""
    k = d.get("kwargs", {})
    sess = k.get("session")
    style = k.get("style")
    kwargs = dict(
        video_path=k.get("video_path", ""),
        session=Session.from_dict(sess) if sess else None,
        t0=k.get("t0", 0.0) or 0.0,
        style=OverlayStyle.from_dict(style) if style else None,
        mode=AnchorMode(k.get("mode", AnchorMode.START_SIGNAL.value)),
        out_path=k.get("out_path", ""),
        trim_start=k.get("trim_start"),
        trim_end=k.get("trim_end"),
        encoder=k.get("encoder", "auto"),
        no_overlay=k.get("no_overlay", False),
        output_format=k.get("output_format", "mp4"),
    )
    return RenderJob(id=d.get("id") or uuid.uuid4().hex,
                     label=d.get("label", ""), kwargs=kwargs)


class RenderQueueRunner(QObject):
    job_progress        = Signal(str, float)      # (job_id, 0.0–1.0)
    job_status_changed  = Signal(str, object)     # (job_id, JobStatus)
    queue_finished      = Signal()
    queue_stopped       = Signal()                # zatrzymano (pauza, nie koniec)

    def __init__(self, get_busy, set_busy, parent=None, parallel: int = 1):
        super().__init__(parent)
        self._jobs: list[RenderJob] = []
        self._active: dict[str, RenderWorker] = {}   # job_id → żywy worker
        self._get_busy = get_busy
        self._set_busy = set_busy
        self._running = False
        self._stopping = False   # żądanie zatrzymania kolejki (po bieżących)
        self._parallel = max(1, parallel)

    def set_parallel(self, n: int) -> None:
        """Limit równoległych renderów. Zmiana w trakcie działa od następnego
        wolnego slotu (biegnących zadań nie przerywa ani nie dokłada od razu)."""
        self._parallel = max(1, n)

    def active_workers(self) -> list[RenderWorker]:
        return list(self._active.values())

    def add_job(self, job: RenderJob) -> None:
        self._jobs.append(job)
        if self._running:
            self._fill_slots()   # wolny slot? — zadanie startuje od razu

    def remove_job(self, job_id: str) -> bool:
        for i, j in enumerate(self._jobs):
            if j.id == job_id and j.status == JobStatus.PENDING:
                del self._jobs[i]
                return True
        return False

    def jobs(self) -> list[RenderJob]:
        return list(self._jobs)

    def clear_finished(self) -> None:
        self._jobs = [j for j in self._jobs
                      if j.status not in (JobStatus.DONE, JobStatus.FAILED)]

    def retry_failed(self) -> list[str]:
        """Przywraca nieudane zadania do PENDING (do ponowienia). Zwraca ich id."""
        ids = []
        for j in self._jobs:
            if j.status == JobStatus.FAILED:
                j.status = JobStatus.PENDING
                ids.append(j.id)
        return ids

    def start_queue(self) -> bool:
        if self._running or self._get_busy():
            return False
        self._running = True
        self._stopping = False
        self._fill_slots()
        return True

    def stop(self) -> None:
        """Zatrzymuje kolejkę: przerywa WSZYSTKIE biegnące zadania (wrócą do
        PENDING) i NIE uruchamia kolejnych. `start_queue` wznawia."""
        if not self._running:
            return
        self._stopping = True
        if self._active:
            for w in list(self._active.values()):
                w.cancel()
            # finalizacja w _fill_slots, gdy ostatni worker zgłosi cancelled
        else:
            # Brak aktywnych workerów (np. między zadaniami) — zatrzymaj OD RAZU,
            # inaczej `_running` zostałby True i „Start kolejki" by nie wznowił.
            self._stopping = False
            self._running = False
            self._set_busy(False)
            self.queue_stopped.emit()

    def _fill_slots(self) -> None:
        """Dosypuje zadania do wolnych slotów (do limitu `_parallel`), a gdy nic
        już nie biegnie — kończy kolejkę (albo pauzuje, jeśli zatrzymywano)."""
        if not self._stopping:
            pending = [j for j in self._jobs if j.status == JobStatus.PENDING]
            for job in pending[:max(0, self._parallel - len(self._active))]:
                self._start_job(job)
        if self._active:
            return
        was_stopping = self._stopping
        self._stopping = False
        self._running = False
        self._set_busy(False)
        (self.queue_stopped if was_stopping else self.queue_finished).emit()

    def _start_job(self, job: RenderJob) -> None:
        job.status = JobStatus.RUNNING
        self._set_busy(True)
        self.job_status_changed.emit(job.id, JobStatus.RUNNING)
        w = RenderWorker(job.kwargs)
        self._active[job.id] = w
        w.progress.connect(lambda p, jid=job.id: self.job_progress.emit(jid, p))
        w.finished_ok.connect(lambda _, jid=job.id: self._on_job_done(jid))
        w.failed.connect(lambda msg, jid=job.id: self._on_job_failed(jid, msg))
        w.cancelled.connect(lambda jid=job.id: self._on_job_cancelled(jid))
        w.start()

    def _finish_worker(self, job_id: str) -> None:
        """Zamyka worker zadania BEZPIECZNIE: czeka aż wątek REALNIE się zakończy,
        dopiero potem zwalnia referencję.

        KRYTYCZNE (patrz CLAUDE.md): `finished_ok`/`failed`/`cancelled` lecą z
        OSTATNIEJ linii `run()` — wątek QThread jeszcze się NIE zakończył. Gdyby
        tu od razu zwolnić referencję, GC zniszczyłby QThread „w trakcie pracy"
        → twardy crash (QThread: Destroyed while thread is still running).
        `wait()` wraca natychmiast (run() już oddaje sterowanie)."""
        w = self._active.pop(job_id, None)
        if w is not None:
            w.wait()

    def _on_job_done(self, job_id: str) -> None:
        self._mark(job_id, JobStatus.DONE)
        self._finish_worker(job_id)
        self._fill_slots()

    def _on_job_failed(self, job_id: str, _msg: str) -> None:
        self._mark(job_id, JobStatus.FAILED)
        self._finish_worker(job_id)
        self._fill_slots()

    def _on_job_cancelled(self, job_id: str) -> None:
        # Przerwane zadanie wraca do PENDING (do ponowienia); kolejka pauzuje.
        self._mark(job_id, JobStatus.PENDING)
        self._finish_worker(job_id)
        self._fill_slots()   # zobaczy _stopping → po ostatnim emituje queue_stopped

    def _mark(self, job_id: str, status: JobStatus) -> None:
        for j in self._jobs:
            if j.id == job_id:
                j.status = status
                self.job_status_changed.emit(job_id, status)
                return


class JobRowWidget(QWidget):
    remove_requested = Signal(str)

    _STATUS_COLORS = {
        JobStatus.PENDING: "#6688aa",
        JobStatus.RUNNING: "#f0c040",
        JobStatus.DONE:    "#44cc88",
        JobStatus.FAILED:  "#e05555",
    }

    def __init__(self, job: RenderJob, parent=None):
        super().__init__(parent)
        self._job_id = job.id
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)

        self._status_icon = QLabel()
        self._status_icon.setFixedSize(14, 14)
        lay.addWidget(self._status_icon)

        self._label = QLabel(job.label)
        self._label.setMinimumWidth(200)
        lay.addWidget(self._label, 1)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(True)   # pokazuj liczbowy % postępu
        self._progress.setFormat("%p%")
        self._progress.setFixedWidth(120)
        lay.addWidget(self._progress)

        self._del_btn = QPushButton("Usuń")
        self._del_btn.setFixedWidth(50)
        self._del_btn.clicked.connect(lambda: self.remove_requested.emit(self._job_id))
        lay.addWidget(self._del_btn)

        self._apply_status(job.status)

    def update_progress(self, p: float) -> None:
        self._progress.setValue(int(p * 100))

    def update_status(self, status: JobStatus) -> None:
        self._apply_status(status)

    def _apply_status(self, status: JobStatus) -> None:
        color = self._STATUS_COLORS.get(status, "#888888")
        self._status_icon.setStyleSheet(
            f"background:{color}; border-radius:7px;"
        )
        self._del_btn.setVisible(status == JobStatus.PENDING)
        if status == JobStatus.FAILED:
            self._progress.setFormat("błąd")
            self._progress.setStyleSheet("QProgressBar::chunk { background: #e05555; }")
            return
        # Powrót z FAILED (retry przez „Start kolejki") musi zdjąć czerwony pasek.
        self._progress.setFormat("%p%")
        self._progress.setStyleSheet("")
        if status == JobStatus.DONE:
            self._progress.setValue(100)


class RenderQueueWindow(QWidget):
    def __init__(self, runner: RenderQueueRunner, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("Kolejka renderów")
        self.setMinimumWidth(560)
        self._runner = runner
        self._rows: dict[str, JobRowWidget] = {}
        self._progress: dict[str, float] = {}   # job_id → ostatni postęp (0–1)

        root = QVBoxLayout(self)

        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setSpacing(2)
        self._list_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._list_widget)
        scroll.setMinimumHeight(200)
        root.addWidget(scroll, 1)

        self._status_label = QLabel("Gotowy")
        root.addWidget(self._status_label)

        btn_row = QHBoxLayout()
        self._start_btn = QPushButton("Start kolejki")
        self._start_btn.setToolTip("Renderuje oczekujące zadania (tyle naraz, ile "
                                   "ustawiono w „Równoległe”; nieudane ponawia automatycznie)")
        self._start_btn.clicked.connect(self._on_start)
        self._stop_btn = QPushButton("Zatrzymaj")
        self._stop_btn.setToolTip("Przerywa biegnące rendery i pauzuje kolejkę "
                                  "(zadania zostają jako oczekujące — „Start kolejki” wznawia)")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop)
        self._clear_btn = QPushButton("Wyczyść zakończone")
        self._clear_btn.setToolTip("Usuwa z listy zadania ukończone i nieudane")
        self._clear_btn.clicked.connect(self._on_clear_finished)
        self._save_btn = QPushButton("Zapisz kolejkę")
        self._save_btn.setToolTip("Zapisz niewykonane zadania w AppData (odzysk po awarii)")
        self._save_btn.clicked.connect(self._on_save_queue)
        self._load_btn = QPushButton("Wczytaj kolejkę")
        self._load_btn.setToolTip("Wczytaj zapisaną kolejkę z AppData")
        self._load_btn.clicked.connect(self._on_load_queue)
        btn_row.addWidget(self._start_btn)
        btn_row.addWidget(self._stop_btn)
        btn_row.addWidget(self._clear_btn)
        btn_row.addWidget(self._save_btn)
        btn_row.addWidget(self._load_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(QLabel("Równoległe:"))
        self._parallel_spin = QSpinBox()
        self._parallel_spin.setRange(1, config._QUEUE_PARALLEL_MAX)
        self._parallel_spin.setValue(config.load_queue_parallel())
        self._parallel_spin.setToolTip(
            "Ile plików renderować jednocześnie. Przy NVENC pojedynczy render\n"
            "wykorzystuje GPU w ~50% (kompozycja nakładki idzie na CPU) — dwa\n"
            "równoległe niemal podwajają przepustowość partii. Zmniejsz do 1,\n"
            "gdy laptop się przegrzewa albo render idzie na CPU (x264).\n"
            "Zmiana w trakcie działa od następnego wolnego slotu.")
        self._parallel_spin.valueChanged.connect(self._on_parallel_changed)
        runner.set_parallel(self._parallel_spin.value())
        btn_row.addWidget(self._parallel_spin)
        root.addLayout(btn_row)

        runner.job_progress.connect(self._on_job_progress)
        runner.job_status_changed.connect(self._on_job_status_changed)
        runner.queue_finished.connect(self._on_queue_finished)
        runner.queue_stopped.connect(self._on_queue_stopped)

    def add_job(self, job: RenderJob) -> None:
        row = JobRowWidget(job)
        row.remove_requested.connect(self._on_remove)
        self._rows[job.id] = row
        self._list_layout.insertWidget(self._list_layout.count() - 1, row)
        self._runner.add_job(job)
        self._refresh_start_btn()
        self._autosave_queue()

    def closeEvent(self, event):
        if self._runner._running:
            self.hide()
            event.ignore()
        else:
            event.accept()

    def _on_start(self) -> None:
        # „Start" PONAWIA też zadania nieudane (FAILED → PENDING) — inaczej po awarii
        # /błędzie kolejka miałaby same FAILED i Start nie miałby co uruchomić.
        retried = self._runner.retry_failed()
        for jid in retried:
            if row := self._rows.get(jid):
                row.update_status(JobStatus.PENDING)
        started = self._runner.start_queue()
        if not started:
            self._status_label.setText("Renderowanie już trwa — poczekaj na koniec.")
        else:
            self._status_label.setText("Renderowanie kolejki…")
        self._refresh_start_btn()

    def _on_stop(self) -> None:
        self._runner.stop()
        self._stop_btn.setEnabled(False)
        self._status_label.setText("Zatrzymywanie kolejki (przerywam biegnące rendery)…")

    def _on_clear_finished(self) -> None:
        for job_id, row in list(self._rows.items()):
            job = next((j for j in self._runner.jobs() if j.id == job_id), None)
            if job and job.status in (JobStatus.DONE, JobStatus.FAILED):
                self._list_layout.removeWidget(row)
                row.deleteLater()
                del self._rows[job_id]
        self._runner.clear_finished()

    def _on_remove(self, job_id: str) -> None:
        if self._runner.remove_job(job_id):
            row = self._rows.pop(job_id, None)
            if row:
                self._list_layout.removeWidget(row)
                row.deleteLater()

    def _on_parallel_changed(self, n: int) -> None:
        self._runner.set_parallel(n)
        config.save_queue_parallel(n)

    def _on_job_progress(self, job_id: str, p: float) -> None:
        if row := self._rows.get(job_id):
            row.update_progress(p)
        self._progress[job_id] = p
        self._update_overall()

    def _update_overall(self) -> None:
        """Pokazuje łączny postęp kolejki w pasku stanu (suma po wszystkich
        biegnących zadaniach — przy współbieżności >1 biegnie kilka naraz)."""
        jobs = self._runner.jobs()
        total = len(jobs)
        if not total:
            return
        done = sum(1 for j in jobs if j.status == JobStatus.DONE)
        running = [j for j in jobs if j.status == JobStatus.RUNNING]
        overall = (done + sum(self._progress.get(j.id, 0.0) for j in running)) / total
        if len(running) == 1:
            name = Path(str(running[0].kwargs.get("video_path", ""))).name
            cur = self._progress.get(running[0].id, 0.0)
            detail = f"{name} · bieżący {cur * 100:.0f}%"
        else:
            detail = f"{len(running)} plików równolegle"
        self._status_label.setText(
            f"Ukończone {done}/{total} · {detail} · łącznie {overall * 100:.0f}%")

    def _on_job_status_changed(self, job_id: str, status) -> None:
        if row := self._rows.get(job_id):
            row.update_status(status)
        if status != JobStatus.RUNNING:
            self._progress.pop(job_id, None)   # świeży % po wznowieniu/ponowieniu
        self._refresh_start_btn()
        self._autosave_queue()   # DONE wypada z zapisu, FAILED zostaje (do ponowienia)

    def _on_queue_finished(self) -> None:
        self._status_label.setText("Kolejka zakończona.")
        self._refresh_start_btn()
        QMessageBox.information(self, "Kolejka renderów",
                                "Wszystkie zadania zostały ukończone.")

    def _on_queue_stopped(self) -> None:
        self._status_label.setText(
            "Kolejka zatrzymana. „Start kolejki” wznawia od przerwanego pliku.")
        self._refresh_start_btn()

    def _refresh_start_btn(self) -> None:
        running = self._runner._running
        # Start aktywny, gdy jest cokolwiek do zrobienia: oczekujące LUB nieudane
        # (te drugie „Start" ponawia — patrz `_on_start`/`retry_failed`).
        has_todo = any(j.status in (JobStatus.PENDING, JobStatus.FAILED)
                       for j in self._runner.jobs())
        self._start_btn.setEnabled(has_todo and not running)
        self._stop_btn.setEnabled(running)

    # --- zapis/odczyt kolejki (AppData) ---
    def _queue_payload(self) -> dict:
        """Stan kolejki bez zadań zakończonych sukcesem (DONE) — tylko do (po)wykonania."""
        jobs = [_job_to_dict(j) for j in self._runner.jobs()
                if j.status != JobStatus.DONE]
        return {"version": 1, "jobs": jobs}

    def _autosave_queue(self) -> None:
        """Cichy zapis bieżącego stanu — plik w AppData jest zawsze aktualny
        (po awarii „Wczytaj kolejkę" odtworzy niewykonane zadania)."""
        config.save_queue(self._queue_payload())

    def _on_save_queue(self) -> None:
        payload = self._queue_payload()
        config.save_queue(payload)
        n = len(payload["jobs"])
        self._status_label.setText(
            f"Zapisano kolejkę ({n} zadań) → {config.queue_path()}")

    def _on_load_queue(self) -> None:
        data = config.load_queue()
        if not data or not data.get("jobs"):
            QMessageBox.information(self, "Wczytaj kolejkę",
                                    "Brak zapisanej kolejki w AppData.")
            return
        existing = {j.id for j in self._runner.jobs()}
        added = 0
        for jd in data["jobs"]:
            try:
                job = _job_from_dict(jd)
            except Exception:  # noqa: BLE001
                continue
            if job.id in existing:
                continue
            job.status = JobStatus.PENDING   # wczytane = do ponowienia
            self.add_job(job)
            added += 1
        self._status_label.setText(f"Wczytano {added} zadań z zapisanej kolejki.")


# ----------------------------- przetwarzanie wsadowe -----------------------------
class BatchPrepWorker(QThread):
    """Przygotowuje JEDEN plik wsadowy w tle (sieć + FFT nie blokują UI):
    pobiera sesję z API po ID, wykrywa bzyczek (T0) i liczy okno auto-przycięcia.

    Wynik (`done`) zawiera komplet danych potrzebnych do zbudowania RenderJob.
    Błąd (`failed`) — czytelny komunikat dla wiersza. (Patrz pułapki QThread w
    CLAUDE.md: pola NIE nazwane `start`/`end`; worker trzymany do `finished`.)
    """
    done   = Signal(str, object)   # (row_id, dict: session/t0/trim_start/trim_end)
    failed = Signal(str, str)      # (row_id, komunikat)

    def __init__(self, row_id: str, video_path: str, lrf_path: str | None,
                 session_id: int):
        super().__init__()
        self.row_id = row_id
        self.video_path = video_path
        self.lrf_path = lrf_path
        self.session_id = session_id

    def run(self):
        try:
            session = api.fetch_session(self.session_id)
            if not session.shots:
                raise ValueError("API nie zwróciło strzałów dla tego ID.")
            src = self.lrf_path or self.video_path
            t0 = audio_sync.detect_dji_start(src)
            if t0 is None:
                raise ValueError("Nie wykryto sygnału startu (bzyczka).")
            try:
                dur = ffmpeg.probe(self.video_path).duration
            except Exception:  # noqa: BLE001
                dur = None
            start, end = render.auto_trim_window(
                t0, session.shots[-1].czas,
                tail=_TRIM_TAIL_S, lead_in=_LEAD_IN_S, duration=dur)
            self.done.emit(self.row_id, {
                "session": session, "t0": t0,
                "trim_start": start, "trim_end": end,
            })
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(self.row_id, str(exc))


class BatchIdDetectWorker(QThread):
    """Dekoduje ID sesji z sygnału tonowego JEDNEGO pliku w tle (FFT nie blokuje UI).

    Analizuje zawsze oryginalny plik wideo — NIE proxy LRF (sygnał ID gra pod
    koniec nagrania, poza oknem, na którym LRF jest używane do detekcji T0 —
    patrz `MainWindow._detect_id_tone`). Brak sygnału to nie błąd: `done` niesie
    wtedy None i wiersz wraca do „podaj ID". (Pułapki QThread jak w
    `BatchPrepWorker`: worker trzymany do `finished`.)
    """
    done = Signal(str, object)   # (row_id, int | None)

    def __init__(self, row_id: str, video_path: str):
        super().__init__()
        self.row_id = row_id
        self.video_path = video_path

    def run(self):
        try:
            detected = audio_sync.decode_id_tone(self.video_path)
        except Exception:  # noqa: BLE001
            detected = None
        self.done.emit(self.row_id, detected)


class BatchRowStatus(Enum):
    NEEDS_ID  = auto()   # brak/zerowe ID
    DETECTING = auto()   # trwa wykrywanie ID z sygnału tonowego
    PENDING   = auto()   # gotowe do przygotowania
    PREPARING = auto()   # trwa fetch+detekcja
    READY     = auto()   # przygotowane (T0+przycięcie znane)
    FAILED    = auto()   # błąd przygotowania


# wiersz „zajęty" = żywy QThread w tle; nie wolno go usuwać ani edytować jego ID
_BATCH_BUSY = (BatchRowStatus.DETECTING, BatchRowStatus.PREPARING)


@dataclass
class BatchRow:
    id:         str
    video_path: str
    lrf_path:   str | None
    status:     BatchRowStatus = BatchRowStatus.NEEDS_ID
    session_id: int = 0
    prep:       dict | None = None     # wynik BatchPrepWorker
    error:      str = ""


class BatchRowWidget(QWidget):
    """Wiersz jednego pliku w oknie wsadowym: status, nazwa, ID, info, play, usuń."""
    remove_requested = Signal(str)
    play_requested   = Signal(str)
    id_changed       = Signal(str, int)

    _STATUS_COLORS = {
        BatchRowStatus.NEEDS_ID:  "#aa7733",
        BatchRowStatus.DETECTING: "#f0c040",
        BatchRowStatus.PENDING:   "#6688aa",
        BatchRowStatus.PREPARING: "#f0c040",
        BatchRowStatus.READY:     "#44cc88",
        BatchRowStatus.FAILED:    "#e05555",
    }

    def __init__(self, row: BatchRow, parent=None):
        super().__init__(parent)
        self._row_id = row.id
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)

        self._status_icon = QLabel()
        self._status_icon.setFixedSize(14, 14)
        lay.addWidget(self._status_icon)

        self._name = QLabel(Path(row.video_path).name)
        self._name.setMinimumWidth(180)
        self._name.setToolTip(row.video_path)
        lay.addWidget(self._name, 2)

        lay.addWidget(QLabel("ID:"))
        self._id_spin = QSpinBox()
        self._id_spin.setRange(0, _SESSION_ID_MAX)   # 0 = brak ID (wiersz nieprzygotowany)
        self._id_spin.setValue(row.session_id)
        self._id_spin.setFixedWidth(100)
        self._id_spin.valueChanged.connect(
            lambda v: self.id_changed.emit(self._row_id, v))
        lay.addWidget(self._id_spin)

        self._info = QLabel("")
        self._info.setMinimumWidth(190)
        self._info.setStyleSheet("color:#aaaaaa;")
        lay.addWidget(self._info, 2)

        self._play_btn = QPushButton("▶")
        self._play_btn.setFixedWidth(34)
        self._play_btn.setToolTip("Otwórz plik źródłowy w odtwarzaczu")
        self._play_btn.clicked.connect(lambda: self.play_requested.emit(self._row_id))
        lay.addWidget(self._play_btn)

        self._del_btn = QPushButton("Usuń")
        self._del_btn.setFixedWidth(50)
        self._del_btn.clicked.connect(lambda: self.remove_requested.emit(self._row_id))
        lay.addWidget(self._del_btn)

        self.update_row(row)

    def set_session_id(self, value: int) -> None:
        """Ustawia ID w spinboxie (wyemituje `id_changed` → aktualizacja wiersza)."""
        self._id_spin.setValue(value)

    def update_row(self, row: BatchRow) -> None:
        color = self._STATUS_COLORS.get(row.status, "#888888")
        self._status_icon.setStyleSheet(f"background:{color}; border-radius:7px;")
        busy = row.status in _BATCH_BUSY
        self._id_spin.setEnabled(not busy)
        self._del_btn.setEnabled(not busy)
        if row.status == BatchRowStatus.READY and row.prep:
            p = row.prep
            self._info.setText(
                f"T0={p['t0']:.2f}s · przyc. {p['trim_start']:.1f}–{p['trim_end']:.1f}s")
            self._info.setStyleSheet("color:#44cc88;")
            self._info.setToolTip("")
        elif row.status == BatchRowStatus.FAILED:
            self._info.setText(f"błąd: {row.error}")
            self._info.setStyleSheet("color:#e05555;")
            self._info.setToolTip(row.error)
        elif row.status == BatchRowStatus.PREPARING:
            self._info.setText("przygotowuję…")
            self._info.setStyleSheet("color:#f0c040;")
        elif row.status == BatchRowStatus.DETECTING:
            self._info.setText("wykrywam ID z audio…")
            self._info.setStyleSheet("color:#f0c040;")
        elif row.status == BatchRowStatus.NEEDS_ID:
            # po nieudanej detekcji `row.error` niesie „nie wykryto ID — podaj ręcznie"
            self._info.setText(row.error or "podaj ID")
            self._info.setStyleSheet("color:#aa7733;")
        else:
            self._info.setText("gotowe do przygotowania")
            self._info.setStyleSheet("color:#aaaaaa;")


_POLISH_MAP = str.maketrans({
    "ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "ø": "o", "Ø": "O",
})


def _sanitize_filename_part(text: str) -> str:
    """Zamienia tekst (np. nazwę uczestnika) na bezpieczny fragment nazwy pliku.

    Polskie/diakrytyczne znaki → ASCII (Jarosław → Jaroslaw), spacje → „_",
    odrzuca znaki niedozwolone w nazwach plików Windows/Unix. Zwraca "" gdy po
    sanityzacji nic nie zostaje.
    """
    if not text:
        return ""
    text = text.translate(_POLISH_MAP)
    # NFKD rozkłada litery z diakrytykami na bazę + znak łączący; usuwamy te drugie.
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.encode("ascii", "ignore").decode("ascii")
    # spacje/białe znaki → podkreślenie; usuń znaki niedozwolone i kropki brzegowe.
    text = re.sub(r"\s+", "_", text.strip())
    text = re.sub(r'[<>:"/\\|?*]+', "", text)
    text = re.sub(r"[^A-Za-z0-9._-]+", "", text)
    return text.strip("._-")


class BatchDialog(QWidget):
    """Okno przetwarzania wsadowego (tryb auto + ID).

    Dodajesz wiele plików, podajesz ID dla każdego, klikasz „Przygotuj" — aplikacja
    pobiera sesje z API, wykrywa T0 (bzyczek) i liczy auto-przycięcie. Wspólny styl
    nakładki, jeden katalog docelowy i sufiks nazwy. Gotowe pliki trafiają do
    istniejącej kolejki renderów (`RenderQueueRunner`), która renderuje je po kolei.
    """

    def __init__(self, runner: "RenderQueueRunner", queue_window: "RenderQueueWindow",
                 base_style: OverlayStyle, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("Przetwarzanie wsadowe (auto + ID)")
        self.setMinimumSize(720, 460)
        self._runner = runner
        self._queue_window = queue_window
        self._base_style = base_style
        self._rows: dict[str, BatchRow] = {}
        self._row_widgets: dict[str, BatchRowWidget] = {}
        self._workers: dict[str, QThread] = {}   # prep/detect, trzymane do finished

        root = QVBoxLayout(self)

        top = QHBoxLayout()
        add_btn = QPushButton("Dodaj pliki…")
        add_btn.setToolTip("Dodaje pliki wideo do listy wsadowej")
        add_btn.clicked.connect(self._add_files)
        export_btn = QPushButton("Eksport → schowek")
        export_btn.setToolTip("Kopiuje listę jako wiersze „<ścieżka>;<ID>”")
        export_btn.clicked.connect(self._export_clipboard)
        import_btn = QPushButton("Import ze schowka")
        import_btn.setToolTip("Wkleja listę „<ścieżka>;<ID>” ze schowka")
        import_btn.clicked.connect(self._import_clipboard)
        self._detect_id_btn = QPushButton("Wykryj ID z audio")
        self._detect_id_btn.setToolTip(
            "Dla plików bez ID szuka w nagraniu sygnału tonowego ID, który timer\n"
            "odtwarza po zapisie sesji w bazie (marker 5000 Hz + 4 cyfry + cyfra\n"
            "kontrolna, 5200–7000 Hz) i wpisuje wykryte ID do wiersza. Zawsze analizuje\n"
            "oryginalny plik (nie proxy LRF). Sprawdź wynik przed przygotowaniem.")
        self._detect_id_btn.clicked.connect(self._detect_ids)
        top.addWidget(add_btn)
        top.addWidget(export_btn)
        top.addWidget(import_btn)
        top.addWidget(self._detect_id_btn)
        top.addStretch(1)
        self._count_label = QLabel("Brak plików.")
        top.addWidget(self._count_label)
        root.addLayout(top)

        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setSpacing(2)
        self._list_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._list_widget)
        scroll.setMinimumHeight(180)
        root.addWidget(scroll, 1)

        # --- ustawienia wspólne dla całej partii ---
        opts = QGroupBox("Ustawienia wspólne")
        form = QFormLayout(opts)

        out_row = QHBoxLayout()
        self._out_dir_edit = QLineEdit()
        out_browse = QPushButton("Wybierz…")
        out_browse.clicked.connect(self._pick_out_dir)
        out_row.addWidget(self._out_dir_edit, 1)
        out_row.addWidget(out_browse)
        form.addRow("Katalog docelowy:", out_row)

        self._suffix_edit = QLineEdit("_PiRoOverlay")
        form.addRow("Sufiks nazwy:", self._suffix_edit)

        self._participant_chk = QCheckBox("Dodaj informacje o uczestniku")
        self._participant_chk.setToolTip(
            "Po sufiksie doda do nazwy pliku ID sesji oraz nazwę uczestnika "
            "(znaki diakrytyczne sanityzowane, np. Jarosław → Jaroslaw).")
        form.addRow("", self._participant_chk)

        self._format_combo = QComboBox()
        for label, val in (("MP4 (H.264)", "mp4"), ("WebM (VP9)", "webm"),
                           ("GIF (animowany)", "gif")):
            self._format_combo.addItem(label, val)
        self._format_combo.currentIndexChanged.connect(lambda *_: self._refresh())
        form.addRow("Format:", self._format_combo)

        toggles = QHBoxLayout()
        self._gpu_chk = QCheckBox("GPU (NVENC, jeśli dostępne)")
        self._gpu_chk.setChecked(True)
        self._overlay_chk = QCheckBox("Nakładka ze strzałami")
        self._overlay_chk.setChecked(True)
        self._overlay_chk.toggled.connect(self._on_overlay_toggled)
        self._clock_chk = QCheckBox("Płynący zegar od T0")
        self._clock_chk.setChecked(base_style.show_running_clock)
        toggles.addWidget(self._gpu_chk)
        toggles.addWidget(self._overlay_chk)
        toggles.addWidget(self._clock_chk)
        toggles.addStretch(1)
        form.addRow("Nakładki:", toggles)
        root.addWidget(opts)

        note = QLabel(
            "Tryb auto + ID: oś czasu z API (po ID), T0 = wykryty bzyczek, przycięcie "
            "5 s przed T0 → ostatni strzał + 5 s. Wygląd nakładki wspólny — kopiowany "
            "z głównego okna (zmień go tam przed otwarciem). Plansza START zawsze (auto). "
            "„Wykryj ID z audio” próbuje odczytać ID z sygnału tonowego timera dla "
            "plików bez ID.")
        note.setStyleSheet("color:#aaaaaa;")
        note.setWordWrap(True)
        root.addWidget(note)

        btns = QHBoxLayout()
        self._prep_btn = QPushButton("Przygotuj wszystkie")
        self._prep_btn.setToolTip("Dla plików z ID: pobiera sesję z API, wykrywa "
                                  "sygnał startu (T0) i liczy auto-przycięcie")
        self._prep_btn.clicked.connect(self._prepare_all)
        self._enqueue_btn = QPushButton("Wyślij gotowe do kolejki")
        self._enqueue_btn.setToolTip("Buduje zadania renderu z przygotowanych "
                                     "plików i dodaje je do kolejki renderów")
        self._enqueue_btn.clicked.connect(self._enqueue_ready)
        self._clear_btn = QPushButton("Wyczyść wszystko")
        self._clear_btn.setToolTip("Usuwa wszystkie pliki z listy wsadowej")
        self._clear_btn.clicked.connect(self._clear_all)
        close_btn = QPushButton("Zamknij")
        close_btn.clicked.connect(self.close)
        btns.addWidget(self._prep_btn)
        btns.addWidget(self._enqueue_btn)
        btns.addWidget(self._clear_btn)
        btns.addStretch(1)
        btns.addWidget(close_btn)
        root.addLayout(btns)

        self._refresh()

    # --- dodawanie / usuwanie plików ---
    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Wybierz pliki wideo", "",
            "Wideo (*.mp4 *.mov *.mkv *.avi);;Wszystkie pliki (*)")
        if not paths:
            return
        if not self._out_dir_edit.text() and paths:
            self._out_dir_edit.setText(str(Path(paths[0]).parent))
        for path in paths:
            self._add_row(path)
        self._refresh()

    def _add_row(self, path: str, session_id: int = 0) -> BatchRow | None:
        """Tworzy wiersz dla pliku (pomija duplikat ścieżki). Wspólne dla „Dodaj
        pliki…" i importu ze schowka."""
        if any(r.video_path == path for r in self._rows.values()):
            return None
        lrf = ffmpeg.find_lrf(path)
        status = (BatchRowStatus.PENDING if session_id > 0
                  else BatchRowStatus.NEEDS_ID)
        row = BatchRow(id=uuid.uuid4().hex, video_path=path,
                       lrf_path=str(lrf) if lrf else None,
                       session_id=session_id, status=status)
        self._rows[row.id] = row
        w = BatchRowWidget(row)
        w.remove_requested.connect(self._remove_row)
        w.play_requested.connect(self._play_row)
        w.id_changed.connect(self._on_id_changed)
        self._row_widgets[row.id] = w
        self._list_layout.insertWidget(self._list_layout.count() - 1, w)
        return row

    def _export_clipboard(self) -> None:
        """Kopiuje całą listę do schowka — po jednym pliku w wierszu „<ścieżka>;<ID>”."""
        if not self._rows:
            QMessageBox.information(self, "Eksport", "Brak plików do wyeksportowania.")
            return
        lines = [f"{r.video_path};{r.session_id}" for r in self._rows.values()]
        QApplication.clipboard().setText("\n".join(lines))
        self._count_label.setText(f"Skopiowano {len(lines)} pozycji do schowka.")

    def _import_clipboard(self) -> None:
        """Wkleja listę ze schowka w formacie „<ścieżka>;<ID>” (jeden plik na wiersz).
        Dla istniejącej ścieżki aktualizuje ID; nowa ścieżka → nowy wiersz."""
        text = QApplication.clipboard().text()
        if not text.strip():
            QMessageBox.information(self, "Import", "Schowek jest pusty.")
            return
        by_path = {r.video_path: r for r in self._rows.values()}
        added = updated = skipped = 0
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            # rozdziel po OSTATNIM ';' — ścieżka Windows może zawierać inne znaki,
            # ale ID jest zawsze na końcu po średniku.
            path, sep, id_str = line.rpartition(";")
            if not sep:
                path, id_str = line, ""
            path = path.strip()
            if not path:
                skipped += 1
                continue
            try:
                sid = int(id_str.strip()) if id_str.strip() else 0
            except ValueError:
                sid = 0
            if path in by_path:
                # aktualizacja ID istniejącego wiersza (przez spinbox → _on_id_changed)
                w = self._row_widgets.get(by_path[path].id)
                if w:
                    w.set_session_id(sid)
                updated += 1
            else:
                row = self._add_row(path, session_id=sid)
                if row:
                    by_path[path] = row
                    added += 1
        self._refresh()
        self._count_label.setText(
            f"Import: dodano {added}, zaktualizowano {updated}"
            + (f", pominięto {skipped}" if skipped else ""))

    def _remove_row(self, row_id: str) -> None:
        row = self._rows.get(row_id)
        if row is None or row.status in _BATCH_BUSY:
            return
        self._rows.pop(row_id, None)
        w = self._row_widgets.pop(row_id, None)
        if w:
            self._list_layout.removeWidget(w)
            w.deleteLater()
        self._refresh()

    def _clear_all(self) -> None:
        """Usuwa wszystkie pliki z listy wsadowej (pomija wiersze w trakcie
        przygotowania — nie wolno wyrwać żywego QThread)."""
        if not self._rows:
            return
        busy = any(r.status in _BATCH_BUSY for r in self._rows.values())
        if busy:
            QMessageBox.information(
                self, "Wyczyść wszystko",
                "Trwa przygotowanie lub wykrywanie ID — poczekaj na zakończenie.")
            return
        if QMessageBox.question(
                self, "Wyczyść wszystko",
                f"Usunąć wszystkie pliki z listy ({len(self._rows)})?"
                ) != QMessageBox.Yes:
            return
        for w in self._row_widgets.values():
            self._list_layout.removeWidget(w)
            w.deleteLater()
        self._rows.clear()
        self._row_widgets.clear()
        self._refresh()

    def _play_row(self, row_id: str) -> None:
        row = self._rows.get(row_id)
        if row:
            QDesktopServices.openUrl(QUrl.fromLocalFile(row.video_path))

    def _on_id_changed(self, row_id: str, value: int) -> None:
        row = self._rows.get(row_id)
        if row is None or row.status in _BATCH_BUSY:
            return
        row.session_id = value
        # zmiana ID unieważnia poprzednie przygotowanie / komunikat detekcji
        if row.status in (BatchRowStatus.READY, BatchRowStatus.FAILED):
            row.prep = None
        row.error = ""
        row.status = BatchRowStatus.PENDING if value > 0 else BatchRowStatus.NEEDS_ID
        self._sync_row(row)
        self._refresh()

    def _pick_out_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Katalog docelowy",
                                             self._out_dir_edit.text() or "")
        if d:
            self._out_dir_edit.setText(d)

    def _on_overlay_toggled(self, on: bool) -> None:
        self._clock_chk.setEnabled(on)

    # --- wykrywanie ID z sygnału tonowego ---
    def _detect_ids(self) -> None:
        """Dla wierszy bez ID odpala w tle dekodowanie sygnału tonowego (per plik).

        Wynik trafia do spinboxa wiersza (`set_session_id` → `_on_id_changed` →
        status PENDING) — bez automatycznego pobrania z API, użytkownik widzi
        i może poprawić ID przed „Przygotuj wszystkie" (jak w głównym oknie).
        """
        todo = [r for r in self._rows.values()
                if r.status == BatchRowStatus.NEEDS_ID]
        if not todo:
            QMessageBox.information(
                self, "Przetwarzanie wsadowe",
                "Brak plików bez ID — wszystkie wiersze mają już ID.")
            return
        for row in todo:
            row.status = BatchRowStatus.DETECTING
            row.error = ""
            self._sync_row(row)
            worker = BatchIdDetectWorker(row.id, row.video_path)
            worker.done.connect(self._on_id_detected)
            worker.finished.connect(lambda rid=row.id: self._workers.pop(rid, None))
            self._workers[row.id] = worker
            worker.start()
        self._refresh()

    def _on_id_detected(self, row_id: str, detected: object) -> None:
        row = self._rows.get(row_id)
        if row is None:
            return
        # najpierw wróć do NEEDS_ID, żeby _on_id_changed (guard _BATCH_BUSY)
        # przyjął wartość ustawianą przez spinbox
        row.status = BatchRowStatus.NEEDS_ID
        if not detected:
            row.error = "nie wykryto ID — podaj ręcznie"
            self._sync_row(row)
        elif w := self._row_widgets.get(row_id):
            w.set_session_id(int(detected))   # → _on_id_changed → PENDING
        else:
            row.session_id = int(detected)
            row.status = BatchRowStatus.PENDING
        self._refresh()

    # --- przygotowanie (fetch + detekcja T0) ---
    def _prepare_all(self) -> None:
        todo = [r for r in self._rows.values()
                if r.status == BatchRowStatus.PENDING and r.session_id > 0]
        if not todo:
            QMessageBox.information(
                self, "Przetwarzanie wsadowe",
                "Brak plików do przygotowania (podaj ID dla plików).")
            return
        for row in todo:
            row.status = BatchRowStatus.PREPARING
            self._sync_row(row)
            worker = BatchPrepWorker(row.id, row.video_path, row.lrf_path,
                                     row.session_id)
            worker.done.connect(self._on_prep_done)
            worker.failed.connect(self._on_prep_failed)
            worker.finished.connect(lambda rid=row.id: self._workers.pop(rid, None))
            self._workers[row.id] = worker
            worker.start()
        self._refresh()

    def _on_prep_done(self, row_id: str, result: dict) -> None:
        row = self._rows.get(row_id)
        if row is None:
            return
        row.prep = result
        row.status = BatchRowStatus.READY
        row.error = ""
        self._sync_row(row)
        self._refresh()

    def _on_prep_failed(self, row_id: str, msg: str) -> None:
        row = self._rows.get(row_id)
        if row is None:
            return
        row.error = msg
        row.status = BatchRowStatus.FAILED
        self._sync_row(row)
        self._refresh()

    # --- wysyłka do kolejki renderów ---
    def _enqueue_ready(self) -> None:
        ready = [r for r in self._rows.values() if r.status == BatchRowStatus.READY]
        if not ready:
            QMessageBox.information(
                self, "Przetwarzanie wsadowe",
                "Brak przygotowanych plików. Kliknij „Przygotuj wszystkie”.")
            return
        out_dir = Path(self._out_dir_edit.text()) if self._out_dir_edit.text() else None
        if out_dir is None or not out_dir.is_dir():
            QMessageBox.warning(self, "Brak katalogu",
                                "Wskaż istniejący katalog docelowy.")
            return
        fmt = self._format_combo.currentData()
        ext = _FORMAT_EXT.get(fmt, ".mp4")
        suffix = self._suffix_edit.text()
        add_participant = self._participant_chk.isChecked()
        no_overlay = not self._overlay_chk.isChecked()
        style = replace(self._base_style,
                        show_running_clock=self._clock_chk.isChecked())
        encoder = "auto" if self._gpu_chk.isChecked() else "cpu"

        added = 0
        for row in ready:
            p = row.prep
            session = p["session"]
            extra = ""
            if add_participant:
                extra = f"_{row.session_id}"
                part = _sanitize_filename_part(session.uczestnik or "")
                if part:
                    extra += f"_{part}"
            out_path = out_dir / (Path(row.video_path).stem + suffix + extra + ext)
            t0 = audio_sync.resolve_t0(p["t0"], AnchorMode.START_SIGNAL,
                                       session.shots[0].czas)
            kwargs = dict(
                video_path=row.video_path, session=session, t0=t0,
                style=style, mode=AnchorMode.START_SIGNAL, out_path=str(out_path),
                trim_start=p["trim_start"] if p["trim_start"] > 0 else None,
                trim_end=p["trim_end"] if p["trim_end"] > 0 else None,
                encoder=encoder, no_overlay=no_overlay, output_format=fmt,
            )
            job = RenderJob(
                id=uuid.uuid4().hex,
                label=f"{Path(row.video_path).name} → {out_path.name}",
                kwargs=kwargs)
            self._queue_window.add_job(job)
            added += 1
            # zostaw wiersz, ale oznacz jako wysłany (PENDING bez ID-edycji)
            row.status = BatchRowStatus.PENDING
            row.prep = None
            self._sync_row(row)

        self._queue_window.show()
        self._queue_window.raise_()
        self._refresh()
        QMessageBox.information(
            self, "Przetwarzanie wsadowe",
            f"Dodano {added} zadań do kolejki. Kliknij „Start kolejki” w oknie kolejki.")

    # --- pomocnicze ---
    def _sync_row(self, row: BatchRow) -> None:
        if w := self._row_widgets.get(row.id):
            w.update_row(row)

    def _refresh(self) -> None:
        n = len(self._rows)
        ready = sum(1 for r in self._rows.values() if r.status == BatchRowStatus.READY)
        pending = sum(1 for r in self._rows.values()
                      if r.status == BatchRowStatus.PENDING and r.session_id > 0)
        busy = any(r.status in _BATCH_BUSY for r in self._rows.values())
        needs_id = sum(1 for r in self._rows.values()
                       if r.status == BatchRowStatus.NEEDS_ID)
        self._count_label.setText(
            f"Plików: {n} · gotowych: {ready}" if n else "Brak plików.")
        self._prep_btn.setEnabled(pending > 0 and not busy)
        self._enqueue_btn.setEnabled(ready > 0 and not busy)
        self._clear_btn.setEnabled(n > 0 and not busy)
        self._detect_id_btn.setEnabled(needs_id > 0 and not busy)

    def closeEvent(self, event):
        if any(r.status in _BATCH_BUSY for r in self._rows.values()):
            self.hide()
            event.ignore()
        else:
            event.accept()


# ----------------------------- waveform -----------------------------
class WaveformWidget(QWidget):
    """Wizualizacja ścieżki audio z interakcją:

    - lewy klik (poza uchwytami) → ustawia kotwicę T0,
    - Ctrl + lewy klik → podgląd klatki w danym czasie (bez zmiany T0),
    - przeciągnięcie uchwytu (zielony=start, czerwony=koniec) → przycięcie fragmentu,
    - cienkie znaczniki = wykryte onsety (pomoc w trafieniu sygnału/strzału).
    """

    anchorChanged = Signal(float)
    trimChanged = Signal(float, float)
    previewAt = Signal(float)   # Ctrl+klik → podgląd w czasie t

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(140)
        self.env: list[float] = []
        self.duration = 0.0
        self.onsets: list[float] = []
        self.anchor: float | None = None
        self.anchor_label = "T0"      # "T0" (beep) lub "T1" (pierwszy strzał) wg trybu
        self.preview_t: float | None = None   # czas aktualnie podglądu (Ctrl+klik)
        self.trim_start = 0.0
        self.trim_end = 0.0
        # okno widoku (zoom): widoczny zakres czasu [view_start, view_end]
        self.view_start = 0.0
        self.view_end = 0.0
        self._drag: str | None = None  # "start" | "end" | None
        self._pan = None               # (x0, vs, ve) podczas przesuwania
        self.setCursor(Qt.CrossCursor)
        self.setToolTip("Klik = ustaw kotwicę (snap do strzału) · "
                        "Ctrl+klik = podgląd klatki w danym czasie · "
                        "kółko = zoom · prawy przycisk = przesuń · dwuklik = reset zoomu")

    def set_data(self, env, duration, onsets):
        self.env = env
        self.duration = duration
        self.onsets = onsets
        self.trim_start = 0.0
        self.trim_end = duration
        self.anchor = None
        self.preview_t = None
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

        # kursor podglądu (Ctrl+klik)
        if self.preview_t is not None and self._in_view(self.preview_t):
            p.setPen(QPen(QColor(255, 140, 0), 2, Qt.DashLine))
            xp = int(self._t2x(self.preview_t))
            p.drawLine(xp, 0, xp, plot_h)

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

        orange = QColor(255, 140, 0)
        if self.preview_t is not None and self._in_view(self.preview_t):
            self._tag(p, int(self._t2x(self.preview_t)),
                      f"▶ {_fmt_axis_time(self.preview_t)}", orange, "center")

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
        t = self._x2t(x)
        # Ctrl+klik → podgląd w czasie t (bez zmiany kotwicy T0)
        if e.modifiers() & Qt.ControlModifier:
            self.preview_t = t
            self.update()
            self.previewAt.emit(t)
            return
        if abs(x - self._t2x(self.trim_start)) <= _HANDLE_PX:
            self._drag = "start"
        elif abs(x - self._t2x(self.trim_end)) <= _HANDLE_PX:
            self._drag = "end"
        else:
            self.set_anchor(self._snap_to_onset(t))
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


class PreviewLabel(QLabel):
    """QLabel podglądu z trybem edycji pozycji — przeciąganie nakładek myszą.

    Mapuje współrzędne kliknięcia (w widżecie) na piksele wyświetlanej klatki,
    uwzględniając wyśrodkowany pixmap (KeepAspectRatio z letterboxem). Emituje
    zdarzenia w pikselach klatki; logikę „co złapano i jak przesunąć offset"
    obsługuje MainWindow.
    """
    grabbed = Signal(float, float)   # (fx, fy) w pikselach klatki podglądu
    dragged = Signal(float, float)
    dropped = Signal()

    def __init__(self, *args):
        super().__init__(*args)
        self._disp: QRect | None = None    # gdzie leży pixmap wewnątrz widżetu
        self._frame_size: tuple[int, int] | None = None
        self.edit_mode = False

    def set_frame_geometry(self, disp: QRect, frame_size: tuple[int, int]) -> None:
        self._disp = disp
        self._frame_size = frame_size

    def _to_frame(self, pos) -> tuple[float, float] | None:
        if not self._disp or not self._frame_size or self._disp.width() <= 0:
            return None
        fx = (pos.x() - self._disp.x()) / self._disp.width() * self._frame_size[0]
        fy = (pos.y() - self._disp.y()) / self._disp.height() * self._frame_size[1]
        return fx, fy

    def mousePressEvent(self, e):
        if self.edit_mode and e.button() == Qt.LeftButton:
            f = self._to_frame(e.position())
            if f:
                self.grabbed.emit(*f)
                return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self.edit_mode and (e.buttons() & Qt.LeftButton):
            f = self._to_frame(e.position())
            if f:
                self.dragged.emit(*f)
                return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.edit_mode and e.button() == Qt.LeftButton:
            self.dropped.emit()
        super().mouseReleaseEvent(e)


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
        self.lrf_path: str | None = None
        self.worker: RenderWorker | None = None
        self.wave_worker: WaveformWorker | None = None
        self._detect_workers: list[StartDetectWorker] = []
        self._detect_gen: int = 0
        self._video_size: tuple[int, int] | None = None  # (w, h) — do skalowania podglądu
        # Zapisane ustawienia tego pliku, czekające na zastosowanie po analizie audio
        # (spiny czasu mają sensowny zakres dopiero po poznaniu długości nagrania).
        self._pending_file_settings: dict | None = None
        # True gdy ustawienia bieżącego pliku są „ustabilizowane" (po analizie audio):
        # dopiero wtedy wolno je zapisać (inaczej zapisalibyśmy domyślne wartości
        # widgetów, zanim wczytany/wykryty T0/trim zostanie zastosowany).
        self._file_settings_ready: bool = False
        # Edycja pozycji w podglądzie (przeciąganie nakładek).
        self._preview_rects: dict[str, tuple[int, int, int, int]] = {}
        self._grab: dict | None = None
        self.last_output: str | None = None
        self._used_encoder: str | None = None
        self._render_busy: bool = False
        self._queue_runner: RenderQueueRunner | None = None
        self._queue_window: RenderQueueWindow | None = None
        self._batch_window: BatchDialog | None = None
        # Podgląd — cache klatki + timer debouncujący ekstrakcję FFmpeg
        self._cached_frame: Image.Image | None = None
        self._cached_frame_t: float = -1.0
        self._frame_worker: FrameExtractWorker | None = None
        self._preview_timer = QTimer()
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._do_request_frame)
        # Scrubber — timer debouncujący ekstrakcję klatki dla Ctrl+klik
        self._scrubber_t: float | None = None
        self._scrubber_timer = QTimer()
        self._scrubber_timer.setSingleShot(True)
        self._scrubber_timer.timeout.connect(self._do_scrubber_preview)
        # Autosave stylu — debouncowany, aby nie pisać na dysk przy każdym spinboxie
        self._autosave_timer = QTimer()
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.timeout.connect(lambda: config.save_last_style(self.current_style()))
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
        left_scroll.setMinimumWidth(360)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)

        self.edit_pos_btn = QPushButton("✥ Edytuj pozycje (przeciąganie)")
        self.edit_pos_btn.setCheckable(True)
        self.edit_pos_btn.setToolTip(
            "Tryb edycji: przeciągaj w podglądzie panel strzału i zegar, by ustawić ich\n"
            "pozycję (offsety). W tym trybie podgląd pokazuje panel strzału także przy\n"
            "kotwicy „Sygnał startu”.")
        self.edit_pos_btn.toggled.connect(self._on_edit_pos_toggled)
        right.addWidget(self.edit_pos_btn)

        self.preview_label = PreviewLabel("Przeciągnij tu plik wideo lub użyj „…”")
        self.preview_label.setMinimumSize(480, 270)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("background:#222;color:#aaa;")
        self.preview_label.grabbed.connect(self._on_preview_grab)
        self.preview_label.dragged.connect(self._on_preview_drag)
        self.preview_label.dropped.connect(self._on_preview_drop)
        right.addWidget(self.preview_label, 3)

        self.waveform = WaveformWidget()
        self.waveform.anchorChanged.connect(self._on_wave_anchor)
        self.waveform.trimChanged.connect(self._on_wave_trim)
        self.waveform.previewAt.connect(self._on_preview_at)
        right.addWidget(self.waveform, 1)
        right_container = QWidget()
        right_container.setLayout(right)

        # QSplitter — użytkownik może przeciągnąć granicę i zwęzić lewą kolumnę.
        # Lewy panel dostaje mniejszy udział startowy, by nie był zbyt szeroki.
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_scroll)
        splitter.addWidget(right_container)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([380, 800])
        root.addWidget(splitter)

        # Etykieta kotwicy (T0/T1) zależy od trybu — podłączamy po utworzeniu waveformu.
        self.anchor_combo.currentIndexChanged.connect(self._on_anchor_mode_changed)
        self._on_anchor_mode_changed()

        # Wczytaj ostatni styl z dysku (jeśli istnieje) — bez triggerowania autosave.
        last_style = config.load_last_style()
        if last_style is not None:
            self._apply_style(last_style)

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
        self.rb_id.setChecked(True)
        grp = QButtonGroup(self); grp.addButton(self.rb_text); grp.addButton(self.rb_id)
        srow = QHBoxLayout(); srow.addWidget(self.rb_text); srow.addWidget(self.rb_id)
        form.addRow("Źródło", _wrap(srow))

        self.timeline_edit = QPlainTextEdit()
        self.timeline_edit.setPlaceholderText("1: 2.81s | 2: 4.63s (+1.82s) | ...")
        self.timeline_edit.setMaximumHeight(80)
        self.timeline_edit.textChanged.connect(self._update_preview)
        form.addRow("Oś czasu", self.timeline_edit)

        self.id_spin = QSpinBox(); self.id_spin.setRange(1, _SESSION_ID_MAX)
        fetch = QPushButton("Pobierz")
        fetch.setToolTip("Pobiera oś czasu i metadane z API (bez zmiany przycięcia).")
        fetch.clicked.connect(self._fetch_id)
        fetch_trim = QPushButton("Pobierz i przytnij")
        fetch_trim.setToolTip(
            "Pobiera z API, wykrywa sygnał startu (T0) i przycina film:\n"
            "5 s przed T0 → ostatni strzał + 5 s.")
        fetch_trim.clicked.connect(self._fetch_id_and_trim)
        for b in (fetch, fetch_trim):
            b.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        idrow = QHBoxLayout(); idrow.addWidget(self.id_spin)
        idrow.addWidget(fetch); idrow.addWidget(fetch_trim)
        form.addRow("ID", _wrap(idrow))

        detect_id_tone = QPushButton("Wykryj ID z audio")
        detect_id_tone.setToolTip(
            "Szuka w nagraniu sygnału tonowego ID, który timer odtwarza po zapisie\n"
            "sesji w bazie (marker 5000 Hz + 4 cyfry + cyfra kontrolna, 5200–7000 Hz)\n"
            "i wpisuje wykryte ID. Zawsze analizuje oryginalny plik (nie proxy LRF).")
        detect_id_tone.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        detect_id_tone.clicked.connect(self._detect_id_tone)
        detect_row = QHBoxLayout(); detect_row.addWidget(detect_id_tone)
        form.addRow("", _wrap(detect_row))

        self.api_meta_label = QLabel()
        self.api_meta_label.setStyleSheet("color: #aaaaaa;")
        self.api_meta_label.hide()
        form.addRow("", self.api_meta_label)
        self.rb_id.toggled.connect(
            lambda checked: self.api_meta_label.setVisible(
                checked and bool(self.api_meta_label.text())
            )
        )
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

        detect = QPushButton("Wykryj kotwicę")
        detect.setToolTip("Szuka pierwszego wyraźnego onsetu w zaznaczonym fragmencie.")
        detect.clicked.connect(self._detect)
        nextc = QPushButton("Następny kandydat")
        nextc.setToolTip("Przeskakuje do kolejnego wykrytego onsetu.")
        nextc.clicked.connect(self._next_candidate)
        start_sig = QPushButton("Wykryj sygnał startu")
        start_sig.setToolTip(
            "Filtr pasmowy 2000–4500 Hz (pasmo buzzera shot-timera) + wybór\n"
            "najgłośniejszego bzyczka. Ustawia typ kotwicy na „Sygnał startu”\n"
            "i przelicza T0. Działa dobrze na nagraniach DJI Osmo.")
        start_sig.clicked.connect(self._detect_start_signal)
        # Przyciski nie wymuszają minimalnej szerokości tekstu — mogą się zwężać,
        # by lewy panel nie rozpychał się przez długie etykiety.
        for b in (detect, nextc, start_sig):
            b.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        drow = QHBoxLayout()
        drow.addWidget(detect); drow.addWidget(nextc); drow.addWidget(start_sig)
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

        self.tail_spin = _dspin(0.0, 60.0, 0.5, " s", _TRIM_TAIL_S)
        self.tail_spin.setToolTip("Margines (s) doliczany po ostatnim strzale przy auto-przycięciu.")
        self.tail_spin.setMaximumWidth(120)  # węższe pole, ale bez ucinania sufiksu „ s"
        autotrim_btn = QPushButton("Auto-przycięcie")
        autotrim_btn.setToolTip(
            "Ustaw zakres przycięcia: 5 s przed startem → ostatni strzał + margines.")
        autotrim_btn.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        autotrim_btn.clicked.connect(self._apply_auto_trim)
        # Margines i przycisk w jednej linii (przycisk wypełnia resztę szerokości).
        mrow = QHBoxLayout()
        mrow.addWidget(self.tail_spin)
        mrow.addWidget(autotrim_btn, 1)
        form.addRow("Margines końcowy", _wrap(mrow))
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

        self.off_x = _ispin(0, 8000, _DEFAULT_OFFSET_PX)
        self.off_y = _ispin(0, 8000, _DEFAULT_OFFSET_PX)
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

        self.clock_chk = QCheckBox("Płynący czas od T0 (nad nakładką, od STARTU)")
        self.clock_chk.setToolTip(
            "Nad nakładką ze strzałami pokazuje płynący zegar „T+x.xs” liczony od\n"
            "sygnału startu (T0). Widoczny już od STARTU, jeszcze przed pierwszym strzałem.")
        self.clock_chk.stateChanged.connect(self._update_preview)
        form.addRow(self.clock_chk)

        self.clock_pos_combo = QComboBox()
        self.clock_pos_combo.addItem("Nad nakładką (auto)", "auto")
        for p in ANCHOR_POSITIONS:
            self.clock_pos_combo.addItem(p, p)
        self.clock_pos_combo.setToolTip(
            "Gdzie umieścić zegar. „Nad nakładką (auto)” trzyma go tuż nad panelem\n"
            "strzału; pozostałe opcje pozycjonują go niezależnie (róg + offset poniżej).")
        self.clock_pos_combo.currentIndexChanged.connect(self._update_preview)
        form.addRow("Pozycja zegara", self.clock_pos_combo)

        self.clock_off_x = _ispin(0, 8000, _DEFAULT_OFFSET_PX)
        self.clock_off_y = _ispin(0, 8000, _DEFAULT_OFFSET_PX)
        self.clock_off_x.setToolTip("Offset zegara X (używany, gdy pozycja ≠ „auto”).")
        self.clock_off_y.setToolTip("Offset zegara Y (używany, gdy pozycja ≠ „auto”).")
        self.clock_off_x.valueChanged.connect(self._update_preview)
        self.clock_off_y.valueChanged.connect(self._update_preview)
        crow = QHBoxLayout(); crow.addWidget(self.clock_off_x); crow.addWidget(self.clock_off_y)
        form.addRow("Offset zegara X / Y", _wrap(crow))

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

        preset_row = QHBoxLayout()
        load_preset_btn = QPushButton("Wczytaj preset…")
        save_preset_btn = QPushButton("Zapisz preset…")
        load_preset_btn.clicked.connect(self._load_preset)
        save_preset_btn.clicked.connect(self._save_preset)
        preset_row.addWidget(load_preset_btn)
        preset_row.addWidget(save_preset_btn)
        form.addRow(_wrap(preset_row))

        self.appearance_box = box
        return box

    def _apply_style(self, style: OverlayStyle) -> None:
        """Ustawia wszystkie widgety wyglądu z podanego OverlayStyle (bez pośrednich preview)."""
        widgets = [
            self.lang_combo, self.scale_spin, self.pos_combo,
            self.off_x, self.off_y, self.bg_btn, self.text_btn,
            self.accent_btn, self.border_btn, self.border_chk, self.border_w,
            self.clock_chk, self.clock_pos_combo, self.clock_off_x, self.clock_off_y,
            self.banner_spin, self.banner_scale_spin, self.banner_bg_btn,
            self.banner_text_btn, self.banner_border_btn, self.banner_border_chk,
            self.banner_border_w,
        ]
        for w in widgets:
            w.blockSignals(True)

        idx = self.lang_combo.findData(style.lang)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
        self.scale_spin.setValue(style.scale)
        self.pos_combo.setCurrentText(style.position)
        self.off_x.setValue(style.offset_x)
        self.off_y.setValue(style.offset_y)
        self.bg_btn._rgba = style.bg_color;     self.bg_btn._refresh()
        self.text_btn._rgba = style.text_color; self.text_btn._refresh()
        self.accent_btn._rgba = style.accent_color; self.accent_btn._refresh()
        self.border_btn._rgba = style.border_color; self.border_btn._refresh()
        self.border_chk.setChecked(style.border_enabled)
        self.border_w.setValue(style.border_width)
        self.clock_chk.setChecked(style.show_running_clock)
        cidx = self.clock_pos_combo.findData(style.clock_position)
        if cidx >= 0:
            self.clock_pos_combo.setCurrentIndex(cidx)
        self.clock_off_x.setValue(style.clock_offset_x)
        self.clock_off_y.setValue(style.clock_offset_y)
        self.banner_spin.setValue(style.start_banner_duration)
        self.banner_scale_spin.setValue(style.start_banner_scale)
        self.banner_bg_btn._rgba = style.start_banner_bg_color; self.banner_bg_btn._refresh()
        self.banner_text_btn._rgba = style.start_banner_text_color; self.banner_text_btn._refresh()
        self.banner_border_btn._rgba = style.start_banner_border_color; self.banner_border_btn._refresh()
        self.banner_border_chk.setChecked(style.start_banner_border_enabled)
        self.banner_border_w.setValue(style.start_banner_border_width)

        for w in widgets:
            w.blockSignals(False)
        self._update_preview()

    def _save_preset(self) -> None:
        start_dir = config.load_last_dir("preset") or ""
        default_name = str(Path(start_dir) / "preset_nakładki.json") if start_dir else "preset_nakładki.json"
        path, _ = QFileDialog.getSaveFileName(
            self, "Zapisz preset wyglądu", default_name,
            "Preset JSON (*.json)")
        if not path:
            return
        config.save_last_dir("preset", Path(path).parent)
        try:
            self.current_style().to_json(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Błąd zapisu", str(exc))

    def _load_preset(self) -> None:
        start_dir = config.load_last_dir("preset") or ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Wczytaj preset wyglądu", start_dir,
            "Preset JSON (*.json)")
        if not path:
            return
        config.save_last_dir("preset", Path(path).parent)
        try:
            style = OverlayStyle.from_json(path)
            self._apply_style(style)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Błąd wczytywania presetu", str(exc))

    def _output_group(self):
        box = QGroupBox("Wyjście")
        v = QVBoxLayout(box)
        self.out_edit = QLineEdit()
        out_browse = QPushButton("…"); out_browse.clicked.connect(self._choose_output)
        orow = QHBoxLayout(); orow.addWidget(self.out_edit); orow.addWidget(out_browse)
        v.addLayout(orow)

        self.format_combo = QComboBox()
        self.format_combo.addItem("MP4 (H.264)", "mp4")
        self.format_combo.addItem("WebM (VP9)", "webm")
        self.format_combo.addItem("GIF (animowany)", "gif")
        self.format_combo.currentIndexChanged.connect(self._on_format_changed)
        frow = QHBoxLayout()
        frow.addWidget(QLabel("Format wyjścia:"))
        frow.addWidget(self.format_combo)
        v.addLayout(frow)

        self.no_overlay_chk = QCheckBox("Bez nakładki (tylko przycięcie)")
        self.no_overlay_chk.stateChanged.connect(self._on_no_overlay_toggled)
        v.addWidget(self.no_overlay_chk)
        self.gpu_chk = QCheckBox("Akceleracja GPU (NVENC, jeśli dostępna)")
        self.gpu_chk.setChecked(True)
        v.addWidget(self.gpu_chk)
        self.nvenc_label = QLabel()
        self._refresh_nvenc_status()
        v.addWidget(self.nvenc_label)
        diag = QPushButton("Diagnostyka NVENC")
        diag.setToolTip("Pokazuje status NVENC, użytą binarkę FFmpeg "
                        "i szczegóły błędu, gdy test kodowania nie przeszedł")
        diag.clicked.connect(self._show_nvenc_diag)
        v.addWidget(diag)
        cli_btn = QPushButton("Pokaż komendę CLI")
        cli_btn.setToolTip(
            "Buduje równoważne wywołanie bezgłowe (PiroOverlay.exe …) z bieżących\n"
            "ustawień — do skryptów/automatyzacji. Można je skopiować do schowka.")
        cli_btn.clicked.connect(self._show_cli_command)
        v.addWidget(cli_btn)
        self.progress = QProgressBar(); v.addWidget(self.progress)
        # Wiersz 1: Renderuj / Zatrzymaj — w jednej linii, mniejsze (nie rozciągają się).
        brow = QHBoxLayout()
        self.render_btn = QPushButton("Renderuj"); self.render_btn.clicked.connect(self._start_render)
        self.cancel_btn = QPushButton("Zatrzymaj")
        self.cancel_btn.setToolTip("Przerywa trwające renderowanie i usuwa niedokończony plik.")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_render)
        self.render_btn.setMaximumWidth(120)
        self.cancel_btn.setMaximumWidth(120)
        brow.addWidget(self.render_btn)
        brow.addWidget(self.cancel_btn)
        brow.addStretch(1)
        v.addLayout(brow)

        # Wiersz 2: kolejka renderów.
        qrow = QHBoxLayout()
        self.queue_add_btn = QPushButton("Dodaj do kolejki")
        self.queue_add_btn.setToolTip(
            "Dodaje render z bieżącymi ustawieniami jako zadanie kolejki")
        self.queue_add_btn.clicked.connect(self._add_to_queue)
        self.queue_show_btn = QPushButton("Kolejka")
        self.queue_show_btn.setToolTip("Otwiera okno kolejki renderów")
        self.queue_show_btn.clicked.connect(self._show_queue_window)
        qrow.addWidget(self.queue_add_btn)
        qrow.addWidget(self.queue_show_btn)
        qrow.addStretch(1)
        v.addLayout(qrow)

        # Wiersz 3: przetwarzanie wsadowe.
        bbrow = QHBoxLayout()
        self.batch_btn = QPushButton("Wsadowo…")
        self.batch_btn.setToolTip("Przetwarzanie wielu plików (tryb auto + ID)")
        self.batch_btn.clicked.connect(self._show_batch_window)
        bbrow.addWidget(self.batch_btn)
        bbrow.addStretch(1)
        v.addLayout(bbrow)

        # Wiersz 4: otwarcie wyniku — widoczne dopiero PO zakończeniu renderu.
        orow2 = QHBoxLayout()
        self.open_btn = QPushButton("Otwórz folder z wynikiem")
        self.open_btn.setVisible(False)
        self.open_btn.clicked.connect(self._open_output_folder)
        orow2.addWidget(self.open_btn)
        orow2.addStretch(1)
        v.addLayout(orow2)
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
            show_running_clock=self.clock_chk.isChecked(),
            clock_position=self.clock_pos_combo.currentData(),
            clock_offset_x=self.clock_off_x.value(),
            clock_offset_y=self.clock_off_y.value(),
            start_banner_duration=self.banner_spin.value(),
            start_banner_scale=self.banner_scale_spin.value(),
            start_banner_bg_color=self.banner_bg_btn.rgba(),
            start_banner_text_color=self.banner_text_btn.rgba(),
            start_banner_border_enabled=self.banner_border_chk.isChecked(),
            start_banner_border_color=self.banner_border_btn.rgba(),
            start_banner_border_width=self.banner_border_w.value(),
        )

    def _choose_video(self):
        start_dir = config.load_last_dir("video") or ""
        path, _ = QFileDialog.getOpenFileName(self, "Wybierz wideo", start_dir,
                                              "Wideo (*.mp4 *.mov *.mkv *.avi)")
        if path:
            config.save_last_dir("video", Path(path).parent)
            self._set_video(path)

    def _set_video(self, path: str):
        # Zanim podmienimy plik — zapisz ustawienia poprzedniego (jeśli były gotowe),
        # by nie zgubić zmian zrobionych bez renderu/kolejki (np. wpisane ID z API).
        if self.video_path and self._file_settings_ready:
            self._save_file_settings()
        self._file_settings_ready = False
        self.video_path = path
        self.video_edit.setText(path)
        p = Path(path)
        out_ext = _FORMAT_EXT.get(self.format_combo.currentData(), ".mp4")
        self.out_edit.setText(str(p.with_name(p.stem + "_PiRoOverlay" + out_ext)))
        # Inwaliduj cache — nowe wideo, stara klatka nieaktualna
        self._cached_frame = None
        self._cached_frame_t = -1.0
        # Rozmiar wideo (do skalowania offsetów w podglądzie ≈ render).
        try:
            info = ffmpeg.probe(path)
            self._video_size = (info.width, info.height)
        except Exception:  # noqa: BLE001
            self._video_size = None

        # Zapamiętane ustawienia dla tego pliku (zastosujemy po analizie audio).
        self._pending_file_settings = config.load_file_settings(path)

        lrf = ffmpeg.find_lrf(path)
        self.lrf_path = str(lrf) if lrf else None
        audio_src = self.lrf_path or path
        msg = "Analiza audio (proxy LRF)…" if self.lrf_path else "Analiza audio…"
        self.preview_label.setText(msg)

        self.wave_worker = WaveformWorker(audio_src)
        self.wave_worker.done.connect(self._on_wave_done)
        self.wave_worker.failed.connect(lambda m: self.preview_label.setText("Błąd audio: " + m))
        self.wave_worker.start()
        self._request_frame()

    def _on_wave_done(self, env, dur, onsets):
        self.waveform.set_data(env, dur, onsets)
        for s in (self.trim_start_spin, self.trim_end_spin, self.t0_spin):
            s.setMaximum(max(dur, 1.0))
        self._set_trim_silently(0.0, dur)
        self._update_preview()
        # Jeśli ten plik był już renderowany/dodany do kolejki — przywróć jego ustawienia
        # i NIE uruchamiaj auto-detekcji (zapisany T0/przycięcie ma pierwszeństwo).
        pending = self._pending_file_settings
        self._pending_file_settings = None
        if pending:
            self._apply_file_settings(pending)
            self._file_settings_ready = True  # wolno zapisywać (mamy komplet)
            self.statusBar().showMessage(
                "Wczytano zapisane ustawienia dla tego pliku.", 6000)
            return
        # Pierwszy raz dla tego pliku → wykryj T0 (buzzer) i ustaw przycięcie.
        self._file_settings_ready = True
        self._auto_detect_t0()

    def _auto_detect_t0(self) -> None:
        """Startuje detekcję bzyczka (T0) w tle po imporcie pliku; po wykryciu
        ustawia kotwicę + przycięcie: 5 s przed T0 → max 75 s po T0.
        (Przycięcie po pobraniu z API robi synchronicznie „Pobierz i przytnij".)
        """
        if not self.video_path:
            return
        src = self.lrf_path or self.video_path
        self._detect_gen += 1
        worker = StartDetectWorker(src, self._detect_gen)
        worker.done.connect(self._on_autodetect_t0)
        # Trzymaj referencję dopóki wątek żyje — inaczej QThread może zostać
        # zniszczony w trakcie działania (crash). Sprzątamy po zakończeniu.
        self._detect_workers.append(worker)
        worker.finished.connect(lambda w=worker: self._detect_workers.remove(w)
                                if w in self._detect_workers else None)
        worker.start()

    def _on_autodetect_t0(self, gen: int, detected) -> None:
        if gen != self._detect_gen:
            return  # przestarzały wynik (nowsza detekcja już w toku) — ignoruj
        if detected is None:
            return  # nie wykryto — użytkownik ustawi ręcznie, bez komunikatu
        self._force_start_signal_mode()
        self.t0_spin.setValue(detected)
        dur = self.waveform.duration or None
        start = max(0.0, detected - _LEAD_IN_S)
        end = detected + _IMPORT_TAIL_S
        if dur:
            end = min(end, dur)
        self.trim_start_spin.setValue(start)
        self.trim_end_spin.setValue(end)

    def _force_start_signal_mode(self) -> None:
        """Wykryty bzyczek JEST sygnałem startu → wymuś tryb kotwicy START_SIGNAL."""
        idx = self.anchor_combo.findData(AnchorMode.START_SIGNAL.value)
        if idx >= 0:
            self.anchor_combo.setCurrentIndex(idx)

    def _set_trim_silently(self, start: float, end: float) -> None:
        """Ustawia spiny przycięcia bez emitowania sygnałów (bez pętli zwrotnej
        waveform ↔ spinboxy)."""
        self.trim_start_spin.blockSignals(True); self.trim_end_spin.blockSignals(True)
        self.trim_start_spin.setValue(start); self.trim_end_spin.setValue(end)
        self.trim_start_spin.blockSignals(False); self.trim_end_spin.blockSignals(False)

    def _choose_output(self):
        fmt = self.format_combo.currentData()
        filters = {
            "mp4":  "Wideo MP4 (*.mp4)",
            "webm": "Wideo WebM (*.webm)",
            "gif":  "Animowany GIF (*.gif)",
        }
        current_text = self.out_edit.text()
        if current_text:
            default_name = current_text
        else:
            start_dir = config.load_last_dir("output") or ""
            default_name = str(Path(start_dir) / "output.mp4") if start_dir else "output.mp4"
        path, _ = QFileDialog.getSaveFileName(
            self, "Plik wyjściowy", default_name,
            filters.get(fmt, "Wideo (*.mp4)"))
        if path:
            config.save_last_dir("output", Path(path).parent)
            self.out_edit.setText(path)

    def _build_session(self):
        if self.rb_id.isChecked():
            return api.fetch_session(self.id_spin.value())
        shots = parse_timeline(self.timeline_edit.toPlainText())
        if self.session is not None:
            return replace(self.session, shots=shots)
        return Session(shots=shots)

    def _fetch_id(self, silent: bool = False) -> bool:
        """Pobiera dane sesji z API po ID. `silent=True` — bez modala przy błędzie
        (status bar zamiast okna), używane przy automatycznym wczytaniu ustawień pliku."""
        try:
            self.session = api.fetch_session(self.id_spin.value())
            self.timeline_edit.setPlainText(
                " | ".join(self._shot_to_text(s) for s in self.session.shots))
            parts = []
            if self.session.nazwa_toru:
                parts.append(f"Tor: {self.session.nazwa_toru}")
            if self.session.uczestnik:
                parts.append(f"Zawodnik: {self.session.uczestnik}")
            self.api_meta_label.setText("  |  ".join(parts))
            self.api_meta_label.setVisible(bool(parts))
            self._update_preview()
            return True
        except Exception as exc:  # noqa: BLE001
            if silent:
                self.statusBar().showMessage(
                    f"Nie udało się pobrać danych z API (ID {self.id_spin.value()}): {exc}", 8000)
            else:
                QMessageBox.critical(self, "Błąd API", str(exc))
            return False

    def _fetch_id_and_trim(self):
        """Pobiera dane z API, ustala T0 (wykrywa bzyczek jeśli trzeba) i przycina
        film: 5 s przed T0 → ostatni strzał + 5 s.

        Działa synchronicznie (deterministycznie) — w przeciwieństwie do detekcji
        w tle daje natychmiastowy, widoczny wynik i jasny komunikat przy problemie.
        """
        if not self.video_path:
            QMessageBox.warning(self, "Brak wideo",
                                "Najpierw wybierz plik wideo — przycięcie wymaga audio.")
            return
        if not self._fetch_id():
            return
        session = self.session
        if not (session and session.shots):
            QMessageBox.warning(self, "Brak osi czasu",
                                "API nie zwróciło strzałów — nie mam czego przyciąć.")
            return

        # T0 = już wykryty przy imporcie (t0_spin) albo wykryj teraz (na LRF — szybko).
        t0 = self.t0_spin.value()
        if t0 <= 0:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                src = self.lrf_path or self.video_path
                detected = audio_sync.detect_dji_start(src)
            finally:
                QApplication.restoreOverrideCursor()
            if detected is None:
                QMessageBox.warning(
                    self, "Nie wykryto sygnału startu",
                    "Nie udało się wykryć bzyczka. Ustaw T0 ręcznie (klik na waveformie "
                    "lub „Wykryj sygnał startu”) i kliknij „Pobierz i przytnij” ponownie.")
                return
            t0 = detected
            self._force_start_signal_mode()
            self.t0_spin.setValue(t0)

        dur = self.waveform.duration or None
        start, end = render.auto_trim_window(
            t0, session.shots[-1].czas,
            tail=_TRIM_TAIL_S, lead_in=_LEAD_IN_S, duration=dur)
        self.trim_start_spin.setValue(start)
        self.trim_end_spin.setValue(end)
        self.statusBar().showMessage(
            f"Przycięto: {start:.2f}s – {end:.2f}s (T0={t0:.2f}s, "
            f"ostatni strzał {session.shots[-1].czas:.2f}s)", 8000)

    @staticmethod
    def _shot_to_text(shot):
        if shot.split is None:
            return f"{shot.numer}: {shot.czas:.2f}s"
        return f"{shot.numer}: {shot.czas:.2f}s (+{shot.split:.2f}s)"

    def _detect(self):
        if not self.video_path:
            QMessageBox.warning(self, "Brak wideo", "Najpierw wybierz plik wideo.")
            return
        src = self.lrf_path or self.video_path
        s = self.trim_start_spin.value()
        e = self.trim_end_spin.value() or None
        detected = audio_sync.detect_start(src, start=s, end=e)
        if detected is None:
            QMessageBox.warning(self, "Detekcja", "Nie wykryto sygnału — ustaw ręcznie.")
            return
        self.t0_spin.setValue(detected)  # wywoła _on_t0_spin → waveform + podgląd

    def _detect_start_signal(self):
        """Wykrywa bzyczek shot-timera (filtr 2–4.5 kHz) i ustawia go jako T0.

        Wymusza tryb kotwicy „Sygnał startu” — wykryty bzyczek JEST sygnałem
        startu, więc T0 = czas bzyczka (bez przesunięcia o pierwszy strzał).
        """
        if not self.video_path:
            QMessageBox.warning(self, "Brak wideo", "Najpierw wybierz plik wideo.")
            return
        src = self.lrf_path or self.video_path
        s = self.trim_start_spin.value()
        e = self.trim_end_spin.value() or None
        detected = audio_sync.detect_dji_start(src, start=s, end=e)
        if detected is None:
            QMessageBox.warning(self, "Detekcja",
                                "Nie wykryto sygnału startu — ustaw ręcznie.")
            return
        self._force_start_signal_mode()
        self.t0_spin.setValue(detected)  # wywoła _on_t0_spin → waveform + podgląd

    def _detect_id_tone(self):
        """Dekoduje ID sesji z sygnału tonowego (timer po zapisie w bazie).

        Zawsze analizuje `self.video_path` — NIE proxy LRF (proxy nie było
        częścią pomiaru, którym dobrano pasmo 5000–7000 Hz, a sygnał ID gra
        pod koniec nagrania, poza oknem, na którym LRF jest zwykle używane
        do detekcji T0).
        """
        if not self.video_path:
            QMessageBox.warning(self, "Brak wideo", "Najpierw wybierz plik wideo.")
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            detected = audio_sync.decode_id_tone(self.video_path)
        finally:
            QApplication.restoreOverrideCursor()
        if detected is None:
            QMessageBox.warning(
                self, "Detekcja",
                "Nie znaleziono sygnału ID w audio — wpisz ID ręcznie.")
            return
        self.id_spin.setValue(detected)
        self.statusBar().showMessage(f"Wykryto ID z audio: {detected}", 8000)

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
        self._set_trim_silently(start, end)

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

    def _on_preview_at(self, t: float) -> None:
        """Ctrl+klik na waveformie → pokaż klatkę z nakładką odpowiednią dla czasu t."""
        if not self.video_path:
            return
        self._scrubber_t = t
        self._scrubber_timer.start(_SCRUBBER_DEBOUNCE_MS)

    def _do_scrubber_preview(self) -> None:
        t = getattr(self, "_scrubber_t", None)
        if t is None or not self.video_path:
            return
        if self._frame_worker and self._frame_worker.isRunning():
            self._scrubber_timer.start(_BUSY_RETRY_MS)
            return
        self._frame_worker = FrameExtractWorker(self.lrf_path or self.video_path, t)
        self._frame_worker.done.connect(self._on_scrubber_frame_ready)
        self._frame_worker.failed.connect(
            lambda m: self.preview_label.setText("Błąd podglądu klatki:\n" + m))
        self._frame_worker.start()

    def _on_scrubber_frame_ready(self, frame: Image.Image, t: float) -> None:
        """Klatka scrubber gotowa → nałóż panel aktywny dla czasu t."""
        try:
            session = self.session or self._safe_session()
            if session is None or not session.shots:
                self._show_image(frame)
                return
            style = self.current_style()
            mode = self._anchor_mode()
            pstyle = self._scaled_style(style, frame.size[1])
            t0 = audio_sync.resolve_t0(self.t0_spin.value(), mode, session.shots[0].czas)
            duration = self.waveform.duration or (t + 10)
            events = render.build_events(session, t0, pstyle, frame.size, duration)
            composite = frame.copy()
            for ev in events:
                if ev.start <= t < ev.end:
                    panel = ev.image
                    if ev.centered:
                        x = (frame.size[0] - panel.size[0]) // 2
                        y = (frame.size[1] - panel.size[1]) // 2
                    else:
                        x, y = overlay.panel_origin(panel.size, frame.size, pstyle)
                    composite.alpha_composite(panel, (x, y))
                    break
            if style.show_running_clock and t >= t0 - 1e-6:
                self._composite_clock(composite, pstyle, session, t - t0)
            self._show_image(composite)
        except Exception:  # noqa: BLE001
            _log_ui_error("scrubber")
            self._show_image(frame)

    def _request_frame(self):
        """Kotwica się zmieniła → wyciągnij nową klatkę w tle (debounce)."""
        self._preview_timer.start(_FRAME_DEBOUNCE_MS)

    def _do_request_frame(self):
        """Uruchamiane przez timer — startuje workera jeśli nie ma aktywnego."""
        if not self.video_path:
            return
        anchor_t = max(0.0, self.t0_spin.value())
        if (self._frame_worker and self._frame_worker.isRunning()):
            if abs(self._frame_worker.anchor_t - anchor_t) < 0.01:
                return  # ten sam timestamp, poczekaj na wynik
            self._preview_timer.start(_BUSY_RETRY_MS)  # inny czas — retry gdy worker skończy
            return
        self._frame_worker = FrameExtractWorker(self.lrf_path or self.video_path, anchor_t)
        self._frame_worker.done.connect(self._on_frame_ready)
        self._frame_worker.failed.connect(
            lambda m: self.preview_label.setText("Błąd podglądu klatki:\n" + m))
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
                # Brak strzałów (np. zaraz po wczytaniu, pusty timeline) — pokaż
                # samą klatkę, żeby podgląd nie wisiał na komunikacie ładowania.
                self._show_image(self._cached_frame.copy())
                return
            style = self.current_style()
            mode = self._anchor_mode()
            frame = self._cached_frame.copy()
            # Skaluj offsety do rozdzielczości podglądu — podgląd ≈ render (WYSIWYG).
            pstyle = self._scaled_style(style, frame.size[1])
            self._preview_rects = {}
            edit = self.edit_pos_btn.isChecked()
            # W trybie edycji pokazujemy panel strzału (zamiast planszy START), by
            # dało się go przeciągać; plansza START i tak jest wyśrodkowana.
            if mode == AnchorMode.START_SIGNAL and not edit:
                panel = overlay.render_start_banner(pstyle, frame.size)
                x = (frame.size[0] - panel.size[0]) // 2
                y = (frame.size[1] - panel.size[1]) // 2
            else:
                # Stały rozmiar panelu (jak w renderze) — podgląd nie „pulsuje".
                shot_fixed = overlay.shot_panel_max_size(session, pstyle, frame.size)
                panel = overlay.render_shot_panel(session, 0, pstyle, frame.size, shot_fixed)
                x, y = overlay.panel_origin(panel.size, frame.size, pstyle)
                self._preview_rects["panel"] = (x, y, panel.size[0], panel.size[1])
            frame.alpha_composite(panel, (x, y))
            if style.show_running_clock:
                elapsed = (session.shots[0].czas
                           if (mode != AnchorMode.START_SIGNAL or edit) else 0.0)
                self._composite_clock(frame, pstyle, session, elapsed)
            self._show_image(frame)
        except Exception:  # noqa: BLE001
            # Bez modala (podgląd odświeża się przy każdej zmianie stylu), ale ze
            # śladem — ciche połykanie maskowało błędy kompozycji nakładek.
            _log_ui_error("podgląd")
        self._autosave_timer.start(_STYLE_AUTOSAVE_MS)

    def _preview_scale(self, frame_h: int) -> float:
        """Współczynnik klatka_podglądu / wideo (do skalowania offsetów). 1.0 gdy brak."""
        if self._video_size and self._video_size[1] > 0:
            return frame_h / self._video_size[1]
        return 1.0

    def _scaled_style(self, style, frame_h: int):
        """Kopia stylu z offsetami przeskalowanymi do rozdzielczości podglądu."""
        s = self._preview_scale(frame_h)
        if s == 1.0:
            return style
        return replace(
            style,
            offset_x=int(round(style.offset_x * s)),
            offset_y=int(round(style.offset_y * s)),
            clock_offset_x=int(round(style.clock_offset_x * s)),
            clock_offset_y=int(round(style.clock_offset_y * s)),
        )

    def _composite_clock(self, frame, style, session, elapsed: float) -> None:
        """Nakłada panel płynącego zegara na klatkę podglądu — pozycja i STAŁY rozmiar
        jak w renderze (auto = nad panelem strzału, albo niezależny róg + offset zegara)."""
        # Stały rozmiar = max przy ostatnim strzale (najwięcej cyfr) — bez pulsowania.
        max_elapsed = session.shots[-1].czas if session.shots else elapsed
        clock_fixed = overlay.clock_panel_max_size(style, frame.size, max_elapsed)
        clock = overlay.render_clock_panel(style, frame.size, elapsed, clock_fixed)
        if style.clock_position == "auto":
            shot_fixed = overlay.shot_panel_max_size(session, style, frame.size)
            ref_h = shot_fixed[1]
            gap = render._clock_gap(frame.size, style)
            xy = render._clock_xy(style, frame.size, clock.size, ref_h, gap)
        else:
            xy = render._clock_xy(style, frame.size, clock.size, 0, 0)
        frame.alpha_composite(clock, xy)
        self._preview_rects["clock"] = (xy[0], xy[1], clock.size[0], clock.size[1])

    # --- edycja pozycji nakładek przez przeciąganie w podglądzie ---
    def _on_edit_pos_toggled(self, on: bool) -> None:
        self.preview_label.edit_mode = on
        self.preview_label.setCursor(Qt.OpenHandCursor if on else Qt.ArrowCursor)
        self._grab = None
        if on:
            self.statusBar().showMessage(
                "Tryb edycji pozycji: przeciągnij panel strzału lub zegar w podglądzie.", 6000)
        self._update_preview()

    @staticmethod
    def _invert_offset(position: str, topleft, panel_size, video_size):
        """Z lewego-górnego rogu (px) → offset (px) względem kotwicy (odwrotność panel_origin).
        Zwraca (ox, oy, horiz) — ox=None gdy poziom = center (offset nieużywany)."""
        x, y = topleft
        pw, ph = panel_size
        vw, vh = video_size
        vert, _, horiz = position.partition("-")
        if horiz == "left":
            ox = max(0, x)
        elif horiz == "right":
            ox = max(0, vw - pw - x)
        else:  # center — offset X nieużywany
            ox = None
        oy = max(0, y) if vert == "top" else max(0, vh - ph - y)
        return ox, oy, horiz

    def _on_preview_grab(self, fx: float, fy: float) -> None:
        # Zegar rysowany na wierzchu → ma priorytet w trafieniu.
        for key in ("clock", "panel"):
            r = self._preview_rects.get(key)
            if r and r[0] <= fx <= r[0] + r[2] and r[1] <= fy <= r[1] + r[3]:
                self._grab = {"key": key, "fx": fx, "fy": fy,
                              "x0": r[0], "y0": r[1], "w": r[2], "h": r[3]}
                self.preview_label.setCursor(Qt.ClosedHandCursor)
                return
        self._grab = None

    def _on_preview_drag(self, fx: float, fy: float) -> None:
        if not self._grab or self._cached_frame is None:
            return
        g = self._grab
        fw, fh = self._cached_frame.size
        nx = max(0, min(g["x0"] + (fx - g["fx"]), fw - g["w"]))
        ny = max(0, min(g["y0"] + (fy - g["fy"]), fh - g["h"]))
        scale = self._preview_scale(fh) or 1.0
        if g["key"] == "panel":
            pos = self.pos_combo.currentText()
            ox, oy, _ = self._invert_offset(pos, (nx, ny), (g["w"], g["h"]), (fw, fh))
            if ox is not None:
                self.off_x.setValue(int(round(ox / scale)))
            self.off_y.setValue(int(round(oy / scale)))
        else:  # zegar
            cp = self.clock_pos_combo.currentData()
            if cp == "auto":
                # Przeciąganie wymaga konkretnego rogu — przejdź na róg panelu.
                cp = self.pos_combo.currentText()
                cidx = self.clock_pos_combo.findData(cp)
                if cidx >= 0:
                    self.clock_pos_combo.setCurrentIndex(cidx)
            ox, oy, _ = self._invert_offset(cp, (nx, ny), (g["w"], g["h"]), (fw, fh))
            if ox is not None:
                self.clock_off_x.setValue(int(round(ox / scale)))
            self.clock_off_y.setValue(int(round(oy / scale)))

    def _on_preview_drop(self) -> None:
        self._grab = None
        if self.edit_pos_btn.isChecked():
            self.preview_label.setCursor(Qt.OpenHandCursor)

    def _safe_session(self):
        try:
            return self._build_session()
        except Exception:  # noqa: BLE001
            return None

    def _show_image(self, pil_img):
        img = pil_img.convert("RGBA")
        fw, fh = img.size
        qim = ImageQt(img)
        lbl = self.preview_label.size()
        pix = QPixmap.fromImage(QImage(qim)).scaled(
            lbl, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview_label.setPixmap(pix)
        # Geometria wyświetlanego (wyśrodkowanego) obrazka — do mapowania myszy w edycji.
        dx = (lbl.width() - pix.width()) // 2
        dy = (lbl.height() - pix.height()) // 2
        self.preview_label.set_frame_geometry(QRect(dx, dy, pix.width(), pix.height()), (fw, fh))

    def _collect_render_kwargs(self) -> dict | None:
        if not self.video_path:
            QMessageBox.warning(self, "Brak wideo", "Wybierz plik wideo."); return None
        if not self.out_edit.text():
            QMessageBox.warning(self, "Brak wyjścia", "Podaj plik wyjściowy."); return None
        no_overlay = self.no_overlay_chk.isChecked()
        if no_overlay and self.format_combo.currentData() != "mp4":
            # Jak w wersji WWW: trim_video koduje H.264+AAC (faststart) —
            # w kontenerze WebM/GIF dałoby to uszkodzony plik.
            QMessageBox.warning(
                self, "Bez nakładki",
                "Tryb „bez nakładki” (samo przycięcie) obsługuje tylko format MP4 — "
                "zmień format wyjściowy.")
            return None
        if no_overlay:
            # „Bez nakładki" = samo przycięcie: oś czasu strzałów jest zbędna.
            # Nie wołamy _build_session() (pusty tekst rzuca TimelineParseError,
            # a źródło ID robiłoby zbędny strzał do API) — bierzemy sesję już
            # pobraną wcześniej, jeśli jest (trafia tylko do zapisu kolejki).
            session = self.session
        else:
            try:
                session = self._build_session()
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "Błąd danych", str(exc)); return None
        mode = self._anchor_mode()
        if session is not None and session.shots:
            t0 = audio_sync.resolve_t0(self.t0_spin.value(), mode, session.shots[0].czas)
        else:
            t0 = self.t0_spin.value()
        ts = self.trim_start_spin.value()
        te = self.trim_end_spin.value()
        return dict(
            video_path=self.video_path, session=session, t0=t0,
            style=self.current_style(), mode=mode, out_path=self.out_edit.text(),
            trim_start=ts if ts > 0 else None,
            trim_end=te if te > 0 else None,
            encoder="auto" if self.gpu_chk.isChecked() else "cpu",
            no_overlay=no_overlay,
            output_format=self.format_combo.currentData(),
        )

    # --- zapamiętywanie ustawień per-plik ---
    def _collect_file_settings(self) -> dict:
        """Komplet parametrów aktualnego pliku do zapisu w AppData."""
        return {
            "style": self.current_style().to_dict(),
            "source": "id" if self.rb_id.isChecked() else "text",
            "id": self.id_spin.value(),
            "timeline": self.timeline_edit.toPlainText(),
            "anchor": self._anchor_mode().value,
            "t0": self.t0_spin.value(),
            "trim_start": self.trim_start_spin.value(),
            "trim_end": self.trim_end_spin.value(),
            "tail": self.tail_spin.value(),
            "gpu": self.gpu_chk.isChecked(),
            "no_overlay": self.no_overlay_chk.isChecked(),
            "format": self.format_combo.currentData(),
            "output": self.out_edit.text(),
        }

    def _apply_file_settings(self, data: dict) -> None:
        """Przywraca parametry pliku zapisane przy poprzednim renderze/kolejce.

        Wywoływane po analizie audio (spiny czasu mają już poprawny zakres)."""
        try:
            style = OverlayStyle.from_dict(data["style"])
            self._apply_style(style)  # ustawia też język, zegar, planszę START
        except Exception:  # noqa: BLE001
            pass
        if data.get("source") == "text":
            self.rb_text.setChecked(True)
        else:
            self.rb_id.setChecked(True)
        if data.get("id"):
            self.id_spin.setValue(int(data["id"]))
        if data.get("timeline"):
            self.timeline_edit.setPlainText(data["timeline"])
        aidx = self.anchor_combo.findData(data.get("anchor", AnchorMode.START_SIGNAL.value))
        if aidx >= 0:
            self.anchor_combo.setCurrentIndex(aidx)
        self.t0_spin.setValue(float(data.get("t0", 0.0)))
        self.trim_start_spin.setValue(float(data.get("trim_start", 0.0)))
        self.trim_end_spin.setValue(float(data.get("trim_end", 0.0)))
        self.tail_spin.setValue(float(data.get("tail", _TRIM_TAIL_S)))
        self.gpu_chk.setChecked(bool(data.get("gpu", True)))
        self.no_overlay_chk.setChecked(bool(data.get("no_overlay", False)))
        fidx = self.format_combo.findData(data.get("format", "mp4"))
        if fidx >= 0:
            self.format_combo.setCurrentIndex(fidx)
        if data.get("output"):
            self.out_edit.setText(data["output"])
        # Źródło = ID → pobierz dane z API od razu (cicho), żeby metadane toru/
        # zawodnika i oś czasu były gotowe bez ręcznego „Pobierz".
        if data.get("source") == "id" and data.get("id"):
            self._fetch_id(silent=True)
        self._update_preview()

    def _save_file_settings(self) -> None:
        """Zapisuje parametry bieżącego pliku do AppData (cicho — błąd nie blokuje renderu)."""
        if not self.video_path:
            return
        try:
            config.save_file_settings(self.video_path, self._collect_file_settings())
        except Exception:  # noqa: BLE001
            pass

    def _build_cli_command(self) -> str:
        """Buduje równoważne wywołanie CLI (PiroOverlay.exe …) z bieżących ustawień.

        Odwzorowuje to, co CLI obsługuje: wideo, źródło osi, T0, kotwicę, język,
        przycięcie, enkoder, zegar oraz tryb „bez nakładki”. Szczegóły wyglądu
        nakładki (kolory, skala, pozycja panelu, offsety, plansza START) nie mają
        odpowiedników w CLI i są pomijane (patrz nota w oknie)."""
        parts = ["PiroOverlay.exe"]
        video = self.video_edit.text() or (self.video_path or "<wideo>")
        parts += ["--video", _cli_quote(video)]

        no_overlay = self.no_overlay_chk.isChecked()
        if not no_overlay:
            if self.rb_id.isChecked():
                parts += ["--id", str(self.id_spin.value())]
            else:
                tl = self.timeline_edit.toPlainText().strip()
                if tl:
                    parts += ["--timeline", _cli_quote(tl)]

        mode = self._anchor_mode()
        if mode != AnchorMode.START_SIGNAL:
            parts += ["--anchor", mode.value]
        t0 = self.t0_spin.value()
        if t0 > 0:
            parts += ["--t0", _fmt_num(t0)]

        lang = self.lang_combo.currentData()
        if lang != Lang.PL:
            parts += ["--lang", lang.value]

        ts = self.trim_start_spin.value()
        te = self.trim_end_spin.value()
        if ts > 0:
            parts += ["--trim-start", _fmt_num(ts)]
        if te > 0:
            parts += ["--trim-end", _fmt_num(te)]

        if not self.gpu_chk.isChecked():
            parts += ["--encoder", "cpu"]

        if no_overlay:
            parts += ["--no-overlay"]
        else:
            style = self.current_style()
            if style.show_running_clock:
                parts += ["--clock"]
                if style.clock_position != "auto":
                    parts += ["--clock-position", style.clock_position]
                    if style.clock_offset_x != _DEFAULT_OFFSET_PX:
                        parts += ["--clock-offset-x", str(style.clock_offset_x)]
                    if style.clock_offset_y != _DEFAULT_OFFSET_PX:
                        parts += ["--clock-offset-y", str(style.clock_offset_y)]

        out = self.out_edit.text()
        if out:
            parts += ["-o", _cli_quote(out)]
        return " ".join(parts)

    def _show_cli_command(self):
        cmd = self._build_cli_command()
        dlg = QDialog(self)
        dlg.setWindowTitle("Komenda CLI (bieżące ustawienia)")
        dlg.setMinimumWidth(660)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Równoważne wywołanie bezgłowe PiroOverlay.exe:"))
        text = QPlainTextEdit(cmd)
        text.setReadOnly(True)
        text.setMaximumHeight(120)
        text.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        lay.addWidget(text)
        note = QLabel(
            "Uwaga: CLI odwzorowuje wideo, źródło osi (ID/tekst), T0, kotwicę, język,\n"
            "przycięcie, enkoder, płynący zegar i tryb „bez nakładki”. Szczegóły wyglądu\n"
            "nakładki (kolory, skala, pozycja panelu, offsety, plansza START) NIE są\n"
            "obsługiwane w CLI i zostały pominięte.")
        note.setStyleSheet("color:#aaaaaa;")
        note.setWordWrap(True)
        lay.addWidget(note)
        btns = QHBoxLayout()
        copy_btn = QPushButton("Kopiuj do schowka")
        copy_btn.clicked.connect(
            lambda: (QApplication.clipboard().setText(cmd),
                     self.statusBar().showMessage("Skopiowano komendę CLI do schowka.", 4000)))
        close_btn = QPushButton("Zamknij")
        close_btn.clicked.connect(dlg.accept)
        btns.addStretch(1); btns.addWidget(copy_btn); btns.addWidget(close_btn)
        lay.addLayout(btns)
        dlg.exec()

    def _start_render(self):
        if self._render_busy:
            QMessageBox.warning(self, "Zajęty",
                                "Render jest już w toku (kolejka lub bezpośredni)."); return
        kwargs = self._collect_render_kwargs()
        if kwargs is None:
            return
        self._save_file_settings()  # zapamiętaj parametry tego pliku
        self._render_busy = True
        self.render_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.open_btn.setVisible(False)  # pokaż dopiero po udanym renderze
        self.worker = RenderWorker(kwargs)
        self._used_encoder = None
        self._render_warn = None
        self.worker.progress.connect(lambda p: self.progress.setValue(int(p * 100)))
        self.worker.encoder_used.connect(self._on_encoder_used)
        self.worker.warn.connect(self._on_warn)
        self.worker.finished_ok.connect(self._on_done)
        self.worker.failed.connect(self._on_fail)
        self.worker.cancelled.connect(self._on_cancelled)
        self.worker.start()

    def _cancel_render(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.cancel_btn.setEnabled(False)
            self.cancel_btn.setText("Zatrzymywanie…")

    def _reset_render_ui(self) -> None:
        """Przywraca przyciski renderu po zakończeniu (sukces/błąd/anulowanie)."""
        self._render_busy = False
        self.render_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("Zatrzymaj")

    def _on_cancelled(self):
        self._reset_render_ui()
        self.progress.setValue(0)
        QMessageBox.information(self, "Zatrzymano", "Renderowanie zostało przerwane.")

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

    def _on_format_changed(self, *_):
        """Aktualizuje rozszerzenie pliku wyjściowego gdy zmienia się format."""
        current = self.out_edit.text()
        if not current:
            return
        p = Path(current)
        fmt = self.format_combo.currentData()
        new_ext = _FORMAT_EXT.get(fmt, ".mp4")
        # Zamień obecne rozszerzenie tylko jeśli jest znane (mp4/webm/gif/mov/avi/mkv).
        if p.suffix.lower() in (".mp4", ".webm", ".gif", ".mov", ".avi", ".mkv"):
            self.out_edit.setText(str(p.with_suffix(new_ext)))

    def _on_no_overlay_toggled(self, state):
        self.appearance_box.setDisabled(bool(state))

    def _on_done(self, path: str):
        self._reset_render_ui()
        self.last_output = path
        self.open_btn.setVisible(True)
        self.open_btn.setEnabled(True)
        enc = {"h264_nvenc": "GPU (NVENC)", "libx264": "CPU (x264)"}.get(self._used_encoder, "")
        msg = f"Zapisano:\n{path}"
        if enc:
            msg += f"\n\nEnkoder: {enc}"
        if self._render_warn:
            msg += f"\n\n⚠ {self._render_warn}"
        QMessageBox.information(self, "Gotowe", msg)

    def _on_fail(self, msg: str):
        self._reset_render_ui()
        QMessageBox.critical(self, "Błąd renderowania", msg)

    def _add_to_queue(self):
        kwargs = self._collect_render_kwargs()
        if kwargs is None:
            return
        self._save_file_settings()  # zapamiętaj parametry tego pliku
        job = RenderJob(
            id=uuid.uuid4().hex,
            label=f"{Path(str(kwargs['video_path'])).name} → {Path(str(kwargs['out_path'])).name}",
            kwargs=kwargs,
        )
        win = self._get_queue_window()
        win.add_job(job)
        win.show()
        win.raise_()

    def _show_queue_window(self):
        win = self._get_queue_window()
        win.show()
        win.raise_()

    def _show_batch_window(self):
        # Współdziel runner/okno kolejki — wsad tylko dokłada do nich zadania.
        queue_win = self._get_queue_window()
        if self._batch_window is None:
            self._batch_window = BatchDialog(
                self._queue_runner, queue_win, self.current_style(), parent=None)
        else:
            # odśwież wspólny styl (mógł się zmienić w głównym oknie)
            self._batch_window._base_style = self.current_style()
            self._batch_window._clock_chk.setChecked(
                self.current_style().show_running_clock)
        self._batch_window.show()
        self._batch_window.raise_()

    def _get_queue_window(self) -> RenderQueueWindow:
        if self._queue_window is None:
            runner = RenderQueueRunner(
                get_busy=lambda: self._render_busy,
                set_busy=lambda v: setattr(self, "_render_busy", v),
                parallel=config.load_queue_parallel(),
            )
            self._queue_runner = runner
            runner.queue_finished.connect(
                lambda: self.render_btn.setEnabled(True)
            )
            self._queue_window = RenderQueueWindow(runner, parent=None)
        return self._queue_window

    def closeEvent(self, event):
        # Zapisz ustawienia bieżącego pliku (np. wpisane ID z API), by były przy
        # następnym otwarciu — nawet bez renderu/kolejki.
        if self.video_path and self._file_settings_ready:
            self._save_file_settings()
        # Przerwij bezpośredni render, by nie niszczyć działającego QThread.
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(_THREAD_JOIN_MS)
        if self._queue_runner is not None and self._queue_runner._running:
            self._queue_runner.stop()  # pauzuje kolejkę + ubija biegnące rendery
            for w in self._queue_runner.active_workers():
                w.wait(_THREAD_JOIN_MS)
        # Poczekaj na workery przygotowania wsadu (QThread niszczony w trakcie = crash).
        if self._batch_window is not None:
            for worker in list(self._batch_window._workers.values()):
                worker.wait(_THREAD_JOIN_MS)
        event.accept()

    def _open_output_folder(self):
        """Otwiera folder z wynikiem; na Windows zaznacza plik w eksploratorze."""
        if not self.last_output:
            return
        path = Path(self.last_output)
        if sys.platform == "win32" and path.exists():
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


# ----------------------------- autoaktualizacja -----------------------------
_RELEASES_API = "https://api.github.com/repos/enclude/congenial-octo-memory/releases/latest"
_RELEASES_PAGE = "https://github.com/enclude/congenial-octo-memory/releases/latest"


class UpdateChecker(QThread):
    update_available = Signal(str)  # nowa wersja

    def run(self):
        try:
            req = urllib.request.Request(
                _RELEASES_API, headers={"User-Agent": f"PiroOverlay/{__version__}"},
                method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            tag = data.get("tag_name", "")
            remote = tag.lstrip("v")
            if remote and remote != __version__ and _is_newer(remote, __version__):
                self.update_available.emit(remote)
        except Exception:  # noqa: BLE001 — brak sieci lub błąd API: ignoruj cicho
            pass


def _is_newer(remote: str, local: str) -> bool:
    """Zwraca True gdy remote > local (porównanie semver po liczbach)."""
    def parts(v):
        try:
            return tuple(int(x) for x in v.split(".")[:3])
        except ValueError:
            return (0,)
    return parts(remote) > parts(local)


def _show_update_dialog(parent, new_version: str) -> None:
    box = QMessageBox(parent)
    box.setWindowTitle("Dostępna aktualizacja")
    box.setIcon(QMessageBox.Information)
    box.setText(
        f"Dostępna jest nowa wersja <b>v{new_version}</b> "
        f"(aktualna: v{__version__}).<br><br>"
        f"Pobierz ze strony projektu."
    )
    download_btn = box.addButton("Pobierz", QMessageBox.AcceptRole)
    box.addButton("Pomiń", QMessageBox.RejectRole)
    box.exec()
    if box.clickedButton() == download_btn:
        QDesktopServices.openUrl(QUrl(_RELEASES_PAGE))


# ----------------------------- helpery -----------------------------
def _log_ui_error(context: str) -> None:
    """Ślad cichych wyjątków UI (podgląd, scrubber) w crash_log.txt — bez modala.

    Podgląd odświeża się przy każdej zmianie stylu, więc okno błędu byłoby spamem,
    ale całkiem ciche połykanie maskowało błędy kompozycji nakładek."""
    try:
        path = config.config_dir() / "crash_log.txt"
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n=== Wyjątek UI ({context}) ===\n")
            traceback.print_exc(file=f)
    except Exception:  # noqa: BLE001
        pass


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


def _cli_quote(s: str) -> str:
    """Otacza wartość cudzysłowem, gdy zawiera spację/cudzysłów (do wklejenia w shellu)."""
    s = str(s)
    if not s:
        return '""'
    if any(c in s for c in ' \t"'):
        return '"' + s.replace('"', r'\"') + '"'
    return s


def _fmt_num(v: float) -> str:
    """Liczba bez zbędnych zer końcowych (3.20 → 3.2, 5.00 → 5)."""
    return f"{v:.3f}".rstrip("0").rstrip(".")


class WheelGuard(QObject):
    """Globalny filtr zdarzeń: kółko myszy NIE zmienia wartości ŻADNEGO pola
    (spinbox/combo). Zamiast zmieniać wartość, przewijanie jest przekazywane do
    najbliższego `QScrollArea` (gdy pole leży w obszarze przewijanym), więc strona
    nadal przewija się pod kursorem — tylko wartość pola pozostaje nietknięta.

    Instalowany na `QApplication`, więc obejmuje pola we wszystkich oknach (główne,
    kolejka, wsad, dialogi) — także te tworzone później.
    """
    _GUARDED = (QAbstractSpinBox, QComboBox)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel and isinstance(obj, self._GUARDED):
            area = obj.parentWidget()
            while area is not None and not isinstance(area, QScrollArea):
                area = area.parentWidget()
            if area is not None:
                # przekaż przewijanie do obszaru (viewport nie jest polem → przewinie)
                QApplication.sendEvent(area.viewport(), event)
            return True   # zablokuj zmianę wartości pola
        return False


_crash_log_file = None  # utrzymuje otwarty uchwyt dla faulthandler (GC by go zamknął)


def _install_crash_logging() -> None:
    """Zapisuje twarde crashe i nieobsłużone wyjątki do AppData.

    `faulthandler` zrzuca stos WSZYSTKICH wątków przy natywnym crashu (segfault,
    `abort()` z „QThread: Destroyed while thread is still running") — inaczej
    aplikacja po prostu znika bez śladu. `sys.excepthook`/`threading.excepthook`
    łapią wyjątki Pythona. Wszystko ląduje w `crash_log.txt` obok `render_log.txt`."""
    global _crash_log_file
    try:
        import threading
        path = config.config_dir() / "crash_log.txt"
        _crash_log_file = open(path, "a", encoding="utf-8", buffering=1)
        faulthandler.enable(file=_crash_log_file, all_threads=True)

        def _log_exc(kind, exc, tb):
            try:
                _crash_log_file.write("\n=== Nieobsłużony wyjątek ===\n")
                traceback.print_exception(kind, exc, tb, file=_crash_log_file)
                _crash_log_file.flush()
            except Exception:  # noqa: BLE001
                pass

        sys.excepthook = lambda k, e, t: (_log_exc(k, e, t),
                                          sys.__excepthook__(k, e, t))
        if hasattr(threading, "excepthook"):
            threading.excepthook = lambda a: _log_exc(a.exc_type, a.exc_value,
                                                      a.exc_traceback)
    except Exception:  # noqa: BLE001
        pass


def main():
    _install_crash_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("PiroOverlay")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(QIcon(resources.icon_path()))
    app._wheel_guard = WheelGuard(app)   # referencja, by filtr nie zniknął (GC)
    app.installEventFilter(app._wheel_guard)
    win = MainWindow()
    win.resize(1180, 760)
    win.show()

    checker = UpdateChecker()
    checker.update_available.connect(lambda v: _show_update_dialog(win, v))
    checker.start()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
