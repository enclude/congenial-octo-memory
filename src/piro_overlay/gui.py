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
import os
import re
import subprocess
import sys
import tempfile
import time
import traceback
import unicodedata
import uuid
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from functools import partial
from pathlib import Path
from typing import Callable

import urllib.request
import json

from PySide6.QtCore import (
    QEvent, QLocale, QObject, QPoint, QPointF, QRect, QRectF, QSettings, QSize, QSizeF, Qt,
    QThread, QTimer, QUrl, Signal,
)
from PySide6.QtGui import (
    QAction, QColor, QDesktopServices, QFontMetrics, QIcon, QImage, QKeySequence,
    QPainter, QPainterPath, QPen, QPixmap, QPolygon, QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractSpinBox, QApplication, QComboBox, QCheckBox,
    QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGraphicsPixmapItem,
    QGraphicsScene, QGraphicsView, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QListWidget, QListWidgetItem,
    QScrollArea, QSizePolicy, QSpinBox, QSplitter, QStackedWidget, QPlainTextEdit,
    QStatusBar, QToolBar, QToolButton, QVBoxLayout, QWidget,
)

# Podgląd w ruchu jest DODATKIEM: gdy backendu multimediów brak (okrojony bundle,
# egzotyczna dystrybucja Qt), aplikacja działa dalej na podglądzie statycznym.
try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
    _HAS_MULTIMEDIA = True
except Exception:  # noqa: BLE001
    _HAS_MULTIMEDIA = False

from PIL import Image
from PIL.ImageQt import ImageQt

from . import (__version__, api, audio_sync, config, ffmpeg, overlay, pipeline,
              preview, render, resources)
from .i18n import get_translator
from .models import ANCHOR_POSITIONS, AnchorMode, Lang, OverlayStyle, Session, Shot
from .parser import delete_shot, format_timeline, move_shot, parse_timeline
from . import ui_theme
from .ui_theme import (
    RADIUS, SPACING, apply_theme, current_tokens, load_app_fonts, repolish, restore_window_state,
    make_font, save_window_state, set_app_user_model_id, set_windows_dark_titlebar,
    setup_hidpi,
)
from .ui_widgets import (
    ColorSwatchButton, FormSection, InlineMessage, PathField, SectionHeader,
    SegmentedControl, StatusDot,
    _focus_ring, set_busy, set_kind, set_role, status_message,
)

# GUI jest po polsku — teksty nowych elementów (pasek akcji, sekcje, pozycje)
# idą przez istniejący mechanizm i18n, żeby nie powstał drugi słownik.
_TR = get_translator(Lang.PL)
SITE_URL = "https://shothud.com"     # strona projektu (marka ShotHUD)

PREVIEW_HEIGHT = 360  # obniżona jakość podglądu — szybciej i lżej dla dużych plików
_HANDLE_PX = 8        # tolerancja trafienia uchwytu przycięcia (px)
_AXIS_H = 22          # wysokość paska osi czasu (px)
_TAG_H = 16           # wysokość pastylki etykiety markera (px)
_SHOT_HIT_PX = 4      # tolerancja trafienia markera strzału (px logiczne)

_FORMAT_EXT = {"mp4": ".mp4", "webm": ".webm", "gif": ".gif"}  # format → rozszerzenie
_SESSION_ID_MAX = 10_000_000   # górny zakres ID sesji API (główne okno i wsad)
_DEFAULT_OFFSET_PX = 32        # domyślny offset panelu/zegara — musi zgadzać się
                               # z pominięciami w _build_cli_command (krótsza komenda)
_LEAD_IN_S = 5.0               # sekundy przed T0 przy auto-przycięciu
_VIDEO_FILTER = "Wideo (*.mp4 *.mov *.mkv *.avi)"
_TRIM_TAIL_S = 5.0             # margines po ostatnim strzale przy auto-przycięciu
_IMPORT_TAIL_S = 75.0          # okno po T0 przy detekcji po imporcie (brak osi czasu)
_THREAD_JOIN_MS = 3000         # limit oczekiwania na wątki robocze przy zamykaniu
_FRAME_DEBOUNCE_MS = 250       # debounce ekstrakcji klatki po zmianie kotwicy
_SCRUBBER_DEBOUNCE_MS = 200    # debounce podglądu Ctrl+klik na waveformie
_BUSY_RETRY_MS = 150           # ponowna próba, gdy worker klatki jeszcze pracuje
_PROXY_RETRY_MS = 1000         # odpytywanie „czy można już zbudować proxy podglądu"
_T0_RECHECK_RETRY_MS = 1500    # jw. dla ponownej detekcji T0 z pamięci pliku
_PLAY_RESUME_MS = 200          # kontrola pozycji tuż po starcie odtwarzania
_PLAY_RESUME_TOL_S = 1.0       # większa rozbieżność = backend zgubił przewinięcie
_STYLE_AUTOSAVE_MS = 1000      # debounce autozapisu stylu na dysk
# Wysokość płótna nakładek playera. Panele rysujemy RAZ na przebudowę w tej
# rozdzielczości (nie w 4K) — obraz i tak jest skalowany do widoku, a Pillow
# nie musi rysować pikseli, których nikt nie zobaczy.
_PLAYER_OVERLAY_H = 540
_SEEK_STEP_S = 1.0             # J/L i przyciski „◀ 1 s” / „1 s ▶”
_DEFAULT_FRAME_MS = 40         # krok klatki, gdy fps nagrania nieznany (25 fps)
_PLAYER_REBUILD_MS = 200       # debounce przebudowy nakładek podglądu w ruchu
_SEEK_VERIFY_MS = 150          # kontrola nakładek po przewinięciu w pauzie
_FRAME_STALE_S = 0.5           # klatka starsza od pozycji o tyle = sprzed seeku
_CLOCK_CACHE_MAX = 1200        # pixmapy zegara (co 0.1 s) trzymane między klatkami

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


def _dec_sep() -> str:
    """Separator dziesiętny UI — ten sam, którego używają spinboxy (QLocale systemu)."""
    try:
        return str(QLocale().decimalPoint())
    except Exception:  # noqa: BLE001 — brak QApplication (import w testach)
        return "."


def _fmt_axis_time(t: float) -> str:
    """Etykieta czasu na osi: 's' dla < 60 s, 'M:SS' dla dłuższych nagrań.

    JEDYNY format czasu w UI osi/pastylek/paska podglądu — separator dziesiętny
    bierzemy z locale, żeby oś i spinboxy nie pokazywały dwóch różnych („37.6s"
    obok „37,60 s" to anty-wzorzec 6 ze skilla).
    """
    if t < 60:
        # :g usuwa zbędne zera (0.10 → 0.1, 1.00 → 1)
        label = f"{t:g}s"
    else:
        m, s = divmod(int(round(t)), 60)
        label = f"{m}:{s:02d}"
    return label.replace(".", _dec_sep())


def _fmt_time_s(v: float) -> str:
    """Sekundy w komunikatach UI — jak `_fmt_num`, ale z separatorem z locale."""
    return _fmt_num(v).replace(".", _dec_sep())


def _nice_tick_step(span: float, width: int, target_px: int = 100) -> float:
    """Dobiera krok głównych kresek tak, by etykiety były co ~target_px pikseli."""
    if span <= 0 or width <= 0:
        return 1.0
    raw = target_px * span / width
    for step in _TICK_STEPS:
        if step >= raw - 1e-9:
            return step
    return _TICK_STEPS[-1]


def _apply_icon(btn: QAbstractButton, name: str, size: int = 16,
                 fallback_text: str | None = None) -> None:
    """`btn.setIcon(ui_theme.icon(name, size=size))` with a text/glyph fallback.

    Bez zestawu SVG (`Qt6Svg` brak w bundlu, albo plik ikony nie istnieje)
    `ui_theme.icon` zwraca pusty `QIcon` — bez tego fallbacku przycisk
    icon-only (transport, „Dopasuj”/„Zoom Od–Do”, ✕/▶ w kolejce/wsadzie)
    zostałby CAŁKOWICIE pusty. `fallback_text` przywraca stary glif/tekst i
    (dla `QToolButton`) przełącza styl na `ToolButtonTextOnly`, żeby coś było
    widać. `ensure_svg_support()` nie zmienia się w trakcie działania procesu,
    więc to jednorazowa decyzja — nie trzeba cofać przełączenia stylu.
    """
    ic = ui_theme.icon(name, size=size)
    btn.setIcon(ic)
    if ic.isNull() and fallback_text is not None:
        btn.setText(fallback_text)
        if isinstance(btn, QToolButton):
            btn.setToolButtonStyle(Qt.ToolButtonTextOnly)


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


class FuncWorker(QThread):
    """Dowolne wywołanie domenowe (detekcja, API) w wątku — UI nie zamiera.

    Jeden worker na WSZYSTKIE długie operacje okna głównego: detekcja bzyczka,
    kotwicy, ID z audio i pobranie sesji z API. Argumenty domykaj przez
    `functools.partial` — worker woła po prostu `fn()`.

    `gen` to token pokolenia: handler odrzuca wyniki operacji anulowanej albo
    starszej niż bieżący plik (patrz `MainWindow._op_gen`).

    UWAGA (pułapka z CLAUDE.md): pola NIE mogą nazywać się `start`/`end` —
    przesłoniłyby `QThread.start()`.
    """
    done = Signal(int, object)     # (gen, wynik)
    failed = Signal(int, str)      # (gen, komunikat wyjątku)
    progressed = Signal(int, float)  # (gen, 0.0–1.0) — tylko w trybie `with_callbacks`

    def __init__(self, fn, gen: int = 0, with_callbacks: bool = False):
        super().__init__()
        self._fn = fn
        self.gen = gen
        self.cancelled = False
        # Operacje długie i przerywalne (budowa proxy podglądu) dostają komplet
        # uchwytów renderu: `fn(progress_cb, cancel_check, on_process)`.
        self._with_callbacks = with_callbacks
        self._proc = None

    def cancel(self) -> None:
        """Flaga „wynik już nikogo nie interesuje". Przy operacji z callbackami
        dodatkowo ubijamy proces FFmpeg — sama flaga zatrzymuje go najwcześniej
        przy kolejnej linii postępu, a użytkownik chce efektu natychmiast."""
        self.cancelled = True
        proc = self._proc
        if proc is not None:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass

    def _on_process(self, proc) -> None:
        self._proc = proc

    def run(self):
        try:
            if self._with_callbacks:
                result = self._fn(lambda p: self.progressed.emit(self.gen, p),
                                  lambda: self.cancelled,
                                  self._on_process)
            else:
                result = self._fn()
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(self.gen, str(exc))
            return
        self.done.emit(self.gen, result)


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
    # Powód ostatniego błędu (komunikat z RenderWorker.failed) — trafia do zapisu
    # kolejki w AppData i do tooltipa wiersza; czyszczony przy starcie nowej próby.
    error:  str | None = field(default=None, compare=False)


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
        "error": job.error,
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
                     label=d.get("label", ""), kwargs=kwargs,
                     error=d.get("error"))


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
        job.error = None   # nowa próba — stary powód błędu przestaje obowiązywać
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

    def _on_job_failed(self, job_id: str, msg: str) -> None:
        # Powód błędu zapisany NA zadaniu PRZED `_mark` — handler `job_status_changed`
        # (tooltip wiersza + autozapis kolejki) musi go już widzieć.
        for j in self._jobs:
            if j.id == job_id:
                j.error = msg
                break
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

    _STATUS_ROLES = {
        JobStatus.PENDING: "info",
        JobStatus.RUNNING: "warning",
        JobStatus.DONE:    "success",
        JobStatus.FAILED:  "danger",
    }

    _label_full = ""   # pełna etykieta (plik → wyjście), do elizji na resize

    def __init__(self, job: RenderJob, parent=None):
        super().__init__(parent)
        self._job_id = job.id
        self._label_full = job.label
        self._error_msg: str | None = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(SPACING["sp_2"])

        self._thumb_anchor_t: float | None = None
        self._thumb_label = QLabel()
        self._thumb_label.setFixedSize(_QUEUE_THUMB_W, _QUEUE_THUMB_H)
        self._thumb_label.setPixmap(_queue_thumb_pixmap(None))
        lay.addWidget(self._thumb_label)

        self._status_icon = StatusDot()
        lay.addWidget(self._status_icon)

        self._label = QLabel()
        self._label.setMinimumWidth(120)
        self._label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        lay.addWidget(self._label, 1)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(True)   # pokazuj liczbowy % postępu
        self._progress.setFormat("%p%")
        self._progress.setProperty("kind", "labeled")
        self._progress.setFixedWidth(140)
        lay.addWidget(self._progress)

        self._del_btn = QToolButton()
        self._del_btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self._del_btn.setIconSize(QSize(16, 16))
        _apply_icon(self._del_btn, "close", 16, "✕")
        self._del_btn.setToolTip("Usuń zadanie z kolejki")
        set_kind(self._del_btn, "ghost")
        self._del_btn.clicked.connect(lambda: self.remove_requested.emit(self._job_id))
        lay.addWidget(self._del_btn)

        self._apply_status(job.status)
        self._update_elided_label()

    def refresh_icon(self) -> None:
        _apply_icon(self._del_btn, "close", 16, "✕")
        if self._thumb_anchor_t is None:
            # Klatka jeszcze nie wyciągnięta (albo padła) — placeholder niesie
            # ikonę/kolor tokenu, więc trzeba go przemalować po zmianie motywu.
            self._thumb_label.setPixmap(_queue_thumb_pixmap(None))

    def set_thumb_frame(self, frame: "Image.Image", anchor_t: float) -> None:
        """Ustawia miniaturę na WYCIĄGNIĘTĄ klatkę (cache na wierszu — bez
        ponownej ekstrakcji przy zmianie statusu/postępu)."""
        self._thumb_anchor_t = anchor_t
        self._thumb_label.setPixmap(_queue_thumb_pixmap(frame))
        self._refresh_tooltips()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_elided_label()

    def _update_elided_label(self) -> None:
        fm = QFontMetrics(self._label.font())
        avail = max(40, self._label.width())
        self._label.setText(fm.elidedText(self._label_full, Qt.ElideMiddle, avail))
        self._refresh_tooltips()

    def update_progress(self, p: float) -> None:
        self._progress.setValue(int(p * 100))

    def update_status(self, status: JobStatus) -> None:
        self._apply_status(status)

    def set_error(self, msg: str | None) -> None:
        """Powód błędu jako tooltip całego wiersza (pełny komunikat po najechaniu)."""
        self._error_msg = msg
        self._refresh_tooltips()

    def _refresh_tooltips(self) -> None:
        tip = f"Błąd renderu:\n{self._error_msg}" if self._error_msg else self._label_full
        self.setToolTip(tip)
        self._label.setToolTip(tip)
        self._progress.setToolTip(tip)
        if self._thumb_anchor_t is not None:
            self._thumb_label.setToolTip(
                _TR("queue_thumb_tooltip").format(_fmt_time_s(round(self._thumb_anchor_t, 1))))
        else:
            self._thumb_label.setToolTip(tip)

    def _apply_status(self, status: JobStatus) -> None:
        self._status_icon.set_role(self._STATUS_ROLES.get(status, "muted"))
        self._del_btn.setVisible(status == JobStatus.PENDING)
        if status == JobStatus.FAILED:
            self._progress.setFormat("błąd")
            set_role(self._progress, "danger")
            return
        # Powrót z FAILED (retry przez „Start kolejki") musi zdjąć czerwony pasek.
        self._progress.setFormat("%p%")
        set_role(self._progress, "")
        if status == JobStatus.DONE:
            self._progress.setValue(100)


class RenderQueueWindow(QWidget):
    def __init__(self, runner: RenderQueueRunner, parent=None):
        super().__init__(parent, Qt.Window)
        # To QWidget, nie QDialog — Escape trzeba podpiąć samemu (skill, qt §8).
        QShortcut(QKeySequence.Cancel, self, self.close)
        self.setWindowTitle(_TR("queue_title"))
        self.setMinimumSize(640, 400)
        self._runner = runner
        self._rows: dict[str, JobRowWidget] = {}
        self._progress: dict[str, float] = {}   # job_id → ostatni postęp (0–1)
        self._geometry_restored = False
        # Miniatury: jeden `QueueThumbWorker` naraz (kolejka FIFO żądań) — 20
        # zadań dodanych naraz NIE mają odpalać 20 równoległych FFmpegów.
        self._thumb_pending: list[tuple[str, str, float]] = []
        self._thumb_worker: "QueueThumbWorker | None" = None

        root = QVBoxLayout(self)
        root.setSpacing(SPACING["sp_3"])
        header = SectionHeader(_TR("queue_title"), collapsible=False)
        root.addWidget(header)

        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setSpacing(2)
        self._list_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._list_widget)
        scroll.setMinimumHeight(200)
        root.addWidget(scroll, 1)

        self._empty_label = QLabel(_TR("queue_empty"))
        set_role(self._empty_label, "muted")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setWordWrap(True)
        self._list_layout.insertWidget(0, self._empty_label)

        self._statusbar = QStatusBar()
        status_message(self._statusbar, "Gotowy", "muted", 0)
        root.addWidget(self._statusbar)

        parallel_row = QHBoxLayout()
        parallel_row.setContentsMargins(0, 0, 0, 0)
        parallel_row.addWidget(QLabel("Równoległe:"))
        self._parallel_spin = QSpinBox()
        self._parallel_spin.setRange(1, config._QUEUE_PARALLEL_MAX)
        self._parallel_spin.setValue(config.load_queue_parallel())
        self._parallel_spin.setFixedWidth(56)
        self._parallel_spin.setToolTip(
            "Ile plików renderować jednocześnie. Przy NVENC pojedynczy render\n"
            "wykorzystuje GPU w ~50% (kompozycja nakładki idzie na CPU) — dwa\n"
            "równoległe niemal podwajają przepustowość partii. Zmniejsz do 1,\n"
            "gdy laptop się przegrzewa albo render idzie na CPU (x264).\n"
            "Zmiana w trakcie działa od następnego wolnego slotu.")
        self._parallel_spin.valueChanged.connect(self._on_parallel_changed)
        runner.set_parallel(self._parallel_spin.value())
        parallel_row.addWidget(self._parallel_spin)
        parallel_row.addStretch(1)
        root.addLayout(parallel_row)

        btn_row = QHBoxLayout()
        self._start_btn = QPushButton("Start kolejki")
        set_kind(self._start_btn, "primary")
        self._start_btn.setToolTip("Renderuje oczekujące zadania (tyle naraz, ile "
                                   "ustawiono w „Równoległe”; nieudane ponawia automatycznie)")
        self._start_btn.clicked.connect(self._on_start)
        self._stop_btn = QPushButton("Zatrzymaj")
        set_kind(self._stop_btn, "secondary")
        self._stop_btn.setToolTip("Przerywa biegnące rendery i pauzuje kolejkę "
                                  "(zadania zostają jako oczekujące — „Start kolejki” wznawia)")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop)
        self._clear_btn = QPushButton("Wyczyść zakończone")
        set_kind(self._clear_btn, "ghost")
        self._clear_btn.setToolTip("Usuwa z listy zadania ukończone i nieudane")
        self._clear_btn.clicked.connect(self._on_clear_finished)
        self._save_btn = QPushButton("Zapisz kolejkę…")
        set_kind(self._save_btn, "ghost")
        self._save_btn.setToolTip("Zapisz niewykonane zadania w AppData (odzysk po awarii)")
        self._save_btn.clicked.connect(self._on_save_queue)
        self._load_btn = QPushButton("Wczytaj kolejkę…")
        set_kind(self._load_btn, "ghost")
        self._load_btn.setToolTip("Wczytaj zapisaną kolejkę z AppData")
        self._load_btn.clicked.connect(self._on_load_queue)
        btn_row.addWidget(self._start_btn)
        btn_row.addWidget(self._stop_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self._clear_btn)
        btn_row.addWidget(self._save_btn)
        btn_row.addWidget(self._load_btn)
        root.addLayout(btn_row)

        runner.job_progress.connect(self._on_job_progress)
        runner.job_status_changed.connect(self._on_job_status_changed)
        runner.queue_finished.connect(self._on_queue_finished)
        runner.queue_stopped.connect(self._on_queue_stopped)

    def _update_empty_state(self) -> None:
        self._empty_label.setVisible(not self._rows)

    def refresh_icons(self) -> None:
        for row in self._rows.values():
            row.refresh_icon()

    def add_job(self, job: RenderJob) -> None:
        row = JobRowWidget(job)
        if job.error:   # kolejka wczytana z pliku — pokaż zapisany powód błędu
            row.set_error(job.error)
        row.remove_requested.connect(self._on_remove)
        self._rows[job.id] = row
        self._list_layout.insertWidget(self._list_layout.count() - 1, row)
        self._runner.add_job(job)
        self._refresh_start_btn()
        self._autosave_queue()
        self._update_empty_state()
        self._request_thumb(job)

    # --- miniatury (jeden `QueueThumbWorker` naraz, kolejka FIFO) ---
    def _request_thumb(self, job: RenderJob) -> None:
        video_path = str(job.kwargs.get("video_path") or "")
        if not video_path:
            return
        self._thumb_pending.append((job.id, video_path, _job_thumb_anchor(job)))
        self._advance_thumb_queue()

    def _advance_thumb_queue(self) -> None:
        if self._thumb_worker is not None:
            return   # ekstrakcja już w toku — ten wpis poczeka w kolejce
        while self._thumb_pending:
            job_id, video_path, anchor_t = self._thumb_pending.pop(0)
            if job_id not in self._rows:
                continue   # wiersz usunięty, zanim doszła kolej
            src = _job_thumb_source(video_path)
            worker = QueueThumbWorker(job_id, src, anchor_t)
            worker.done.connect(self._on_thumb_done)
            worker.failed.connect(self._on_thumb_failed)
            worker.finished.connect(self._on_thumb_worker_finished)
            self._thumb_worker = worker
            worker.start()
            return

    def _on_thumb_done(self, job_id: str, frame: "Image.Image") -> None:
        if row := self._rows.get(job_id):
            anchor_t = self._thumb_worker.anchor_t if self._thumb_worker else 0.0
            row.set_thumb_frame(frame, anchor_t)

    def _on_thumb_failed(self, job_id: str, msg: str) -> None:
        pass   # placeholder zostaje — brak klatki to nie błąd renderu

    def _on_thumb_worker_finished(self) -> None:
        self._thumb_worker = None
        self._advance_thumb_queue()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._geometry_restored:
            self._geometry_restored = True
            restore_window_state(self, QSettings(), prefix="ui/queue")

    def closeEvent(self, event):
        if self._runner._running:
            self.hide()
            event.ignore()
        else:
            if self._thumb_worker is not None:
                self._thumb_worker.wait(_THREAD_JOIN_MS)
            save_window_state(self, QSettings(), prefix="ui/queue")
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
            status_message(self._statusbar, "Renderowanie już trwa — poczekaj na koniec.", "warning", 5000)
        else:
            status_message(self._statusbar, "Renderowanie kolejki…", "info", 0)
        self._refresh_start_btn()

    def _on_stop(self) -> None:
        self._runner.stop()
        self._stop_btn.setEnabled(False)
        status_message(self._statusbar, "Zatrzymywanie kolejki (przerywam biegnące rendery)…", "warning", 0)

    def _on_clear_finished(self) -> None:
        for job_id, row in list(self._rows.items()):
            job = next((j for j in self._runner.jobs() if j.id == job_id), None)
            if job and job.status in (JobStatus.DONE, JobStatus.FAILED):
                self._list_layout.removeWidget(row)
                row.deleteLater()
                del self._rows[job_id]
        self._runner.clear_finished()
        self._update_empty_state()

    def _on_remove(self, job_id: str) -> None:
        if self._runner.remove_job(job_id):
            row = self._rows.pop(job_id, None)
            if row:
                self._list_layout.removeWidget(row)
                row.deleteLater()
            # Nie ma sensu wyciągać klatki dla wiersza, który już nie istnieje —
            # `_advance_thumb_queue` i tak by to sprawdziło, ale czemu czekać.
            self._thumb_pending = [p for p in self._thumb_pending if p[0] != job_id]
            self._update_empty_state()

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
        status_message(
            self._statusbar,
            f"Ukończone {done}/{total} · {detail} · łącznie {overall * 100:.0f}%",
            "info", 0)

    def _on_job_status_changed(self, job_id: str, status) -> None:
        if row := self._rows.get(job_id):
            row.update_status(status)
            if status == JobStatus.FAILED:
                job = next((j for j in self._runner.jobs() if j.id == job_id), None)
                row.set_error(job.error if job else None)
            elif status == JobStatus.RUNNING:
                row.set_error(None)   # nowa próba — tooltip ze starym błędem myli
        if status != JobStatus.RUNNING:
            self._progress.pop(job_id, None)   # świeży % po wznowieniu/ponowieniu
        self._refresh_start_btn()
        self._autosave_queue()   # DONE wypada z zapisu, FAILED zostaje (do ponowienia)

    def _on_queue_finished(self) -> None:
        status_message(self._statusbar, "Kolejka zakończona.", "success", 0)
        self._refresh_start_btn()
        QMessageBox.information(self, "Kolejka renderów",
                                "Wszystkie zadania zostały ukończone.")

    def _on_queue_stopped(self) -> None:
        status_message(
            self._statusbar,
            "Kolejka zatrzymana. „Start kolejki” wznawia od przerwanego pliku.",
            "warning", 0)
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
        status_message(
            self._statusbar,
            f"Zapisano kolejkę ({n} zadań) → {config.queue_path()}",
            "success", 5000)

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
        status_message(self._statusbar, f"Wczytano {added} zadań z zapisanej kolejki.", "success", 5000)


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
    # (row_id, int | None, info: "" | opis kodu tymczasowego/dopasowania po czasie,
    #  source: "tone" | "temp" | "time" | "")
    done = Signal(str, object, str, str)

    def __init__(self, row_id: str, video_path: str, match_time: bool = False):
        super().__init__()
        self.row_id = row_id
        self.video_path = video_path
        self.match_time = match_time

    def run(self):
        try:
            code = pipeline.detect_id_tone(self.video_path)
        except Exception:  # noqa: BLE001
            code = None
        detected, info, source = None, "", ""
        if code is not None and code.is_db_id:
            detected, source = code.value, "tone"
        elif code is not None:
            # Kod tymczasowy (sesja nagrana offline): ID wpisu trzeba dopiero
            # znaleźć w bazie po `temp_id`; T0 z bzyczka zawęża rozstrzyganie,
            # gdy ten sam kod ma kilka wpisów.
            try:
                t0 = pipeline.detect_start_signal(self.video_path)
            except Exception:  # noqa: BLE001
                t0 = None
            result = pipeline.resolve_id_tone(code, self.video_path, t0=t0)
            info = result.info
            if result.session_id is not None:
                detected, source = result.session_id, "temp"
        if detected is None and self.match_time:
            detected, match_info = self._match_by_time()
            info = match_info or info
            if detected is not None:
                source = "time"
        self.done.emit(self.row_id, detected, info, source)

    def _match_by_time(self) -> tuple[int | None, str]:
        """Opcja awaryjna: sesja dopasowana po czasie nagrania (bez T0 — wsad go
        jeszcze nie zna, więc okno = całe nagranie). Przyjmujemy TYLKO trafienie
        jednoznaczne; info trafia do `row.error` jako podpowiedź dla użytkownika."""
        try:
            # T0 najpierw: z bzyczkiem okno zawęża się do sekund, a przy kilku
            # kandydatach odcisk strzałów (pipeline) może rozstrzygnąć
            t0 = pipeline.detect_start_signal(self.video_path)
            result = pipeline.find_session_by_time(self.video_path, t0=t0)
        except Exception as exc:  # noqa: BLE001 — sieć/API: wiersz wraca do „podaj ID"
            return None, f"dopasowanie po czasie nie powiodło się: {exc}"
        if result.recording is None:
            return None, "nie wykryto ID, a czas nagrania jest nieznany — podaj ręcznie"
        if result.picked is not None:
            c = result.picked.candidate
            return c.id, (f"ID z dopasowania po czasie: {c.nazwa_toru or '—'} / "
                          f"{c.uczestnik or '—'} (Δ {result.picked.delta_s:+.0f} s) — sprawdź")
        hits = [m.candidate for m in result.matches if m.in_window]
        if hits:
            # z nazwiskami — użytkownik wie, KTO strzelał w tym nagraniu
            return None, ("kilka sesji pasuje po czasie: "
                          + ", ".join(f"{c.id} ({c.uczestnik or c.nazwa_toru or '?'})"
                                      for c in hits) + " — podaj ręcznie")
        return None, "nie wykryto ID ani sesji z czasu nagrania — podaj ręcznie"


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
    id_source:  str = ""               # "tone" (ID z sygnału audio) | "temp" (kod tymczasowy z audio)
                                       # | "time" (dopasowanie po czasie) | "" (ręcznie)


class BatchRowWidget(QWidget):
    """Wiersz jednego pliku w oknie wsadowym: status, nazwa, ID, info, play, usuń."""
    remove_requested  = Signal(str)
    play_requested    = Signal(str)
    prepare_requested = Signal(str)   # „Pobierz" — przygotuj TEN wiersz (fetch+T0)
    redetect_requested = Signal(str)  # „Wykryj ponownie" — reset wiersza + detekcja od zera
    id_changed        = Signal(str, int)

    _STATUS_ROLES = {
        BatchRowStatus.NEEDS_ID:  "warning",
        BatchRowStatus.DETECTING: "warning",
        BatchRowStatus.PENDING:   "info",
        BatchRowStatus.PREPARING: "warning",
        BatchRowStatus.READY:     "success",
        BatchRowStatus.FAILED:    "danger",
    }

    def __init__(self, row: BatchRow, parent=None):
        super().__init__(parent)
        self._row_id = row.id
        self._id_source = ""
        self._name_full = Path(row.video_path).name
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(SPACING["sp_2"])

        self._status_icon = StatusDot()
        lay.addWidget(self._status_icon)

        self._name = QLabel()
        self._name.setMinimumWidth(100)
        self._name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._name.setToolTip(row.video_path)
        lay.addWidget(self._name, 2)

        lay.addWidget(QLabel("ID:"))
        self._id_spin = QSpinBox()
        self._id_spin.setRange(0, _SESSION_ID_MAX)   # 0 = brak ID (wiersz nieprzygotowany)
        self._id_spin.setValue(row.session_id)
        # Jak `id_spin` głównego okna: stała szerokość, bez strzałek, do prawej —
        # ID sesji nie jest wartością, którą inkrementuje się o 1.
        self._id_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self._id_spin.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._id_spin.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._id_spin.setFixedWidth(110)
        self._id_spin.valueChanged.connect(
            lambda v: self.id_changed.emit(self._row_id, v))
        lay.addWidget(self._id_spin)

        # skąd jest ID: sygnał audio (detect) / dopasowanie po czasie (clock) / ręcznie (puste)
        self._src_icon = QLabel()
        self._src_icon.setFixedSize(18, 18)
        self._src_icon.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._src_icon)

        self._info = QLabel("")
        self._info.setMinimumWidth(190)
        self._info.setProperty("role", "muted")
        lay.addWidget(self._info, 2)

        # Po RĘCZNYM wpisaniu ID jeden wiersz nie powinien czekać na „Przygotuj
        # wszystkie" — przycisk pobiera z API i wyznacza T0/przycięcie od razu.
        self._prep_btn = QToolButton()
        self._prep_btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self._prep_btn.setIconSize(QSize(16, 16))
        _apply_icon(self._prep_btn, "download", 16, "⤓")
        set_kind(self._prep_btn, "ghost")
        self._prep_btn.setToolTip("Pobierz z API i przygotuj ten plik (T0 + przycięcie)")
        self._prep_btn.clicked.connect(lambda: self.prepare_requested.emit(self._row_id))
        lay.addWidget(self._prep_btn)

        self._redetect_btn = QToolButton()
        self._redetect_btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self._redetect_btn.setIconSize(QSize(16, 16))
        _apply_icon(self._redetect_btn, "loop", 16, "↻")
        set_kind(self._redetect_btn, "ghost")
        self._redetect_btn.setToolTip(
            "Wykryj ponownie — wyzeruj ID i przygotowanie, odczytaj ID z audio od nowa "
            "(jak przy pierwszym dodaniu pliku)")
        self._redetect_btn.clicked.connect(lambda: self.redetect_requested.emit(self._row_id))
        lay.addWidget(self._redetect_btn)

        self._play_btn = QToolButton()
        self._play_btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self._play_btn.setIconSize(QSize(16, 16))
        _apply_icon(self._play_btn, "play-file", 16, "▶")
        set_kind(self._play_btn, "ghost")
        self._play_btn.setToolTip("Otwórz plik źródłowy w odtwarzaczu")
        self._play_btn.clicked.connect(lambda: self.play_requested.emit(self._row_id))
        lay.addWidget(self._play_btn)

        self._del_btn = QToolButton()
        self._del_btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self._del_btn.setIconSize(QSize(16, 16))
        _apply_icon(self._del_btn, "close", 16, "✕")
        set_kind(self._del_btn, "ghost")
        self._del_btn.setToolTip("Usuń plik z listy wsadowej")
        self._del_btn.clicked.connect(lambda: self.remove_requested.emit(self._row_id))
        lay.addWidget(self._del_btn)

        self.update_row(row)
        self._update_elided_name()

    _ID_SOURCE_ICONS = {
        "tone": ("detect", "🔊", "ID odczytane z sygnału tonowego w audio"),
        "temp": ("detect", "🔊", "ID z KODU TYMCZASOWEGO w audio (sesja offline) — sprawdź"),
        "time": ("clock", "⏱", "ID z dopasowania po czasie nagrania — sprawdź"),
    }

    def _set_source_icon(self, source: str) -> None:
        spec = self._ID_SOURCE_ICONS.get(source)
        if spec is None:
            self._src_icon.clear()
            self._src_icon.setToolTip("")
            return
        name, glyph, tip = spec
        ic = ui_theme.icon(name, size=16)
        if ic.isNull():
            self._src_icon.setText(glyph)
        else:
            self._src_icon.setPixmap(ic.pixmap(16, 16))
        self._src_icon.setToolTip(tip)

    def refresh_icon(self) -> None:
        self._set_source_icon(self._id_source)
        _apply_icon(self._prep_btn, "download", 16, "⤓")
        _apply_icon(self._redetect_btn, "loop", 16, "↻")
        _apply_icon(self._play_btn, "play-file", 16, "▶")
        _apply_icon(self._del_btn, "close", 16, "✕")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_elided_name()

    def _update_elided_name(self) -> None:
        fm = QFontMetrics(self._name.font())
        avail = max(40, self._name.width())
        self._name.setText(fm.elidedText(self._name_full, Qt.ElideMiddle, avail))

    def set_session_id(self, value: int) -> None:
        """Ustawia ID w spinboxie (wyemituje `id_changed` → aktualizacja wiersza)."""
        self._id_spin.setValue(value)

    def set_session_id_silent(self, value: int) -> None:
        """Jak `set_session_id`, ale bez `id_changed` (wywołujący sam ustawił `row`)."""
        self._id_spin.blockSignals(True)
        try:
            self._id_spin.setValue(value)
        finally:
            self._id_spin.blockSignals(False)

    def update_row(self, row: BatchRow) -> None:
        self._status_icon.set_role(self._STATUS_ROLES.get(row.status, "muted"))
        self._id_source = row.id_source
        self._set_source_icon(row.id_source)
        busy = row.status in _BATCH_BUSY
        self._id_spin.setEnabled(not busy)
        self._del_btn.setEnabled(not busy)
        self._redetect_btn.setEnabled(not busy)
        # FAILED też — ponowna próba jednego pliku bez „Przygotuj wszystkie"
        self._prep_btn.setEnabled(
            row.status in (BatchRowStatus.PENDING, BatchRowStatus.FAILED)
            and row.session_id > 0)
        if row.status == BatchRowStatus.READY and row.prep:
            p = row.prep
            # Metadane z API obok liczb: w wierszu jest na to miejsce, a bez nich
            # nie widać, CZYJĄ sesję pobrało wpisane ręcznie (lub odczytane) ID.
            sess = p.get("session")
            meta = " · ".join(x for x in (
                getattr(sess, "nazwa_toru", None), getattr(sess, "uczestnik", None)) if x)
            shots = f"{sess.total_shots} strz." if sess is not None else ""
            tech = f"T0={p['t0']:.2f}s · przyc. {p['trim_start']:.1f}–{p['trim_end']:.1f}s"
            self._info.setText(" · ".join(x for x in (meta, shots, tech) if x))
            set_role(self._info, "success")
            self._info.setToolTip("\n".join(x for x in (meta, shots, tech) if x))
        elif row.status == BatchRowStatus.FAILED:
            self._info.setText(f"błąd: {row.error}")
            set_role(self._info, "danger")
            self._info.setToolTip(row.error)
        elif row.status == BatchRowStatus.PREPARING:
            self._info.setText("przygotowuję…")
            set_role(self._info, "warning")
        elif row.status == BatchRowStatus.DETECTING:
            self._info.setText("wykrywam ID z audio…")
            set_role(self._info, "warning")
        elif row.status == BatchRowStatus.NEEDS_ID:
            # po nieudanej detekcji `row.error` niesie „nie wykryto ID — podaj ręcznie"
            self._info.setText(row.error or "podaj ID")
            set_role(self._info, "warning")
        elif row.status == BatchRowStatus.PENDING and row.error:
            # ID z dopasowania po czasie (nie z sygnału tonowego) — podpowiedź do
            # sprawdzenia przed „Przygotuj wszystkie"; znika przy ręcznej zmianie ID
            self._info.setText(row.error)
            set_role(self._info, "warning")
            self._info.setToolTip(row.error)
        else:
            self._info.setText("gotowe — kliknij ⤓ albo „Przygotuj wszystkie”")
            set_role(self._info, "muted")
            self._info.setToolTip("")


_sanitize_filename_part = pipeline.sanitize_filename_part   # domena; alias dla starych wywołań


class BatchDialog(QWidget):
    """Okno przetwarzania wsadowego (tryb auto + ID).

    Dodajesz wiele plików, podajesz ID dla każdego, klikasz „Przygotuj" — aplikacja
    pobiera sesje z API, wykrywa T0 (bzyczek) i liczy auto-przycięcie. Wspólny styl
    nakładki, jeden katalog docelowy, prefiks i sufiks nazwy. Gotowe pliki trafiają do
    istniejącej kolejki renderów (`RenderQueueRunner`), która renderuje je po kolei.
    """

    def __init__(self, runner: "RenderQueueRunner", queue_window: "RenderQueueWindow",
                 base_style: OverlayStyle, parent=None):
        super().__init__(parent, Qt.Window)
        QShortcut(QKeySequence.Cancel, self, self.close)   # jak w oknie kolejki
        self.setWindowTitle(_TR("batch_title"))
        self.setMinimumSize(720, 700)
        self.setAcceptDrops(True)
        self._runner = runner
        self._queue_window = queue_window
        self._base_style = base_style
        self._rows: dict[str, BatchRow] = {}
        self._row_widgets: dict[str, BatchRowWidget] = {}
        self._workers: dict[str, QThread] = {}   # prep/detect, trzymane do finished
        self._geometry_restored = False
        # „Automat z folderu…": etapy łańcucha (skan → detekcja ID → przygotowanie)
        self._auto_queue: list[str] = []   # etapy jeszcze do wykonania
        self._auto_stage = ""              # etap trwający ("" = brak łańcucha)
        self._auto_total = 0               # ile wierszy objął bieżący etap

        root = QVBoxLayout(self)
        root.setSpacing(SPACING["sp_3"])
        root.addWidget(SectionHeader(_TR("batch_title"), collapsible=False))

        # --- wiersz „Automat" (jedyny primary w oknie) ---
        auto_row = QHBoxLayout()
        self._auto_btn = QPushButton(_TR("batch_auto"))
        set_kind(self._auto_btn, "primary")
        self._auto_btn.setToolTip(_TR("batch_auto_tip"))
        self._auto_btn.clicked.connect(self._auto_from_folder)
        self._recursive_chk = QCheckBox(_TR("batch_auto_recursive"))
        self._recursive_chk.setToolTip(
            "Skanuje też katalogi wewnątrz wskazanego (np. kam1/ i kam2/).")
        self._match_time_chk = QCheckBox(_TR("batch_match_time"))
        self._match_time_chk.setToolTip(_TR("batch_match_time_tip"))
        self._match_time_chk.setChecked(
            QSettings().value("ui/batch/match_by_time", True, type=bool))
        self._match_time_chk.toggled.connect(
            lambda on: QSettings().setValue("ui/batch/match_by_time", on))
        auto_row.addWidget(self._auto_btn)
        auto_row.addWidget(self._recursive_chk)
        auto_row.addWidget(self._match_time_chk)
        auto_row.addStretch(1)
        root.addLayout(auto_row)

        top = QHBoxLayout()
        add_btn = QPushButton("Dodaj pliki…")
        set_kind(add_btn, "secondary")
        add_btn.setToolTip("Dodaje pliki wideo do listy wsadowej")
        add_btn.clicked.connect(self._add_files)
        export_btn = QPushButton("Eksport → schowek")
        set_kind(export_btn, "ghost")
        export_btn.setToolTip("Kopiuje listę jako wiersze „<ścieżka>;<ID>”")
        export_btn.clicked.connect(self._export_clipboard)
        import_btn = QPushButton("Import ze schowka")
        set_kind(import_btn, "ghost")
        import_btn.setToolTip("Wkleja listę „<ścieżka>;<ID>” ze schowka")
        import_btn.clicked.connect(self._import_clipboard)
        self._detect_id_btn = QPushButton("Wykryj ID z audio")
        set_kind(self._detect_id_btn, "ghost")
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
        set_role(self._count_label, "muted")
        top.addWidget(self._count_label)
        root.addLayout(top)

        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setSpacing(2)
        self._list_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._list_widget)
        scroll.setMinimumHeight(180)
        root.addWidget(scroll, 1)

        self._empty_label = QLabel(_TR("batch_empty"))
        set_role(self._empty_label, "muted")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setWordWrap(True)
        self._list_layout.insertWidget(0, self._empty_label)

        # --- ustawienia wspólne dla całej partii ---
        opts = FormSection("Ustawienia wspólne", collapsible=False)

        self._out_dir = PathField(mode="dir", placeholder="np. D:\\rendery")
        opts.add_row("Katalog docelowy", self._out_dir)

        # Prefiks/sufiks to SZABLONY: {id} {uczestnik} {tor} {strzaly} {czas} {hf}
        # (pipeline.expand_name_template) — zastąpiły checkbox „Dodaj informacje
        # o uczestniku" (= sufiks „_PiRoOverlay_{id}_{uczestnik}"). Pamięć w QSettings.
        vars_tip = ("Zmienne: " + " ".join(f"{{{v}}}" for v in pipeline.NAME_TEMPLATE_VARS)
                    + "\n{id} = ID sesji, {uczestnik}/{tor} z API (diakrytyki → ASCII, "
                    "spacje → _), {strzaly} = liczba strzałów, {czas} = czas bazowy, "
                    "{hf} = hit factor.\nPrzykład sufiksu: _PiRoOverlay_{id}_{uczestnik}")
        self._prefix_edit = QLineEdit(QSettings().value("ui/batch/prefix", "", type=str))
        self._prefix_edit.setPlaceholderText("np. {tor}_")
        self._prefix_edit.setToolTip(vars_tip)
        self._prefix_edit.textChanged.connect(
            lambda t: QSettings().setValue("ui/batch/prefix", t))
        opts.add_row("Prefiks nazwy", self._prefix_edit)

        self._suffix_edit = QLineEdit(
            QSettings().value("ui/batch/suffix", "_PiRoOverlay", type=str))
        self._suffix_edit.setPlaceholderText("np. _PiRoOverlay_{id}_{uczestnik}")
        self._suffix_edit.setToolTip(vars_tip)
        self._suffix_edit.textChanged.connect(
            lambda t: QSettings().setValue("ui/batch/suffix", t))
        opts.add_row("Sufiks nazwy", self._suffix_edit)

        vars_lbl = QLabel("Zmienne w prefiksie/sufiksie: "
                          + " ".join(f"{{{v}}}" for v in pipeline.NAME_TEMPLATE_VARS))
        vars_lbl.setProperty("role", "muted")
        vars_lbl.setToolTip(vars_tip)
        opts.add_row("", vars_lbl)

        self._format_combo = QComboBox()
        for label, val in (("MP4 (H.264)", "mp4"), ("WebM (VP9)", "webm"),
                           ("GIF (animowany)", "gif")):
            self._format_combo.addItem(label, val)
        self._format_combo.currentIndexChanged.connect(lambda *_: self._refresh())
        opts.add_row("Format", self._format_combo)

        # Warianty wyjścia — KAŻDY zaznaczony daje osobne zadanie w kolejce per plik
        # (pipeline.batch_variants); przy >1 wariancie nazwa dostaje sufiks `_overlay`/
        # `_timer`/`_trim`. Enkoder zawsze „auto” (render sam spada na CPU), checkbox
        # GPU zniknął. Pamięć w QSettings, niezależna od stylu głównego okna.
        toggles = QHBoxLayout()
        toggles.setContentsMargins(0, 0, 0, 0)
        self._variant_overlay_chk = QCheckBox("Nakładka ze strzałami")
        self._variant_overlay_chk.setToolTip(
            "Wariant „overlay”: nakładka ze strzałami BEZ płynącego zegara")
        self._variant_timer_chk = QCheckBox("Płynący zegar od T0")
        self._variant_timer_chk.setToolTip(
            "Wariant „timer”: nakładka ze strzałami + płynący zegar od T0")
        self._variant_trim_chk = QCheckBox("Przycięcie")
        self._variant_trim_chk.setToolTip(
            "Wariant „trim”: samo przycięcie nagrania, bez żadnej nakładki")
        for chk, key, default in (
                (self._variant_overlay_chk, "ui/batch/variant_overlay", True),
                (self._variant_timer_chk, "ui/batch/variant_timer", False),
                (self._variant_trim_chk, "ui/batch/variant_trim", False)):
            chk.setChecked(QSettings().value(key, default, type=bool))
            chk.toggled.connect(partial(self._on_variant_toggled, key))
            toggles.addWidget(chk)
        toggles.addStretch(1)
        opts.add_widget_row(_wrap(toggles))
        root.addWidget(opts)

        note = QLabel(
            "Tryb auto + ID: oś czasu z API (po ID), T0 = wykryty bzyczek, przycięcie "
            "5 s przed T0 → ostatni strzał + 5 s. Wygląd nakładki wspólny — kopiowany "
            "z głównego okna (zmień go tam przed otwarciem). Plansza START zawsze (auto). "
            "„Wykryj ID z audio” próbuje odczytać ID z sygnału tonowego timera dla "
            "plików bez ID.")
        note.setProperty("role", "muted")
        note.setWordWrap(True)
        root.addWidget(note)

        self._statusbar = QStatusBar()
        self._batch_progress = QProgressBar()
        self._batch_progress.setRange(0, 100)
        self._batch_progress.setTextVisible(False)
        self._batch_progress.setFixedWidth(140)
        self._batch_progress.hide()
        self._statusbar.addPermanentWidget(self._batch_progress)
        status_message(self._statusbar, "Gotowy", "muted", 0)
        root.addWidget(self._statusbar)

        btns = QHBoxLayout()
        self._prep_btn = QPushButton("Przygotuj wszystkie")
        # secondary, bo jedynym primary w oknie jest „Automat z folderu…"
        set_kind(self._prep_btn, "secondary")
        self._prep_btn.setToolTip("Dla plików z ID: pobiera sesję z API, wykrywa "
                                  "sygnał startu (T0) i liczy auto-przycięcie")
        self._prep_btn.clicked.connect(self._prepare_all)
        self._enqueue_btn = QPushButton("Wyślij gotowe do kolejki")
        set_kind(self._enqueue_btn, "secondary")
        self._enqueue_btn.setToolTip("Buduje zadania renderu z przygotowanych "
                                     "plików i dodaje je do kolejki renderów")
        self._enqueue_btn.clicked.connect(self._enqueue_ready)
        self._clear_btn = QPushButton("Wyczyść wszystko")
        set_kind(self._clear_btn, "ghost")
        self._clear_btn.setToolTip("Usuwa wszystkie pliki z listy wsadowej")
        self._clear_btn.clicked.connect(self._clear_all)
        close_btn = QPushButton("Zamknij")
        set_kind(close_btn, "ghost")
        close_btn.clicked.connect(self.close)
        btns.addWidget(self._prep_btn)
        btns.addWidget(self._enqueue_btn)
        btns.addStretch(1)
        btns.addWidget(self._clear_btn)
        btns.addWidget(close_btn)
        root.addLayout(btns)

        self._refresh()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._geometry_restored:
            self._geometry_restored = True
            restore_window_state(self, QSettings(), prefix="ui/batch")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.toLocalFile()]
        if not paths:
            return
        if not self._out_dir.path():
            self._out_dir.set_path(str(Path(paths[0]).parent), emit=False)
        for path in paths:
            self._add_row(path)
        self._refresh()

    # --- dodawanie / usuwanie plików ---
    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Wybierz pliki wideo", "",
            "Wideo (*.mp4 *.mov *.mkv *.avi);;Wszystkie pliki (*)")
        if not paths:
            return
        if not self._out_dir.path() and paths:
            self._out_dir.set_path(str(Path(paths[0]).parent), emit=False)
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
        w.prepare_requested.connect(self._prepare_row)
        w.redetect_requested.connect(self._redetect_row)
        w.id_changed.connect(self._on_id_changed)
        self._row_widgets[row.id] = w
        self._list_layout.insertWidget(self._list_layout.count() - 1, w)
        self._update_empty_state()
        return row

    def _update_empty_state(self) -> None:
        self._empty_label.setVisible(not self._rows)

    def refresh_icons(self) -> None:
        for w in self._row_widgets.values():
            w.refresh_icon()

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
        self._update_empty_state()
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
        self._auto_cancel()   # wyczyszczenie listy gasi łańcuch „Automatu"
        for w in self._row_widgets.values():
            self._list_layout.removeWidget(w)
            w.deleteLater()
        self._rows.clear()
        self._row_widgets.clear()
        self._update_empty_state()
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
        row.id_source = ""      # ręczna edycja = ID od użytkownika, nie z detekcji
        row.status = BatchRowStatus.PENDING if value > 0 else BatchRowStatus.NEEDS_ID
        self._sync_row(row)
        self._refresh()

    def _on_variant_toggled(self, settings_key: str, on: bool) -> None:
        QSettings().setValue(settings_key, on)
        self._refresh()

    def _selected_variants(self) -> list[pipeline.BatchVariant]:
        return pipeline.batch_variants(
            overlay=self._variant_overlay_chk.isChecked(),
            timer=self._variant_timer_chk.isChecked(),
            trim=self._variant_trim_chk.isChecked())

    # --- „Automat z folderu…": skan → ID z audio → przygotowanie ---
    def _auto_active(self) -> bool:
        return bool(self._auto_stage or self._auto_queue)

    def _auto_from_folder(self) -> None:
        """Wskazany katalog → wiersze → detekcja ID → przygotowanie.

        Do kolejki ŚWIADOMIE nic nie trafia automatycznie: błędnie odczytane ID
        pobrałoby cudzą sesję, więc przegląd przed „Wyślij gotowe do kolejki"
        zostaje ręczny (jak dotąd).
        """
        if self._auto_active() or any(r.status in _BATCH_BUSY
                                      for r in self._rows.values()):
            return
        start_dir = (config.load_last_dir("batch_dir")
                     or config.load_last_dir("video") or "")
        directory = QFileDialog.getExistingDirectory(
            self, _TR("batch_auto_pick_dir"), start_dir)
        if not directory:
            return
        config.save_last_dir("batch_dir", directory)
        status_message(self._statusbar, _TR("batch_auto_scanning"), "info", 0)
        try:
            files = pipeline.scan_video_dir(
                directory, recursive=self._recursive_chk.isChecked())
        except (pipeline.PipelineError, OSError) as exc:  # noqa: BLE001
            status_message(self._statusbar,
                           _TR("batch_auto_scan_failed").format(exc), "danger", 0)
            return
        if not files:
            status_message(self._statusbar, _TR("batch_auto_no_files"), "warning", 0)
            return
        if not self._out_dir.path():
            self._out_dir.set_path(directory, emit=False)
        added = sum(1 for f in files if self._add_row(str(f)) is not None)
        self._refresh()
        self._count_label.setText(
            _TR("batch_auto_added").format(added, len(files)))
        self._auto_queue = ["detect", "prep"]
        self._auto_advance()

    def _auto_advance(self) -> None:
        """Uruchamia kolejny etap łańcucha; gdy nie ma czego robić — podsumowuje."""
        while self._auto_queue:
            stage = self._auto_queue.pop(0)
            if stage == "detect":
                todo = [r for r in self._rows.values()
                        if r.status == BatchRowStatus.NEEDS_ID]
                if todo:
                    self._auto_stage, self._auto_total = stage, len(todo)
                    self._detect_ids()
                    return
            elif stage == "prep":
                todo = [r for r in self._rows.values()
                        if r.status == BatchRowStatus.PENDING and r.session_id > 0]
                if todo:
                    self._auto_stage, self._auto_total = stage, len(todo)
                    self._prepare_all()
                    return
        self._auto_finish()

    def _auto_finish(self) -> None:
        """Koniec łańcucha — podsumowanie w pasku stanu (po `_refresh`, bo ono
        nadpisuje komunikat stanem „Gotowy")."""
        self._auto_queue.clear()
        self._auto_stage = ""
        ready = sum(1 for r in self._rows.values()
                    if r.status == BatchRowStatus.READY)
        no_id = sum(1 for r in self._rows.values()
                    if r.status == BatchRowStatus.NEEDS_ID)
        failed = sum(1 for r in self._rows.values()
                     if r.status == BatchRowStatus.FAILED)
        self._refresh()
        kind = "success" if ready and not (no_id or failed) else "warning"
        status_message(self._statusbar,
                       _TR("batch_auto_summary").format(ready, no_id, failed),
                       kind, 0)

    def _auto_cancel(self) -> None:
        """Gasi łańcuch (zamknięcie okna, „Wyczyść wszystko"). Biegnące workery
        kończą się same — przerywamy tylko przechodzenie do kolejnych etapów."""
        self._auto_queue.clear()
        self._auto_stage = ""

    def _finish_worker(self, row_id: str) -> None:
        """Zwalnia referencję workera PO `wait()` (ta sama pułapka QThread co w
        kolejce renderów) i popycha łańcuch, gdy etap właśnie się domknął."""
        worker = self._workers.pop(row_id, None)
        if worker is not None:
            worker.wait()
        if not self._workers and self._auto_stage:
            # etap skończony — kolejny odpalamy przez pętlę zdarzeń, żeby nie
            # startować nowego QThread z wnętrza sygnału `finished` poprzedniego
            self._auto_stage = ""
            QTimer.singleShot(0, self._auto_advance)

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
        self._auto_total = len(todo)   # licznik etapu w pasku stanu („3/12")
        for row in todo:
            self._start_detect(row)
        self._refresh()

    def _start_detect(self, row: BatchRow) -> None:
        row.status = BatchRowStatus.DETECTING
        row.error = ""
        self._sync_row(row)
        worker = BatchIdDetectWorker(row.id, row.video_path,
                                     match_time=self._match_time_chk.isChecked())
        worker.done.connect(self._on_id_detected)
        worker.finished.connect(lambda rid=row.id: self._finish_worker(rid))
        self._workers[row.id] = worker
        worker.start()

    def _redetect_row(self, row_id: str) -> None:
        """„Wykryj ponownie": wiersz wraca do stanu jak po dodaniu (bez ID, bez
        przygotowania, bez pochodzenia) i od razu rusza detekcja ID z audio
        (+ dopasowanie po czasie wg checkboxa) — jak przy pierwszym dodaniu."""
        row = self._rows.get(row_id)
        if row is None or row.status in _BATCH_BUSY or row.id in self._workers:
            return
        row.prep = None
        row.error = ""
        row.id_source = ""
        row.session_id = 0
        row.status = BatchRowStatus.NEEDS_ID
        if w := self._row_widgets.get(row_id):
            # spinbox → _on_id_changed odrzuciłby wartość przy DETECTING, więc
            # zerujemy PRZED startem workera i blokujemy sygnał (row już ma 0)
            w.set_session_id_silent(0)
        self._auto_total = 1 + sum(1 for r in self._rows.values()
                                   if r.status == BatchRowStatus.DETECTING)
        self._start_detect(row)
        self._refresh()

    def _on_id_detected(self, row_id: str, detected: object, info: str = "",
                        source: str = "") -> None:
        row = self._rows.get(row_id)
        if row is None:
            return
        # najpierw wróć do NEEDS_ID, żeby _on_id_changed (guard _BATCH_BUSY)
        # przyjął wartość ustawianą przez spinbox
        row.status = BatchRowStatus.NEEDS_ID
        if not detected:
            row.error = info or "nie wykryto ID — podaj ręcznie"
            self._sync_row(row)
        elif w := self._row_widgets.get(row_id):
            w.set_session_id(int(detected))   # → _on_id_changed → PENDING (czyści error i źródło)
            row.id_source = source
            if info:
                # ID z dopasowania po czasie: podpowiedź zostaje w wierszu, żeby
                # użytkownik sprawdził je przed „Przygotuj wszystkie"
                row.error = info
            self._sync_row(row)
        else:
            row.session_id = int(detected)
            row.status = BatchRowStatus.PENDING
            row.error = info
            row.id_source = source
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
        self._auto_total = len(todo)   # licznik etapu w pasku stanu („5/12")
        for row in todo:
            self._start_prepare(row)
        self._refresh()

    def _prepare_row(self, row_id: str) -> None:
        """„Pobierz" w wierszu: przygotowanie JEDNEGO pliku (PENDING albo ponowienie FAILED)."""
        row = self._rows.get(row_id)
        if row is None or row.session_id <= 0 or row.id in self._workers:
            return
        if row.status not in (BatchRowStatus.PENDING, BatchRowStatus.FAILED):
            return
        self._auto_total = 1 + sum(1 for r in self._rows.values()
                                   if r.status == BatchRowStatus.PREPARING)
        self._start_prepare(row)
        self._refresh()

    def _start_prepare(self, row: BatchRow) -> None:
        row.status = BatchRowStatus.PREPARING
        row.error = ""
        self._sync_row(row)
        worker = BatchPrepWorker(row.id, row.video_path, row.lrf_path,
                                 row.session_id)
        worker.done.connect(self._on_prep_done)
        worker.failed.connect(self._on_prep_failed)
        worker.finished.connect(lambda rid=row.id: self._finish_worker(rid))
        self._workers[row.id] = worker
        worker.start()

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
        variants = self._selected_variants()
        if not variants:
            status_message(self._statusbar,
                           "Zaznacz przynajmniej jeden wariant wyjścia", "warning", 6000)
            return
        out_dir = Path(self._out_dir.path()) if self._out_dir.path() else None
        if out_dir is None or not out_dir.is_dir():
            QMessageBox.warning(self, "Brak katalogu",
                                "Wskaż istniejący katalog docelowy.")
            return
        fmt = self._format_combo.currentData()
        ext = _FORMAT_EXT.get(fmt, ".mp4")
        prefix = self._prefix_edit.text()
        suffix = self._suffix_edit.text()

        added = 0
        for row in ready:
            p = row.prep
            session = p["session"]
            base_name = (
                pipeline.expand_name_template(prefix, session, row.session_id)
                + Path(row.video_path).stem
                + pipeline.expand_name_template(suffix, session, row.session_id))
            t0 = audio_sync.resolve_t0(p["t0"], AnchorMode.START_SIGNAL,
                                       session.shots[0].czas)
            for variant in variants:
                out_path = out_dir / (
                    base_name + pipeline.batch_variant_suffix(variants, variant) + ext)
                style = replace(self._base_style, show_running_clock=variant.clock)
                kwargs = dict(
                    video_path=row.video_path, session=session, t0=t0,
                    style=style, mode=AnchorMode.START_SIGNAL, out_path=str(out_path),
                    trim_start=p["trim_start"] if p["trim_start"] > 0 else None,
                    trim_end=p["trim_end"] if p["trim_end"] > 0 else None,
                    encoder="auto", no_overlay=variant.no_overlay, output_format=fmt,
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
        _dark_titlebar(self._queue_window)
        self._queue_window.raise_()
        self._refresh()
        QMessageBox.information(
            self, "Przetwarzanie wsadowe",
            f"Dodano {added} zadań do kolejki. Kliknij „Start kolejki” w oknie kolejki.")

    # --- pomocnicze ---
    def _sync_row(self, row: BatchRow) -> None:
        if w := self._row_widgets.get(row.id):
            w.update_row(row)

    def _stage_message(self) -> str:
        """Komunikat etapu do paska stanu („Wykrywam ID: 3/12")."""
        left_det = sum(1 for r in self._rows.values()
                       if r.status == BatchRowStatus.DETECTING)
        left_prep = sum(1 for r in self._rows.values()
                        if r.status == BatchRowStatus.PREPARING)
        if left_det:
            total = max(self._auto_total, left_det)
            return _TR("batch_auto_detecting").format(total - left_det, total)
        if left_prep:
            total = max(self._auto_total, left_prep)
            return _TR("batch_auto_preparing").format(total - left_prep, total)
        return "Przetwarzanie w tle…"

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
        set_busy(self._prep_btn, busy and any(
            r.status == BatchRowStatus.PREPARING for r in self._rows.values()),
            "Przygotowuję…")
        set_busy(self._detect_id_btn, busy and any(
            r.status == BatchRowStatus.DETECTING for r in self._rows.values()),
            "Wykrywam…")
        self._prep_btn.setEnabled(pending > 0 and not busy)
        self._enqueue_btn.setEnabled(ready > 0 and not busy
                                     and bool(self._selected_variants()))
        self._clear_btn.setEnabled(n > 0 and not busy)
        self._detect_id_btn.setEnabled(needs_id > 0 and not busy)
        auto = self._auto_active()
        set_busy(self._auto_btn, auto, _TR("batch_auto_busy"))
        self._auto_btn.setEnabled(not busy and not auto)
        self._recursive_chk.setEnabled(not busy and not auto)
        self._batch_progress.setVisible(busy or auto)
        if busy or auto:
            self._batch_progress.setRange(0, 0)   # nieokreślony — postęp per plik nieznany
            status_message(self._statusbar, self._stage_message(), "info", 0)
        else:
            self._batch_progress.setRange(0, 100)
            status_message(self._statusbar, "Gotowy", "muted", 0)

    def closeEvent(self, event):
        self._auto_cancel()   # zamknięcie okna gasi łańcuch „Automatu"
        if any(r.status in _BATCH_BUSY for r in self._rows.values()):
            self.hide()
            event.ignore()
        else:
            save_window_state(self, QSettings(), prefix="ui/batch")
            event.accept()


# ----------------------------- waveform -----------------------------
class WaveformWidget(QWidget):
    """Wizualizacja ścieżki audio z interakcją:

    - lewy klik (poza uchwytami) → ustawia kotwicę T0,
    - Ctrl + lewy klik → podgląd klatki w danym czasie (bez zmiany T0),
    - przeciągnięcie uchwytu (Od/Do) → przycięcie fragmentu,
    - cienkie znaczniki = wykryte onsety (pomoc w trafieniu sygnału/strzału),
    - znaczniki strzałów sesji (czas absolutny = T0 + czas strzału): klik =
      zaznaczenie, przeciągnięcie = zmiana czasu, Delete/Backspace = usunięcie,
    - klawiatura (po fokusie): ←/→ kotwica, Home/End granice przycięcia,
      +/− zoom, 0 reset, O znaczniki onsetów, I/O granice w bieżącym czasie,
      T kotwica w bieżącym czasie, M dodanie strzału,
    - playhead (linia ciągła + trójkąt na osi) pokazuje pozycję odtwarzania;
      kursor podglądu klatki jest przerywany — to DWA różne markery.

    Kolory pochodzą WYŁĄCZNIE z tokenów motywu (`current_tokens`) i są czytane
    w `paintEvent` — zmiana motywu wymaga jedynie `update()`.
    """

    anchorChanged = Signal(float)
    trimChanged = Signal(float, float)
    previewAt = Signal(float)   # Ctrl+klik → podgląd/seek w czasie t
    addShotAt = Signal(float)   # M → dodaj strzał w bieżącym czasie
    shotMoved = Signal(int, float)   # (indeks, nowy czas ABSOLUTNY) — commit edycji
    shotDeleted = Signal(int)        # Delete/Backspace na zaznaczonym strzale

    KEY_STEP = 0.05       # ←/→ przesuwa kotwicę o 50 ms
    KEY_STEP_FAST = 1.0   # Shift + ←/→

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(140)
        self.setFocusPolicy(Qt.StrongFocus)   # oś jest kontrolką, nie dekoracją
        self.env: list[float] = []
        self.duration = 0.0
        self.onsets: list[float] = []
        # znaczniki strzałów sesji w czasie ABSOLUTNYM (T0 + shot.czas) —
        # wyliczane przez MainWindow (`_sync_wave_shots`), oś ich nie liczy sama
        self.shots: list[float] = []
        self.selected_shot: int | None = None
        self._shot_drag_from: float | None = None   # czas przed przeciągnięciem
        self.anchor: float | None = None
        self.anchor_label = "T0"      # "T0" (beep) lub "T1" (pierwszy strzał) wg trybu
        self.preview_t: float | None = None   # czas aktualnie podglądu (Ctrl+klik)
        self.playhead_t: float | None = None  # pozycja odtwarzania (podgląd w ruchu)
        self.trim_start = 0.0
        self.trim_end = 0.0
        self.show_onsets = True       # warstwa widoku (klawisz O) — dane zostają
        # okno widoku (zoom): widoczny zakres czasu [view_start, view_end]
        self.view_start = 0.0
        self.view_end = 0.0
        self._drag: str | None = None  # "start" | "end" | None
        self._pan = None               # (x0, vs, ve) podczas przesuwania
        # cache obwiedni: dwa pixmapy (w zakresie / poza zakresem) + klucz
        self._wave_cache: QPixmap | None = None
        self._wave_cache_dim: QPixmap | None = None
        self._cache_key: tuple | None = None
        self._hidden_tags: list[tuple[int, str]] = []   # etykiety zdjęte przez kolizję
        self._base_tip = _TR("wave_tip")
        self.setCursor(Qt.CrossCursor)
        self.setToolTip(self._base_tip)

    def set_data(self, env, duration, onsets):
        self.env = env
        self.duration = duration
        self.onsets = onsets
        self.shots = []
        self.selected_shot = None
        self.trim_start = 0.0
        self.trim_end = duration
        self.anchor = None
        self.preview_t = None
        self.playhead_t = None
        self.view_start = 0.0
        self.view_end = duration
        self._cache_key = None
        self.update()

    def set_anchor(self, t: float):
        self.anchor = t
        self.update()

    def set_shots(self, times: list[float]) -> None:
        """Znaczniki strzałów (czasy ABSOLUTNE). Zaznaczenie przeżywa odświeżenie
        tylko wtedy, gdy indeks nadal istnieje — po usunięciu ostatniego strzału
        gaśnie samo."""
        self.shots = list(times)
        if self.selected_shot is not None and self.selected_shot >= len(self.shots):
            self.selected_shot = None
        self.update()

    def select_shot(self, index: int | None) -> None:
        """Zaznaczenie strzału (None = brak). Po przesunięciu strzał zmienia
        indeks (lista jest sortowana) — MainWindow wskazuje nowy jawnie."""
        if index is not None and not 0 <= index < len(self.shots):
            index = None
        self.selected_shot = index
        self.update()

    def _shot_at_x(self, x: float) -> int | None:
        """Indeks strzału pod kursorem (±`_SHOT_HIT_PX`), najbliższy przy remisie."""
        best, best_d = None, _SHOT_HIT_PX + 1.0
        for i, t in enumerate(self.shots):
            if not self._in_view(t):
                continue
            d = abs(self._t2x(t) - x)
            if d <= _SHOT_HIT_PX and d < best_d:
                best, best_d = i, d
        return best

    def set_trim(self, start: float, end: float):
        self.trim_start, self.trim_end = start, end
        self.update()

    def set_playhead(self, t: float | None) -> None:
        """Pozycja odtwarzania. Widok podąża za playheadem TYLKO gdy ten wyjedzie
        poza okno (przesuwamy okno, nie zmieniamy zoomu — inaczej obraz osi skakałby
        przy każdym odtworzeniu)."""
        self.playhead_t = t
        if t is not None and not self._in_view(t):
            self._ensure_visible(t)
        self.update()

    def current_t(self) -> float:
        """Czas „tu i teraz” dla skrótów I/O/T/M: playhead → kursor podglądu →
        kotwica → początek zakresu."""
        for value in (self.playhead_t, self.preview_t, self.anchor):
            if value is not None:
                return value
        return self.trim_start

    # --- okno widoku ---
    def _span(self) -> float:
        return max(self.view_end - self.view_start, 1e-6)

    def _in_view(self, t: float) -> bool:
        return self.view_start <= t <= self.view_end

    def _plot_h(self) -> int:
        return max(1, self.height() - _AXIS_H)

    def fit_view(self) -> None:
        """Cały materiał w widoku (reset zoomu) — przycisk „Dopasuj" i klawisz 0."""
        if self.duration <= 0:
            return
        self.view_start, self.view_end = 0.0, self.duration
        self.update()

    def zoom_to_trim(self) -> None:
        """Widok = zakres Od…Do z 5 % marginesu."""
        if self.duration <= 0:
            return
        a, b = self.trim_start, self.trim_end
        if b - a < 0.1:
            self.fit_view()
            return
        pad = (b - a) * 0.05
        self.view_start = max(0.0, a - pad)
        self.view_end = min(self.duration, b + pad)
        self.update()

    def _zoom(self, factor: float, center_t: float) -> None:
        span = self._span()
        new_span = max(0.05, min(self.duration, span * factor))
        frac = (center_t - self.view_start) / span
        ns = center_t - frac * new_span
        ne = ns + new_span
        if ns < 0:
            ns, ne = 0.0, new_span
        if ne > self.duration:
            ne, ns = self.duration, self.duration - new_span
        self.view_start, self.view_end = max(0.0, ns), min(self.duration, ne)
        self.update()

    # --- mapowanie czas <-> px (względem okna widoku) ---
    def _t2x(self, t: float) -> float:
        return (t - self.view_start) / self._span() * self.width()

    def _x2t(self, x: float) -> float:
        if self.width() <= 0:
            return self.view_start
        t = self.view_start + x / self.width() * self._span()
        return max(self.view_start, min(self.view_end, t))

    # --- rysowanie ---
    def _columns(self, w: int) -> list[float]:
        """Jedna kolumna na piksel: maksimum obwiedni z próbek wpadających w kolumnę.

        Przy dużym zoomie próbek jest mniej niż kolumn — wtedy odwrotnie: każda
        kolumna czyta próbkę ze swojego czasu (inaczej fala byłaby dziurawa)."""
        n = len(self.env)
        if n == 0 or self.duration <= 0 or w <= 0:
            return []
        cols = [0.0] * w
        i_lo = max(0, int(self.view_start / self.duration * n))
        i_hi = min(n, int(self.view_end / self.duration * n) + 1)
        if i_hi - i_lo >= w:
            for i in range(i_lo, i_hi):
                x = int(self._t2x(i / n * self.duration))
                if 0 <= x < w and self.env[i] > cols[x]:
                    cols[x] = self.env[i]
        else:
            span = self._span()
            for x in range(w):
                i = int((self.view_start + (x + 0.5) / w * span) / self.duration * n)
                if 0 <= i < n:
                    cols[x] = self.env[i]
        return cols

    def _ensure_wave_cache(self, tokens: dict) -> None:
        key = (len(self.env), round(self.view_start, 6), round(self.view_end, 6),
               self.width(), self.height(),
               tokens["text_muted"], tokens["text_disabled"])
        if key == self._cache_key and self._wave_cache is not None:
            return
        w, plot_h = self.width(), self._plot_h()
        dpr = self.devicePixelRatioF()
        cols = self._columns(w)
        mid = plot_h / 2
        out = []
        for color in (tokens["text_muted"], tokens["text_disabled"]):
            pm = QPixmap(max(1, int(w * dpr)), max(1, int(plot_h * dpr)))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.transparent)
            q = QPainter(pm)
            q.setRenderHint(QPainter.Antialiasing, False)   # 1 px kolumny mają być ostre
            q.setPen(QPen(QColor(color), 1))
            for x, amp in enumerate(cols):
                if amp <= 0:
                    continue
                half = amp * (mid - 4)
                q.drawLine(x, int(mid - half), x, int(mid + half))
            q.end()
            out.append(pm)
        self._wave_cache, self._wave_cache_dim = out
        self._cache_key = key

    def paintEvent(self, _):
        p = QPainter(self)
        t = current_tokens(QApplication.instance())
        w, h = self.width(), self.height()
        plot_h = self._plot_h()
        p.fillRect(self.rect(), QColor(t["surface"]))
        if not self.env or self.duration <= 0:
            p.setPen(QColor(t["text_muted"]))
            p.setFont(make_font("font_ui_small"))
            p.drawText(self.rect(), Qt.AlignCenter, _TR("wave_empty"))
            self._paint_focus(p, t)
            return

        xs, xe = int(self._t2x(self.trim_start)), int(self._t2x(self.trim_end))
        # tło zakresu Od..Do
        if xe > xs:
            p.fillRect(xs, 0, xe - xs, plot_h, QColor(t["accent_subtle"]))

        self._ensure_wave_cache(t)
        if self._wave_cache is not None:
            p.drawPixmap(0, 0, self._wave_cache)
            # poza zakresem: przyciemnienie tła + fala w kolorze „wyłączonym"
            dim = QColor(t["bg"])
            dim.setAlpha(130)
            for x0, x1 in ((0, xs), (xe, w)):
                if x1 <= x0:
                    continue
                p.fillRect(x0, 0, x1 - x0, plot_h, dim)
                p.save()
                p.setClipRect(x0, 0, x1 - x0, plot_h)
                p.drawPixmap(0, 0, self._wave_cache_dim)
                p.restore()

        # onsety (w widoku) — warstwa przełączana klawiszem O
        if self.show_onsets:
            onset = QColor(t["success"])
            onset.setAlpha(130)
            p.setPen(QPen(onset, 1))
            for o in self.onsets:
                if self._in_view(o):
                    x = int(self._t2x(o))
                    p.drawLine(x, 0, x, plot_h)

        # strzały sesji — znaczniki od 1/3 wysokości w dół, żeby nie mylić ich
        # z pełnowysokimi markerami (kotwica/playhead); zaznaczony jest grubszy
        # i w kolorze akcentu (to jego jedyne wyróżnienie poza pastylką)
        if self.shots:
            faint = QColor(t["text"])
            faint.setAlpha(120)
            top = plot_h // 3
            for i, st in enumerate(self.shots):
                if not self._in_view(st):
                    continue
                xsh = int(self._t2x(st))
                if i == self.selected_shot:
                    p.setPen(QPen(QColor(t["accent"]), 3))
                else:
                    p.setPen(QPen(faint, 1))
                p.drawLine(xsh, top, xsh, plot_h)

        # uchwyty przycięcia (info — zieleń/czerwień są zarezerwowane dla stanów)
        p.setPen(QPen(QColor(t["info"]), 2))
        p.drawLine(xs, 0, xs, plot_h)
        p.drawLine(xe, 0, xe, plot_h)

        # kotwica T0/T1 — najważniejszy marker
        if self.anchor is not None and self._in_view(self.anchor):
            p.setPen(QPen(QColor(t["accent"]), 2))
            xa = int(self._t2x(self.anchor))
            p.drawLine(xa, 0, xa, plot_h)

        # kursor podglądu (Ctrl+klik) — przerywany, żeby odróżnić go od playheada
        if self.preview_t is not None and self._in_view(self.preview_t):
            p.setPen(QPen(QColor(t["text"]), 1, Qt.DashLine))
            xp = int(self._t2x(self.preview_t))
            p.drawLine(xp, 0, xp, plot_h)

        # playhead (podgląd w ruchu) — linia ciągła 1 px
        if self.playhead_t is not None and self._in_view(self.playhead_t):
            p.setPen(QPen(QColor(t["text"]), 1))
            xh = int(self._t2x(self.playhead_t))
            p.drawLine(xh, 0, xh, plot_h)

        self._paint_markers(p, w, plot_h, t)
        self._paint_axis(p, w, h, plot_h, t)
        self._paint_focus(p, t)

    def _paint_focus(self, p: QPainter, tokens: dict) -> None:
        if self.hasFocus():
            _focus_ring(p, QRectF(self.rect()), RADIUS["r_sm"], tokens)

    @staticmethod
    def _rel_luminance(color: QColor) -> float:
        """Luminancja względna sRGB (WCAG) — do wyboru koloru tekstu na pastylce."""
        def lin(c: float) -> float:
            return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        return (0.2126 * lin(color.redF()) + 0.7152 * lin(color.greenF())
                + 0.0722 * lin(color.blueF()))

    @classmethod
    def _tag_text_color(cls, color: QColor, tokens: dict) -> str:
        """Tekst pastylki: ten z pary `text`/`bg`, który ma WIĘKSZY kontrast do tła.

        Prosty próg luminancji tła tu nie wystarcza: marker podglądu ma tło w kolorze
        `text`, więc w motywie jasnym „ciemne tło → tekst `text`" dawało czarny napis
        na czarnej pastylce. Liczymy więc kontrast do obu kandydatów i bierzemy lepszy."""
        bg_lum = cls._rel_luminance(color)

        def ratio(token: str) -> float:
            lum = cls._rel_luminance(QColor(tokens[token]))
            hi, lo = max(bg_lum, lum), min(bg_lum, lum)
            return (hi + 0.05) / (lo + 0.05)

        return tokens["bg"] if ratio("bg") >= ratio("text") else tokens["text"]

    def _tag_rect(self, fm: QFontMetrics, x: int, text: str, align: str, row: int) -> QRect:
        pad = SPACING["sp_1"]
        bw = fm.horizontalAdvance(text) + 2 * pad
        if align == "left":
            bx = x
        elif align == "right":
            bx = x - bw
        else:
            bx = x - bw // 2
        bx = max(0, min(bx, self.width() - bw))
        return QRect(int(bx), row * (_TAG_H + 2), bw, _TAG_H)

    def _draw_tag(self, p: QPainter, rect: QRect, text: str, color: QColor,
                  text_color: str) -> None:
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.drawRoundedRect(rect, RADIUS["r_sm"], RADIUS["r_sm"])
        p.setRenderHint(QPainter.Antialiasing, False)
        p.setBrush(Qt.NoBrush)
        p.setPen(QColor(text_color))
        p.drawText(rect, Qt.AlignCenter, text)

    def _paint_markers(self, p: QPainter, w: int, plot_h: int, t: dict):
        """Krawędzie nagrania (bez pastylek) + pastylki T0/Od/Do/podglądu.

        Etykiety układane są w dwóch rzędach; przy trzeciej kolizji zostaje sam
        znacznik, a tekst wędruje do tooltipa (priorytet: T0 > Od/Do > podgląd)."""
        p.setFont(make_font("font_ui_small"))
        fm = QFontMetrics(p.font())

        # krawędzie wideo — przerywane, bez etykiet (podziałka osi wystarczy)
        p.setPen(QPen(QColor(t["text_muted"]), 1, Qt.DashLine))
        for edge_t in (0.0, self.duration):
            if self._in_view(edge_t):
                xe = int(self._t2x(edge_t))
                p.drawLine(xe, 0, xe, plot_h)

        items: list[tuple[int, str, QColor, str]] = []
        if self.anchor is not None and self._in_view(self.anchor):
            items.append((int(self._t2x(self.anchor)),
                          f"{self.anchor_label} {_fmt_axis_time(round(self.anchor, 1))}",
                          QColor(t["accent"]), t["accent_text"]))
        if self._in_view(self.trim_start):
            items.append((int(self._t2x(self.trim_start)),
                          f"Od {_fmt_axis_time(round(self.trim_start, 1))}", QColor(t["info"]), ""))
        if self._in_view(self.trim_end):
            items.append((int(self._t2x(self.trim_end)),
                          f"Do {_fmt_axis_time(round(self.trim_end, 1))}", QColor(t["info"]), ""))
        if self.playhead_t is not None and self._in_view(self.playhead_t):
            items.append((int(self._t2x(self.playhead_t)),
                          f"▶ {_fmt_axis_time(round(self.playhead_t, 1))}",
                          QColor(t["text"]), ""))
        if self.preview_t is not None and self._in_view(self.preview_t):
            items.append((int(self._t2x(self.preview_t)),
                          f"⊹ {_fmt_axis_time(round(self.preview_t, 1))}", QColor(t["text"]), ""))
        # strzały na końcu listy = najniższy priorytet (T0/Od/Do wygrywają miejsce)
        for i, st in enumerate(self.shots):
            if not self._in_view(st):
                continue
            if i == self.selected_shot:
                items.append((int(self._t2x(st)), f"#{i + 1}", QColor(t["accent"]),
                              t["accent_text"]))
            else:
                items.append((int(self._t2x(st)), f"#{i + 1}", QColor(t["text_muted"]), ""))

        placed: list[list[QRect]] = [[], []]
        self._hidden_tags = []
        for x, text, color, forced in items:
            drawn = False
            for row in (0, 1):
                rect = self._tag_rect(fm, x, text, "center", row)
                if any(rect.intersects(o) for o in placed[row]):
                    continue
                placed[row].append(rect)
                self._draw_tag(p, rect, text, color,
                               forced or self._tag_text_color(color, t))
                drawn = True
                break
            if not drawn:
                self._hidden_tags.append((x, text))

    def _paint_axis(self, p: QPainter, w: int, h: int, plot_h: int, t: dict):
        """Rysuje oś czasu (podziałka + etykiety) dla aktualnego okna widoku."""
        p.setFont(make_font("font_ui_small"))
        fm = QFontMetrics(p.font())
        p.setPen(QPen(QColor(t["border"]), 1))
        p.drawLine(0, plot_h, w, plot_h)

        step = _nice_tick_step(self._span(), w)
        tick = math.ceil(self.view_start / step) * step
        while tick <= self.view_end + 1e-6:
            x = int(self._t2x(tick))
            p.setPen(QPen(QColor(t["border"]), 1))
            p.drawLine(x, plot_h, x, plot_h + 4)
            p.setPen(QColor(t["text_muted"]))
            label = _fmt_axis_time(round(tick, 3))
            lw = fm.horizontalAdvance(label)
            lx = max(2, min(x - lw // 2, w - lw - 2))
            p.drawText(lx, h - 5, label)
            tick += step

        # wskaźniki na osi: trójkąt podglądu (kontur) i playheada (wypełniony)
        for value, filled in ((self.preview_t, False), (self.playhead_t, True)):
            if value is None or not self._in_view(value):
                continue
            xp = int(self._t2x(value))
            tri = QPolygon([QPoint(xp - 4, plot_h + 1), QPoint(xp + 4, plot_h + 1),
                            QPoint(xp, plot_h + 7)])
            p.setRenderHint(QPainter.Antialiasing, True)
            if filled:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(t["text"]))
            else:
                p.setPen(QPen(QColor(t["text"]), 1))
                p.setBrush(Qt.NoBrush)
            p.drawPolygon(tri)
            p.setRenderHint(QPainter.Antialiasing, False)
            p.setPen(Qt.NoPen)
            p.setBrush(Qt.NoBrush)

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
        self._zoom(factor, cursor_t)
        e.accept()

    def keyPressEvent(self, e):
        """Klawiatura osi (skill §11): kotwica, granice przycięcia, zoom, onsety."""
        if self.duration <= 0:
            super().keyPressEvent(e)
            return
        key = e.key()
        step = self.KEY_STEP_FAST if e.modifiers() & Qt.ShiftModifier else self.KEY_STEP
        center = (self.view_start + self.view_end) / 2
        # Zaznaczony strzał PRZEJMUJE ←/→ (przesuwa strzał, nie kotwicę) —
        # inaczej trzeba by osobnego modyfikatora, a zaznaczenie i tak jest
        # stanem chwilowym: Escape (lub klik obok) oddaje strzałki kotwicy.
        if self.selected_shot is not None:
            if key in (Qt.Key_Delete, Qt.Key_Backspace):
                self.shotDeleted.emit(self.selected_shot)
                e.accept()
                return
            if key == Qt.Key_Escape:
                self.select_shot(None)
                e.accept()
                return
            if key in (Qt.Key_Left, Qt.Key_Right):
                i = self.selected_shot
                new_t = max(0.0, min(self.duration, self.shots[i]
                                     + (step if key == Qt.Key_Right else -step)))
                self.shots[i] = new_t
                self._ensure_visible(new_t)
                self.update()
                self.shotMoved.emit(i, new_t)
                e.accept()
                return
        if key in (Qt.Key_Left, Qt.Key_Right):
            base = self.anchor if self.anchor is not None else self.trim_start
            self.commit_anchor(base + (step if key == Qt.Key_Right else -step))
        elif key == Qt.Key_Home:
            self.commit_anchor(self.trim_start)
        elif key == Qt.Key_End:
            self.commit_anchor(self.trim_end)
        elif key in (Qt.Key_Plus, Qt.Key_Equal):
            self._zoom(0.8, center)
        elif key == Qt.Key_Minus:
            self._zoom(1.25, center)
        elif key == Qt.Key_0:
            self.fit_view()
        elif key == Qt.Key_I:
            self._set_in_out("start", self.current_t())
        elif key == Qt.Key_O and e.modifiers() & Qt.ShiftModifier:
            # Shift+O zostaje przy starym znaczeniu (warstwa onsetów),
            # samo O przejmuje rolę punktu „Do” z konwencji edytorów wideo.
            self.show_onsets = not self.show_onsets
            self.update()
        elif key == Qt.Key_O:
            self._set_in_out("end", self.current_t())
        elif key == Qt.Key_T:
            self.commit_anchor(self.current_t())
        elif key == Qt.Key_M:
            self.addShotAt.emit(self.current_t())
        else:
            super().keyPressEvent(e)
            return
        e.accept()

    def _set_in_out(self, which: str, t: float) -> None:
        """I/O — granica przycięcia w bieżącym czasie; sygnał ten sam co przy myszy."""
        t = max(0.0, min(self.duration, t))
        if which == "start":
            self.trim_start = min(t, self.trim_end - 0.05)
        else:
            self.trim_end = max(t, self.trim_start + 0.05)
        self.update()
        self.trimChanged.emit(self.trim_start, self.trim_end)

    def commit_anchor(self, t: float) -> None:
        """Ustawia kotwicę z klawiatury — jak klik myszą (ten sam sygnał)."""
        t = max(0.0, min(self.duration, t))
        self._ensure_visible(t)
        self.set_anchor(t)
        self.anchorChanged.emit(t)

    def _ensure_visible(self, t: float) -> None:
        """Przesuwa widok (bez zmiany zoomu), gdy kotwica wyjedzie poza okno."""
        span = self._span()
        if t < self.view_start:
            self.view_start, self.view_end = max(0.0, t), max(0.0, t) + span
        elif t > self.view_end:
            self.view_end = min(self.duration, t)
            self.view_start = max(0.0, self.view_end - span)

    def mouseDoubleClickEvent(self, _):
        self.fit_view()

    def mousePressEvent(self, e):
        if self.duration <= 0:
            return
        self.setFocus(Qt.MouseFocusReason)
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
        # Priorytet trafień: uchwyty Od/Do → marker strzału → kotwica. Uchwyty
        # zostają pierwsze (bez nich nie dałoby się chwycić granicy stojącej na
        # strzale), a marker strzału wyprzedza kotwicę, bo klik w kotwicę można
        # powtórzyć kilka pikseli obok, a w strzał — nie.
        if abs(x - self._t2x(self.trim_start)) <= _HANDLE_PX:
            self._drag = "start"
        elif abs(x - self._t2x(self.trim_end)) <= _HANDLE_PX:
            self._drag = "end"
        elif (hit := self._shot_at_x(x)) is not None:
            self.selected_shot = hit
            self._drag = "shot"
            self._shot_drag_from = self.shots[hit]
            self.update()
        else:
            self.selected_shot = None   # klik poza strzałem odznacza
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
            self._hover(e.position().x())
            return
        t = self._x2t(e.position().x())
        if self._drag == "shot":
            # podgląd w trakcie — commit (sygnał) dopiero przy puszczeniu przycisku
            if self.selected_shot is not None:
                self.shots[self.selected_shot] = max(0.0, min(self.duration, t))
                self.update()
            return
        if self._drag == "start":
            self.trim_start = min(t, self.trim_end - 0.05)
        else:
            self.trim_end = max(t, self.trim_start + 0.05)
        self.update()
        self.trimChanged.emit(self.trim_start, self.trim_end)

    def _hover(self, x: float) -> None:
        """Kursor uchwytu w strefie chwytu + tooltip etykiety zdjętej przez kolizję."""
        if self.duration > 0 and (abs(x - self._t2x(self.trim_start)) <= _HANDLE_PX
                                  or abs(x - self._t2x(self.trim_end)) <= _HANDLE_PX
                                  or self._shot_at_x(x) is not None):
            self.setCursor(Qt.SizeHorCursor)
        else:
            self.setCursor(Qt.CrossCursor)
        hidden = [text for hx, text in self._hidden_tags if abs(hx - x) <= 8]
        self.setToolTip(" · ".join(hidden) if hidden else self._base_tip)

    def mouseReleaseEvent(self, _):
        if self._drag == "shot" and self.selected_shot is not None:
            new_t = self.shots[self.selected_shot]
            if self._shot_drag_from is None or abs(new_t - self._shot_drag_from) > 1e-6:
                self.shotMoved.emit(self.selected_shot, new_t)
        self._shot_drag_from = None
        self._drag = None
        if self._pan is not None:
            self._pan = None
            self.setCursor(Qt.CrossCursor)


def _pil_to_pixmap(img: "Image.Image") -> QPixmap:
    """Pillow RGBA → QPixmap. WOLNO wołać wyłącznie z wątku GUI (Qt tak wymaga)."""
    qim = ImageQt(img.convert("RGBA"))
    return QPixmap.fromImage(QImage(qim))


# Miniatura klatki w wierszu kolejki renderów (v0.53.0): rozmiar logiczny stały,
# ekstrakcja idzie w niskiej rozdzielczości (`_QUEUE_THUMB_EXTRACT_H`) — miniatura
# i tak ją pomniejsza dalej.
_QUEUE_THUMB_W = 96
_QUEUE_THUMB_H = 54
_QUEUE_THUMB_EXTRACT_H = 108


def _queue_thumb_pixmap(frame: "Image.Image | None") -> QPixmap:
    """Miniatura wiersza kolejki: klatka wyśrodkowana (letterbox w tle `surface`,
    rogi zaokrąglone `RADIUS['r_sm']`) albo — gdy `frame` to None (jeszcze nie
    wyciągnięta / ekstrakcja się nie powiodła) — placeholder ikony „play-file"
    w kolorze `text_muted`. WOLNO wołać wyłącznie z wątku GUI (jak `_pil_to_pixmap`)."""
    app = QApplication.instance()
    tokens = current_tokens(app)
    dpr = app.devicePixelRatio() if app is not None else 1.0
    w, h = _QUEUE_THUMB_W, _QUEUE_THUMB_H
    img = QImage(max(1, round(w * dpr)), max(1, round(h * dpr)), QImage.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(Qt.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, w, h), RADIUS["r_sm"], RADIUS["r_sm"])
    painter.setClipPath(path)
    painter.fillRect(QRectF(0, 0, w, h), QColor(tokens["surface"]))
    if frame is not None:
        src = _pil_to_pixmap(frame)
        scaled = src.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        x = (w - scaled.width()) / 2
        y = (h - scaled.height()) / 2
        painter.drawPixmap(QPointF(x, y), scaled)
    else:
        ic = ui_theme.icon("play-file", color=tokens["text_muted"], size=20)
        pm = ic.pixmap(20, 20)
        x = (w - pm.width()) / 2
        y = (h - pm.height()) / 2
        painter.drawPixmap(QPointF(x, y), pm)
    painter.end()
    return QPixmap.fromImage(img)


def _job_thumb_source(video_path: str) -> str:
    """Źródło klatki dla miniatury kolejki: proxy 540p → LRF → oryginał.

    Kolejność jak `MainWindow._frame_src`, ale zaczyna od proxy — miniatura nie
    musi czekać na LRF, gdy proxy już jest gotowe (i vice versa, gdy proxy jeszcze
    się buduje). Każde z tych źródeł jest małe, więc ekstrakcja jest szybka."""
    proxy = config.find_proxy(video_path)
    if proxy is not None:
        return str(proxy)
    lrf = ffmpeg.find_lrf(video_path)
    if lrf is not None:
        return str(lrf)
    return video_path


def _job_thumb_anchor(job: "RenderJob") -> float:
    """Czas klatki miniatury: środek okna przycięcia, albo T0+1s, albo 0."""
    kw = job.kwargs
    ts, te = kw.get("trim_start"), kw.get("trim_end")
    if ts is not None and te is not None:
        return (ts + te) / 2
    t0 = kw.get("t0")
    if t0 is not None:
        return t0 + 1.0
    return 0.0


class QueueThumbWorker(QThread):
    """Wyciąga JEDNĄ klatkę-miniaturę dla wiersza kolejki renderów.

    Osobny od `FrameExtractWorker` (ten sam wzorzec: FFmpeg w tle, PIL.Image
    przez sygnał, konwersja na QPixmap dopiero w wątku GUI), bo niesie `job_id`
    — wynik musi trafić do właściwego wiersza, nawet gdy w międzyczasie inne
    zadania zostały dodane/usunięte z kolejki.
    """
    done = Signal(str, object)   # (job_id, PIL.Image)
    failed = Signal(str, str)    # (job_id, komunikat)

    def __init__(self, job_id: str, video_path: str, anchor_t: float):
        super().__init__()
        self.job_id = job_id
        self.video_path = video_path
        self.anchor_t = anchor_t

    def run(self):
        try:
            with tempfile.TemporaryDirectory() as tmp:
                frame_png = ffmpeg.extract_frame(
                    self.video_path, self.anchor_t,
                    Path(tmp) / "t.png", scale_height=_QUEUE_THUMB_EXTRACT_H)
                frame = Image.open(frame_png).convert("RGBA")
                frame.load()
            self.done.emit(self.job_id, frame)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(self.job_id, str(exc))


class VideoPlayerPage(QGraphicsView):
    """Podgląd w ruchu: klatka z `QGraphicsVideoItem` + nakładki jako pixmapy.

    Dlaczego scena, a nie „klatka z QVideoSink przemalowana Pillow": dekodowanie
    i skalowanie wideo zostaje po stronie Qt/FFmpeg (zero kopii przez Pythona na
    każdą klatkę), a nakładki są policzone RAZ na przebudowę i tylko przełączane
    widocznością wg czasu — dokładnie tak, jak robi to filtergraph w renderze.

    Układ współrzędnych sceny = piksele płótna nakładek (`set_canvas`), więc
    pozycje paneli liczy ta sama funkcja co render (`render._overlay_xy`).
    """

    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.NoFrame)
        self.setRenderHints(QPainter.SmoothPixmapTransform | QPainter.Antialiasing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.NoFocus)   # fokus należy do osi i paska transportu
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.video_item = QGraphicsVideoItem()
        self._scene.addItem(self.video_item)
        self._events: list[tuple[QGraphicsPixmapItem, float, float]] = []
        self._clock_item: QGraphicsPixmapItem | None = None
        self.refresh_theme()

    def refresh_theme(self) -> None:
        """Tło sceny = token `bg` (letterbox nie może być czarną plamą, skill §9)."""
        self.setBackgroundBrush(QColor(current_tokens(QApplication.instance())["bg"]))

    def set_canvas(self, size: tuple[int, int]) -> None:
        self.video_item.setSize(QSizeF(size[0], size[1]))
        self.video_item.setPos(0, 0)
        self._scene.setSceneRect(QRectF(QPointF(0, 0), QSizeF(size[0], size[1])))
        self.fit()

    def fit(self) -> None:
        rect = self._scene.sceneRect()
        if rect.width() > 0 and rect.height() > 0:
            self.fitInView(rect, Qt.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit()

    def clear_overlays(self) -> None:
        for item, _, _ in self._events:
            self._scene.removeItem(item)
        self._events = []
        self.set_clock(None)

    def set_overlays(self, items: list[tuple[QPixmap, int, int, float, float]]) -> None:
        self.clear_overlays()
        for pix, x, y, start, end in items:
            item = QGraphicsPixmapItem(pix)
            item.setPos(x, y)
            item.setZValue(1)
            item.setVisible(False)
            self._scene.addItem(item)
            self._events.append((item, start, end))

    def set_clock(self, pix: QPixmap | None, xy: tuple[int, int] = (0, 0)) -> None:
        if pix is None:
            if self._clock_item is not None:
                self._scene.removeItem(self._clock_item)
                self._clock_item = None
            return
        if self._clock_item is None:
            self._clock_item = QGraphicsPixmapItem()
            self._clock_item.setZValue(2)
            self._scene.addItem(self._clock_item)
        self._clock_item.setPixmap(pix)
        self._clock_item.setPos(*xy)

    def update_time(self, t: float) -> None:
        """Przełącza widoczność nakładek wg czasu klatki (okna jak w renderze)."""
        for item, start, end in self._events:
            item.setVisible(start <= t < end)


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
        self.setMouseTracking(True)   # kursor „łapki" nad nakładką bez wciśniętego LPM
        # Prostokąty nakładek (piksele KLATKI) — rysowane tylko w trybie edycji.
        self.rects: dict[str, tuple[int, int, int, int]] = {}

    def set_edit_rects(self, rects: dict[str, tuple[int, int, int, int]]) -> None:
        self.rects = dict(rects)
        if self.edit_mode:
            self.update()

    def set_edit_mode(self, on: bool) -> None:
        self.edit_mode = on
        self.update()

    def _to_widget(self, r: tuple[int, int, int, int]) -> QRect | None:
        """Prostokąt z pikseli klatki na piksele widżetu (odwrotność `_to_frame`)."""
        if not self._disp or not self._frame_size or self._frame_size[0] <= 0:
            return None
        fw, fh = self._frame_size
        sx = self._disp.width() / fw
        sy = self._disp.height() / fh
        return QRect(int(self._disp.x() + r[0] * sx), int(self._disp.y() + r[1] * sy),
                     max(1, int(r[2] * sx)), max(1, int(r[3] * sy)))

    def paintEvent(self, e):
        super().paintEvent(e)
        if not self.edit_mode or not self.rects:
            return
        t = current_tokens(QApplication.instance())
        p = QPainter(self)
        p.setFont(make_font("font_ui_small"))
        accent = QColor(t["accent"])
        for key, r in self.rects.items():
            wr = self._to_widget(r)
            if wr is None:
                continue
            p.setPen(QPen(accent, 1))
            p.setBrush(Qt.NoBrush)
            p.drawRect(wr)
            label = _TR("rect_" + key)
            # podpis nad ramką, a gdy nie ma miejsca — pod jej górną krawędzią
            ly = wr.top() - 4 if wr.top() > 16 else wr.top() + 14
            p.drawText(wr.left() + 2, ly, label)
        p.end()

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
        if self.edit_mode and not e.buttons():
            f = self._to_frame(e.position())
            over = bool(f) and any(
                r[0] <= f[0] <= r[0] + r[2] and r[1] <= f[1] <= r[1] + r[3]
                for r in self.rects.values())
            self.setCursor(Qt.OpenHandCursor if over else Qt.ArrowCursor)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.edit_mode and e.button() == Qt.LeftButton:
            self.dropped.emit()
        super().mouseReleaseEvent(e)


# ----------------------------- okno główne -----------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.session: Session | None = None
        # Surowa sesja z API — `self.session` to ona PO nałożeniu pól „Tor”/
        # „Uczestnik” (edycja pól przelicza `self.session` z tej kopii).
        self._api_session: Session | None = None
        self.video_path: str | None = None
        self.lrf_path: str | None = None
        # Proxy podglądu (540p) — patrz `_maybe_start_proxy`. `_proxy_path` jest
        # ustawione dopiero gdy proxy REALNIE istnieje; `_proxy_wanted` trzyma
        # ścieżkę nagrania, dla którego proxy dopiero trzeba zbudować.
        self._proxy_path: str | None = None
        self._proxy_wanted: str | None = None
        self._proxy_poll_queued: bool = False
        self._proxy_building: bool = False
        self._proxy_started_at: float = 0.0
        self._proxy_status_at: float = 0.0
        self._op_progress_text: str = ""
        self.worker: RenderWorker | None = None
        self.wave_worker: WaveformWorker | None = None
        # Operacje w tle (detekcje, API): jeden worker naraz + token pokolenia.
        self._op_workers: list[FuncWorker] = []
        self._op_worker: FuncWorker | None = None
        self._op_button: QPushButton | None = None
        self._op_buttons: list[QPushButton] = []
        self._op_gen: int = 0
        self._video_size: tuple[int, int] | None = None  # (w, h) — do skalowania podglądu
        self._video_info: ffmpeg.VideoInfo | None = None  # pełny probe (dopasowanie po czasie)
        # Zapisane ustawienia tego pliku, czekające na zastosowanie po analizie audio
        # (spiny czasu mają sensowny zakres dopiero po poznaniu długości nagrania).
        self._pending_file_settings: dict | None = None
        # Pochodzenie T0 bieżącego pliku (patrz `_set_t0`/`_collect_file_settings`):
        # 0 = ustawiony ręcznie (nigdy nie proponujemy nowej detekcji), >=1 =
        # wersja `audio_sync.START_DETECTOR_VERSION` z chwili automatycznej
        # detekcji. Ustawiane też przy wczytaniu `file_settings.json` (może
        # zostać None = nieznana/przestarzała wersja z wpisu sprzed śledzenia).
        self._t0_detector: int | None = 0
        self._suppress_manual_t0: bool = False
        # True od momentu, gdy `_maybe_recheck_t0` uzna sprawdzenie za potrzebne,
        # do momentu wyniku (nawet przez oczekiwanie na wolny slot `_run_op`) —
        # tryb `--screenshot` czeka na to samo, na czym czeka na proxy/detekcję.
        self._t0_recheck_busy: bool = False
        # Akcja wpięta w `sync_msg` (np. „Użyj X s" przy przestarzałym T0) —
        # `None` gdy komunikat bez akcji.
        self._sync_action_cb: Callable[[], None] | None = None
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
        # Podgląd w ruchu — przebudowa nakładek jest kosztowna (Pillow × liczba
        # strzałów), więc idzie przez własny debounce, nie na każdy tick spinboxa.
        self._player_rebuild_timer = QTimer()
        self._player_rebuild_timer.setSingleShot(True)
        self._player_rebuild_timer.timeout.connect(self._rebuild_player_overlays)
        self.setWindowTitle(f"Piro Overlay v{__version__}")
        self.setWindowIcon(QIcon(resources.icon_path()))
        self.setAcceptDrops(True)  # drag&drop pliku
        self._build_ui()
        # `_build_toolbar` (wołane wewnątrz `_build_ui`) barwi ikony toolbara przed
        # tym, jak transport/edit_pos_btn/fit_btn/zoom_range_btn w ogóle istnieją —
        # domalowanie tamtych czeka na koniec konstrukcji.
        self._refresh_icons()

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
    # ---------- pasek akcji, pasek stanu, motyw ----------
    def _build_toolbar(self) -> None:
        """Główne akcje jako `QAction` — skrót, tooltip i stan `enabled` w jednym miejscu.

        Przyciski w formularzu zostają jako drugie wejście do TYCH SAMYCH akcji
        (`clicked → action.trigger()`), więc nic nie rozjeżdża się przy zmianie stanu.
        Ikony (`ui_theme.icon`) barwione tokenem `text` (primary „Renderuj" —
        `accent_text`, bo tło przycisku jest już akcentem); `_icon_actions` trzyma
        listę do przebarwienia po zmianie motywu (`_refresh_icons`).
        """
        tb = QToolBar("Główny")
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        tb.setIconSize(QSize(16, 16))
        self.addToolBar(tb)
        self.toolbar = tb
        self._icon_actions: list[tuple[QAction, str]] = []

        def act(key: str, shortcut: str | None, slot, tip: str, icon_name: str) -> QAction:
            a = QAction(_TR(key), self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
                a.setToolTip(f"{_TR(key)} ({shortcut})")
            else:
                a.setToolTip(tip or _TR(key))
            if tip and shortcut:
                a.setToolTip(f"{tip} ({shortcut})")
            a.triggered.connect(slot)
            tb.addAction(a)
            self._icon_actions.append((a, icon_name))
            return a

        self.act_open = act("act_open_video", "Ctrl+O", self._choose_video,
                            "Wybierz plik wideo do obróbki", "open")
        self.act_fetch = act("act_fetch_api", "Ctrl+G", self._fetch_id,
                             "Pobierz oś czasu i metadane sesji z API (po ID)", "download")
        self.act_detect_start = act("act_detect_start", "Ctrl+D", self._detect_start_signal,
                                    "Znajdź bzyczek shot-timera i ustaw go jako T0", "detect")
        self.act_auto_trim = act("act_auto_trim", "Ctrl+T", self._apply_auto_trim,
                                 "Przytnij: 5 s przed startem → ostatni strzał + margines",
                                 "trim")
        tb.addSeparator()
        self.act_queue_add = act("act_add_queue", None, self._add_to_queue,
                                 "Dodaj render z bieżącymi ustawieniami do kolejki",
                                 "queue-add")
        self.act_queue = act("act_queue", None, self._show_queue_window,
                             "Otwórz okno kolejki renderów", "queue")
        self.act_batch = act("act_batch", None, self._show_batch_window,
                             "Przetwarzanie wielu plików (tryb auto + ID)", "batch")

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)

        self.act_theme = QAction(_TR("act_theme"), self)
        self.act_theme.setCheckable(True)
        self.act_theme.setChecked(_theme_mode() == "light")
        self.act_theme.toggled.connect(self._on_theme_toggled)
        tb.addAction(self.act_theme)
        self._refresh_theme_action()

        # „Zatrzymaj" widoczne wyłącznie w trakcie renderu (akcja destrukcyjna).
        self.act_cancel = QAction(_TR("act_cancel"), self)
        self.act_cancel.setToolTip("Przerwij render i usuń niedokończony plik")
        self.act_cancel.triggered.connect(self._cancel_render)
        self.act_cancel.setVisible(False)
        tb.addAction(self.act_cancel)
        self._icon_actions.append((self.act_cancel, "cancel"))

        self.act_render = QAction(_TR("render"), self)
        self.act_render.setShortcut(QKeySequence("Ctrl+R"))
        self.act_render.setToolTip("Renderuj (Ctrl+R)")
        self.act_render.triggered.connect(self._start_render)
        # „Otwórz folder" pojawia się dopiero po udanym renderze (jak `open_btn`).
        self.act_open_folder = QAction(_TR("act_open_folder"), self)
        self.act_open_folder.setToolTip("Otwórz folder z ostatnim wyrenderowanym plikiem")
        self.act_open_folder.triggered.connect(self._open_output_folder)
        self.act_open_folder.setVisible(False)
        tb.addAction(self.act_open_folder)
        self._icon_actions.append((self.act_open_folder, "folder-open"))

        render_tb = QToolButton()
        render_tb.setDefaultAction(self.act_render)
        render_tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        render_tb.setIconSize(QSize(16, 16))
        set_kind(render_tb, "primary")
        tb.addWidget(render_tb)
        self._render_tb = render_tb

        self._refresh_icons()

    def _refresh_icons(self) -> None:
        """Retint every icon after a theme switch (colors baked into pixmaps).

        Single place for the whole app: toolbar actions, „Renderuj" (accent_text —
        its background is already the accent, `text` would be nearly invisible),
        transport buttons and the two helper windows' rows.
        """
        tokens = current_tokens(QApplication.instance())
        for a, name in getattr(self, "_icon_actions", []):
            a.setIcon(ui_theme.icon(name, size=16))
        if getattr(self, "act_render", None) is not None:
            self.act_render.setIcon(ui_theme.icon("render", color=tokens["accent_text"], size=16))
        if getattr(self, "act_theme", None) is not None:
            mode = "light" if self.act_theme.isChecked() else "dark"
            self.act_theme.setIcon(ui_theme.icon("sun" if mode == "light" else "moon", size=16))
        self._refresh_transport_icons()
        if getattr(self, "edit_pos_btn", None) is not None:
            _apply_icon(self.edit_pos_btn, "move", 18, None)
        if getattr(self, "fit_btn", None) is not None:
            _apply_icon(self.fit_btn, "fit", 18, _TR("preview_fit"))
        if getattr(self, "zoom_range_btn", None) is not None:
            _apply_icon(self.zoom_range_btn, "zoom-range", 18, _TR("preview_zoom_range"))
        if getattr(self, "save_frame_btn", None) is not None:
            _apply_icon(self.save_frame_btn, "camera", 18, _TR("save_frame"))
        if getattr(self, "match_time_btn", None) is not None:
            _apply_icon(self.match_time_btn, "clock", 18, "⏱")
        if getattr(self, "op_cancel_btn", None) is not None:
            self.op_cancel_btn.setIcon(ui_theme.icon("cancel", size=16))
        if getattr(self, "_queue_window", None) is not None:
            self._queue_window.refresh_icons()
        if getattr(self, "_batch_window", None) is not None:
            self._batch_window.refresh_icons()

    def _build_statusbar(self) -> None:
        """Postęp renderu i status NVENC na stałe w pasku stanu (`addPermanentWidget`).

        Pasek postępu ZOSTAJE widoczny z wartością 0 także poza renderem — ukrywanie
        przesuwałoby etykietę NVENC przy każdym starcie/końcu renderu (skaczący układ),
        a zerowy pasek czytelnie mówi „nic się teraz nie renderuje".
        """
        bar = self.statusBar()
        self.nvenc_label = QLabel()
        self._refresh_nvenc_status()
        bar.addPermanentWidget(self.nvenc_label)
        # „Anuluj" dotyczy operacji w tle (detekcje/API) — widoczny tylko w ich trakcie.
        self.op_cancel_btn = QPushButton(_TR("op_cancel"))
        self.op_cancel_btn.setIcon(ui_theme.icon("cancel", size=16))
        set_kind(self.op_cancel_btn, "ghost")
        self.op_cancel_btn.setToolTip("Przerywa trwającą detekcję/pobieranie")
        self.op_cancel_btn.clicked.connect(self._cancel_operation)
        self.op_cancel_btn.setVisible(False)
        bar.addPermanentWidget(self.op_cancel_btn)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setFormat("%p%")
        self.progress.setFixedWidth(180)
        self.progress.setProperty("kind", "labeled")
        bar.addPermanentWidget(self.progress)
        # Adres strony projektu (marka ShotHUD) — klikalny, po prawej stronie paska.
        site = QLabel(f'<a href="{SITE_URL}" style="color: inherit;">shothud.com</a>')
        site.setOpenExternalLinks(True)
        site.setToolTip(_TR("site_tooltip"))
        set_role(site, "muted")
        bar.addPermanentWidget(site)

    def sync_theme_action(self, mode: str) -> None:
        """Ustawia stan przełącznika BEZ ponownego nakładania motywu.

        Potrzebne dla dewelopreskiej flagi `--light`, która wymusza motyw pomijając
        `QSettings` — inaczej pasek akcji pokazywałby „Motyw: ciemny" w jasnym oknie."""
        self.act_theme.blockSignals(True)
        self.act_theme.setChecked(mode == "light")
        self.act_theme.blockSignals(False)
        self._refresh_theme_action()
        self._refresh_icons()

    def _refresh_theme_action(self) -> None:
        mode = "light" if self.act_theme.isChecked() else "dark"
        self.act_theme.setText(f"{_TR('act_theme')}: {_TR('theme_' + mode)}")

    def _on_theme_toggled(self, light: bool) -> None:
        mode = "light" if light else "dark"
        app = QApplication.instance()
        apply_theme(app, mode)
        ui_theme.clear_icon_cache()   # tokens changed — cached tints are stale
        QSettings().setValue("ui/theme", mode)
        self._refresh_theme_action()
        self._refresh_icons()
        for win in (self, self._queue_window, self._batch_window):
            if win is None:
                continue
            repolish(win)
            try:
                set_windows_dark_titlebar(win, mode == "dark")
            except Exception:  # noqa: BLE001 — offscreen nie ma uchwytu okna
                pass
        # Próbki koloru malują się z tokenów motywu — wymuś przerysowanie.
        for btn in self.findChildren(ColorSwatchButton):
            btn.update()
        # Oś czasu i ramki edycji malują się z tokenów w paintEvent — cache fali
        # unieważnia się sam (kolor jest częścią klucza), ale repaint trzeba wymusić.
        self.waveform.update()
        self.preview_label.update()
        if self.player_page is not None:
            self.player_page.refresh_theme()
        self._update_preview()

    def _build_ui(self):
        self._build_toolbar()
        self._build_statusbar()
        central = QWidget()
        root = QHBoxLayout(central)

        left = QVBoxLayout()
        left.setContentsMargins(SPACING["sp_4"], SPACING["sp_4"],
                                SPACING["sp_4"], SPACING["sp_4"])
        left.setSpacing(SPACING["sp_6"])
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
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setMinimumWidth(380)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)

        # Pasek nad podglądem: transport odtwarzania, tryb edycji, widok osi, czas.
        self._build_player()
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, SPACING["sp_2"])
        bar.setSpacing(SPACING["sp_2"])
        self._build_transport(bar)
        # „Edytuj pozycje" ma ikonę + tekst (jest przełącznikiem trybu, nazwa musi
        # być czytelna); „Dopasuj"/„Zoom Od–Do" są sam-ikonowe z tooltipem — to
        # odchudziło pasek na tyle, że „Edytuj pozycje" już się nie ucina przy 1180 px
        # (wcześniej trzy pełnotekstowe przyciski + glify transportu przepełniały bar).
        self.edit_pos_btn = QToolButton()
        self.edit_pos_btn.setText(_TR("act_edit_pos"))
        self.edit_pos_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.edit_pos_btn.setIconSize(QSize(18, 18))
        self.edit_pos_btn.setCheckable(True)
        self.edit_pos_btn.setToolTip(f"{_TR('tip_edit_pos')} (E)")
        self.edit_pos_btn.toggled.connect(self._on_edit_pos_toggled)
        bar.addWidget(self.edit_pos_btn)
        bar.addStretch(1)
        self.fit_btn = QToolButton()
        self.fit_btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.fit_btn.setIconSize(QSize(18, 18))
        set_kind(self.fit_btn, "ghost")
        self.fit_btn.setToolTip(f"{_TR('preview_fit')} — {_TR('tip_preview_fit')} (0)")
        self.fit_btn.clicked.connect(self._on_fit_view)
        bar.addWidget(self.fit_btn)
        self.zoom_range_btn = QToolButton()
        self.zoom_range_btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.zoom_range_btn.setIconSize(QSize(18, 18))
        set_kind(self.zoom_range_btn, "ghost")
        self.zoom_range_btn.setToolTip(f"{_TR('preview_zoom_range')} — "
                                       f"{_TR('tip_preview_zoom_range')}")
        self.zoom_range_btn.clicked.connect(self._on_zoom_range)
        bar.addWidget(self.zoom_range_btn)
        self.save_frame_btn = QToolButton()
        self.save_frame_btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.save_frame_btn.setIconSize(QSize(18, 18))
        set_kind(self.save_frame_btn, "ghost")
        self.save_frame_btn.setToolTip(f"{_TR('save_frame')} — {_TR('tip_save_frame')} (Ctrl+S)")
        self.save_frame_btn.clicked.connect(self._on_save_frame)
        self.save_frame_btn.setEnabled(False)   # bez wideo nie ma czego zapisać
        bar.addWidget(self.save_frame_btn)
        # Etykieta trybu edycji nie może się skracać do „Ed…ycje" — to przełącznik
        # trybu, jego nazwa jest ważniejsza niż kilka pikseli w wąskim oknie.
        self.edit_pos_btn.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.preview_time_label = QLabel("")
        set_role(self.preview_time_label, "mono")
        bar.addWidget(self.preview_time_label)
        right.addLayout(bar)

        self.preview_label = PreviewLabel("Przeciągnij tu plik wideo lub użyj „…”")
        self.preview_label.setMinimumSize(480, 270)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setProperty("role", "preview")
        self.preview_label.grabbed.connect(self._on_preview_grab)
        self.preview_label.dragged.connect(self._on_preview_drag)
        self.preview_label.dropped.connect(self._on_preview_drop)
        # Stan pusty i podgląd żyją na dwóch stronach stosu — `preview_label`
        # ZOSTAJE tym samym obiektem (używa go scrubber i przeciąganie pozycji).
        self.preview_stack = QStackedWidget()
        self.preview_stack.addWidget(self._empty_state_page())
        self.preview_stack.addWidget(self.preview_label)
        self.preview_stack.addWidget(self._loading_page())
        if self.player_page is not None:
            self.preview_stack.addWidget(self.player_page)
        right.addWidget(self.preview_stack, 3)

        self.waveform = WaveformWidget()
        self.waveform.anchorChanged.connect(self._on_wave_anchor)
        self.waveform.trimChanged.connect(self._on_wave_trim)
        self.waveform.previewAt.connect(self._on_preview_at)
        self.waveform.addShotAt.connect(self._on_wave_add_shot)
        self.waveform.shotMoved.connect(self._on_wave_shot_moved)
        self.waveform.shotDeleted.connect(self._on_wave_shot_deleted)
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
        splitter.setChildrenCollapsible(False)   # nikt nie zgubi inspektora przypadkiem
        splitter.setHandleWidth(9)                # 1 px linii + margines = strefa chwytu
        splitter.setSizes([420, 760])
        self.splitter = splitter   # restore_window_state/save_window_state (QSettings)
        root.addWidget(splitter)

        # Etykieta kotwicy (T0/T1) zależy od trybu — podłączamy po utworzeniu waveformu.
        self.anchor_combo.currentIndexChanged.connect(self._on_anchor_mode_changed)
        self._on_anchor_mode_changed()

        # Wczytaj ostatni styl z dysku (jeśli istnieje) — bez triggerowania autosave.
        last_style = config.load_last_style()
        if last_style is not None:
            self._apply_style(last_style)

        # Przyciski, które zmieniałyby wejście długiej operacji — blokowane na jej czas
        # (nie cały inspektor: zmiana koloru panelu w trakcie detekcji nikomu nie szkodzi).
        self._op_buttons = [self.fetch_btn, self.fetch_trim_btn, self.detect_id_btn,
                            self.match_time_btn,
                            self.detect_btn, self.next_btn, self.start_sig_btn,
                            self.autotrim_btn, self.save_frame_btn]
        # Escape wychodzi z trybu „Edytuj pozycje" (skill §11: tryb zawsze z wyjściem).
        QShortcut(QKeySequence.Cancel, self, self._escape_edit_pos)
        # „E" przełącza tryb edycji — ale nie wtedy, gdy użytkownik pisze w polu.
        QShortcut(QKeySequence("E"), self, self._shortcut_edit_pos)
        # Ctrl+S = „Zapisz klatkę" — skrót okna z modyfikatorem, działa nawet gdy
        # fokus jest w polu tekstowym (w przeciwieństwie do gołego „E").
        QShortcut(QKeySequence("Ctrl+S"), self, self._on_save_frame)
        # Transport z klawiatury (skill §11). Wszystkie skróty przechodzą przez
        # `_transport_shortcut`, który odpuszcza, gdy fokus jest w polu tekstowym.
        for keys, slot in (
            ("J", partial(self._seek_by, -_SEEK_STEP_S)),
            ("K", self._pause),
            ("L", partial(self._seek_by, _SEEK_STEP_S)),
            (",", partial(self._seek_frames, -1)),
            (".", partial(self._seek_frames, 1)),
            ("Home", self._home_key),
            ("End", self._end_key),
        ):
            QShortcut(QKeySequence(keys), self, partial(self._transport_shortcut, slot))
        QShortcut(QKeySequence(Qt.Key_Space), self,
                  partial(self._transport_shortcut, self._toggle_play, True))
        self._update_preview_time()
        self._set_render_enabled(True)   # bez wideo „Renderuj" jest wyłączone

        self.setCentralWidget(central)

    def _empty_state_page(self) -> QWidget:
        """Stan pusty podglądu: co to jest, co zrobić, czym to zrobić (skill §10)."""
        page = QWidget()
        v = QVBoxLayout(page)
        v.setSpacing(SPACING["sp_3"])
        v.addStretch(1)
        title = QLabel(_TR("empty_title"))
        set_role(title, "title")
        title.setAlignment(Qt.AlignCenter)
        hint = QLabel(_TR("empty_hint"))
        set_role(hint, "muted")
        hint.setAlignment(Qt.AlignCenter)
        btn = QPushButton(_TR("act_open_video"))
        set_kind(btn, "primary")
        btn.setToolTip(_TR("tip_choose_video"))
        btn.clicked.connect(self.act_open.trigger)
        brow = QHBoxLayout()
        brow.addStretch(1); brow.addWidget(btn); brow.addStretch(1)
        v.addWidget(title)
        v.addWidget(hint)
        v.addLayout(brow)
        v.addStretch(1)
        return page

    def _loading_page(self) -> QWidget:
        """Stan „pracuję" podglądu: co się dzieje + nieokreślony postęp (skill §10)."""
        page = QWidget()
        self.loading_page = page
        v = QVBoxLayout(page)
        v.setSpacing(SPACING["sp_3"])
        v.addStretch(1)
        self.loading_label = QLabel(_TR("busy_audio"))
        set_role(self.loading_label, "muted")
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_bar = QProgressBar()
        self.loading_bar.setRange(0, 0)      # nieokreślony — długość analizy nieznana
        self.loading_bar.setTextVisible(False)
        self.loading_bar.setFixedWidth(120)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.loading_bar)
        row.addStretch(1)
        v.addWidget(self.loading_label)
        v.addLayout(row)
        v.addStretch(1)
        return page

    def _show_loading(self, text: str, busy: bool = True) -> None:
        self.loading_label.setText(text)
        self.loading_bar.setRange(0, 0) if busy else self.loading_bar.setRange(0, 100)
        self.preview_stack.setCurrentWidget(self.loading_page)

    def _update_preview_time(self) -> None:
        """„▶ czas / długość" w pasku nad podglądem — format z `_fmt_axis_time`."""
        dur = self.waveform.duration
        if dur <= 0:
            self.preview_time_label.setText("")
            return
        t = self.waveform.playhead_t
        if t is None:
            t = self.waveform.preview_t
        if t is None:
            t = self.t0_spin.value()
        # dziesiąte sekundy wystarczą — surowa długość („20,0156s") jest nieczytelna
        self.preview_time_label.setText(
            f"▶ {_fmt_axis_time(round(t, 1))} / {_fmt_axis_time(round(dur, 1))}")

    def _on_fit_view(self) -> None:
        self.waveform.fit_view()

    def _on_zoom_range(self) -> None:
        self.waveform.zoom_to_trim()

    def _current_still_time(self) -> float:
        """Czas klatki do zapisu — to samo źródło co pasek „▶ czas" nad podglądem:
        pozycja playera (gdy aktywny) → kursor podglądu (scrubber/przewinięcie
        osi) → T0+1 s, gdy nic jeszcze nie wskazano (świeżo wczytany plik)."""
        if self._player_active():
            return self.player.position() / 1000.0
        if self.waveform.preview_t is not None:
            return self.waveform.preview_t
        if self.waveform.playhead_t is not None:
            return self.waveform.playhead_t
        return self.t0_spin.value() + 1.0

    def _save_frame_path(self, t: float) -> str:
        """Domyślna nazwa `<stem>_<czas>s.png` w ostatnim katalogu wyjściowym."""
        p = Path(self.video_path)
        time_str = _fmt_time_s(round(max(t, 0.0), 2)).replace(",", ".")
        start_dir = config.load_last_dir("output") or str(p.parent)
        return str(Path(start_dir) / f"{p.stem}_{time_str}s.png")

    def _on_save_frame(self) -> None:
        """„Zapisz klatkę" — PNG z nakładką w pełnej rozdzielczości źródła.

        Dialog PRZED pracą w tle (użytkownik wybiera plik, zanim FFmpeg zacznie
        wyciągać klatkę z oryginału — z 4K/HEVC to sekundy, nie chcemy, żeby
        czekał na wynik, którego jeszcze nie umieścił)."""
        if not self._require_video():
            return
        t = self._current_still_time()
        default_path = self._save_frame_path(t)
        path, _ = QFileDialog.getSaveFileName(
            self, _TR("save_frame"), default_path, "PNG (*.png)")
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        config.save_last_dir("output", Path(path).parent)
        session = self.session or self._safe_session()
        style = self.current_style()
        mode = self._anchor_mode()
        first_shot = session.shots[0].czas if session and session.shots else 0.0
        t0 = audio_sync.resolve_t0(self.t0_spin.value(), mode, first_shot)
        duration = self.waveform.duration or (t + 10.0)
        video_path = self.video_path

        def fn():
            img = preview.render_still(video_path, t, session, t0, style, duration)
            img.save(path)
            return path

        self._run_op(fn, button=self.save_frame_btn,
                     busy_text=_TR("busy_save_frame"),
                     status_text=_TR("busy_save_frame"),
                     on_result=self._on_frame_saved,
                     on_error=lambda msg: self._notify(
                         "input", _TR("msg_save_frame_failed").format(msg)))

    def _on_frame_saved(self, path: str) -> None:
        self._ok(_TR("msg_frame_saved").format(Path(path).name))

    def _shortcut_edit_pos(self) -> None:
        """„E" przełącza tryb edycji tylko poza polami tekstowymi (skill §11)."""
        fw = QApplication.focusWidget()
        if isinstance(fw, (QLineEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox)):
            return
        self.edit_pos_btn.toggle()

    def _escape_edit_pos(self) -> None:
        # Skrót okna ma pierwszeństwo przed `keyPressEvent` osi, więc odznaczenie
        # strzału musi być obsłużone TU (jak Home/End w `_home_key`).
        if (QApplication.focusWidget() is self.waveform
                and self.waveform.selected_shot is not None):
            self.waveform.select_shot(None)
            return
        if self.edit_pos_btn.isChecked():
            self.edit_pos_btn.setChecked(False)

    def _anchor_mode(self) -> AnchorMode:
        """Bezpieczny odczyt trybu kotwicy — konwertuje wartość Qt z powrotem do AnchorMode."""
        return AnchorMode(self.anchor_combo.currentData())

    def _on_anchor_mode_changed(self, *_):
        mode = self._anchor_mode()
        self.waveform.anchor_label = "T0" if mode == AnchorMode.START_SIGNAL else "T1"
        self.waveform.update()
        self._update_preview()

    # ---------- sekcje inspektora ----------
    def _section(self, key: str, title_key: str, collapsed: bool = False) -> FormSection:
        """`FormSection` (nagłówek + chevron) ze stanem zwinięcia w `QSettings`.

        Klucz `ui/section/<key>` żyje w tej samej przestrzeni co geometria okna —
        NIE dotyka plików ustawień z `config.py`.
        """
        sec = FormSection(_TR(title_key), collapsible=True)
        expanded = not collapsed
        try:
            saved = QSettings().value(f"ui/section/{key}")
            if saved is not None:
                expanded = str(saved) == "true"
        except Exception:  # noqa: BLE001
            pass
        sec.header.set_expanded(expanded)
        sec.header.toggled.connect(
            lambda on, k=key: QSettings().setValue(
                f"ui/section/{k}", "true" if on else "false"))
        return sec

    @staticmethod
    def _fill_positions(combo: QComboBox) -> None:
        """Etykiety po polsku, klucz techniczny w `userData`.

        PUŁAPKA: po tej zmianie pozycję czyta się WYŁĄCZNIE przez `currentData()`
        — `currentText()` zwróciłby „Lewy dolny" i wysadził walidację `OverlayStyle`.
        """
        for key in ANCHOR_POSITIONS:
            combo.addItem(_TR("pos_" + key.replace("-", "_")), key)

    @staticmethod
    def _set_data(combo: QComboBox, value) -> None:
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    @staticmethod
    def _elastic(*spins) -> None:
        """Pole liczy minimalną szerokość z najdłuższego tekstu zakresu
        („100000,00 s") i rozpycha inspektor — pozwalamy mu się zwężać.
        `Ignored` sprawia, że minimum bierze się z `setMinimumWidth`, nie z tekstu."""
        for sp in spins:
            sp.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            sp.setMinimumWidth(92)   # mieści „0,00 s" + sufiks + strzałki (także 150 %)
            sp.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            # Bez śledzenia klawiatury podgląd nie przelicza się na KAŻDY wpisany
            # znak (wpisanie „12" nie generuje najpierw wartości 1).
            sp.setKeyboardTracking(False)

    @staticmethod
    def _narrow(width: int, *spins) -> None:
        """Pole na 1–4 cyfry nie musi wypełniać kolumny kontrolek."""
        for sp in spins:
            sp.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            sp.setMinimumWidth(min(76, width))
            sp.setMaximumWidth(width)

    @staticmethod
    def _compact(*combos, chars: int = 14) -> None:
        """Combo NIE wymusza szerokości najdłuższej pozycji (rozpychała inspektor);
        lista rozwijana pokazuje pełny tekst mimo to."""
        for c in combos:
            c.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            c.setMinimumContentsLength(chars)

    def _input_group(self):
        sec = self._section("input", "sec_input")
        self.video_field = PathField(mode="open", filter=_VIDEO_FILTER,
                                     placeholder=_TR("path_video_placeholder"))
        self.video_field.browse.setToolTip(_TR("tip_choose_video"))
        # Przeglądanie idzie przez akcję paska (pamięć katalogu w `config`),
        # nie przez własny dialog PathField — inaczej zgubilibyśmy `last_dir`.
        self.video_field.browse.clicked.disconnect()
        self.video_field.browse.clicked.connect(self.act_open.trigger)
        # Wpisanie/upuszczenie ścieżki = ta sama droga co wybór z dialogu.
        self.video_field.changed.connect(self._set_video)
        sec.add_row("Wideo", self.video_field)

        # Ustawienie dotyczy WEJŚCIA (jak plik jest czytany do podglądu), nie
        # wyjścia — render zawsze idzie na oryginale, niezależnie od proxy.
        self.proxy_chk = QCheckBox(_TR("proxy_chk"))
        self.proxy_chk.setToolTip(_TR("tip_proxy_chk"))
        self.proxy_chk.setChecked(
            QSettings().value("ui/preview_proxy", True, type=bool))
        self.proxy_chk.toggled.connect(
            lambda on: QSettings().setValue("ui/preview_proxy", on))
        sec.add_row("", self.proxy_chk)

        self.source_seg = SegmentedControl([("text", _TR("source_text")),
                                            ("id", _TR("source_id"))])
        self.source_seg.set_value("id")
        sec.add_row("Źródło", self.source_seg)

        self.timeline_edit = QPlainTextEdit()
        self.timeline_edit.setPlaceholderText("1: 2.81s | 2: 4.63s (+1.82s)")
        self.timeline_edit.setProperty("role", "mono")
        self.timeline_edit.setMaximumHeight(80)
        self.timeline_edit.setTabChangesFocus(True)
        self.timeline_edit.textChanged.connect(self._update_preview)
        self.timeline_edit.textChanged.connect(self._refresh_timeline_summary)
        self.timeline_label = QLabel()
        set_role(self.timeline_label, "muted")
        self.timeline_label.setWordWrap(True)
        tl_box = QVBoxLayout(); tl_box.setContentsMargins(0, 0, 0, 0)
        tl_box.setSpacing(SPACING["sp_1"])
        tl_box.addWidget(self.timeline_edit)
        tl_box.addWidget(self.timeline_label)
        sec.add_row("Oś czasu", _wrap(tl_box))

        self.id_spin = QSpinBox(); self.id_spin.setRange(1, _SESSION_ID_MAX)
        # Stała szerokość + BEZ strzałek: ID sesji nie jest wartością, którą
        # inkrementuje się o 1 — a `Ignored` + `AllNonFixedFieldsGrow` zgniatały
        # to pole do paska kilku pikseli obok przycisku „Pobierz".
        self.id_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.id_spin.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.id_spin.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.id_spin.setFixedWidth(110)
        fetch = QPushButton("Pobierz")
        fetch.setToolTip("Pobiera oś czasu i metadane z API, bez zmiany przycięcia (Ctrl+G)")
        fetch.clicked.connect(self.act_fetch.trigger)
        self.fetch_btn = fetch
        fetch_trim = QPushButton("Pobierz i przytnij")
        fetch_trim.setToolTip(
            "Pobiera z API, wykrywa sygnał startu (T0) i przycina film:\n"
            "5 s przed T0 → ostatni strzał + 5 s.")
        fetch_trim.clicked.connect(self._fetch_id_and_trim)
        self.fetch_trim_btn = fetch_trim
        idrow = QHBoxLayout(); idrow.setContentsMargins(0, 0, 0, 0)
        idrow.addWidget(self.id_spin)
        idrow.addWidget(fetch, 1)
        sec.add_row("ID", _wrap(idrow))

        detect_id_tone = QPushButton("Wykryj ID z audio")
        detect_id_tone.setToolTip(
            "Szuka w nagraniu sygnału tonowego ID, który timer odtwarza po zapisie\n"
            "sesji w bazie (marker 5000 Hz + 4 cyfry + cyfra kontrolna, 5200–7000 Hz),\n"
            "wpisuje wykryte ID i OD RAZU pobiera dane z API oraz przycina film\n"
            "(jak „Pobierz i przytnij”). Zawsze analizuje oryginalny plik (nie proxy LRF).")
        detect_id_tone.clicked.connect(self._detect_id_tone)
        self.detect_id_btn = detect_id_tone
        # Paski przycisków idą na pełną szerokość wiersza (jak w `add_widget_row`
        # ze skilla) — w kolumnie kontrolek polskie etykiety byłyby ucinane.
        # „Dopasuj po czasie" jako icon-only (zegar): trzeci przycisk Z TEKSTEM
        # w tym pasku podnosił minimalną szerokość inspektora 401→443 px
        # (poziomy pasek przewijania); opis niesie tooltip, jak w transporcie.
        match_time = QToolButton()
        match_time.setToolButtonStyle(Qt.ToolButtonIconOnly)
        match_time.setIconSize(QSize(18, 18))
        set_kind(match_time, "ghost")
        match_time.setToolTip(f"{_TR('match_time')} — {_TR('tip_match_time')}")
        match_time.clicked.connect(self._match_session_by_time)
        self.match_time_btn = match_time
        idbtns = QHBoxLayout(); idbtns.setContentsMargins(0, 0, 0, 0)
        idbtns.addWidget(fetch_trim, 1); idbtns.addWidget(detect_id_tone, 1)
        idbtns.addWidget(match_time)
        sec.add_widget_row(_wrap(idbtns))

        # Opcja awaryjna dla nagrań bez czytelnego sygnału ID: zamiast szukać
        # nagrania ręcznie w kalkulatorze, dopasowujemy po czasie (nazwa DJI /
        # creation_time / mtime vs start sesji na timerze i chwila zapisu).
        # Pełna szerokość wiersza (`add_widget_row`), nie kolumna kontrolek —
        # etykieta w kolumnie przekraczała minimalną szerokość inspektora.
        self.match_time_chk = QCheckBox(_TR("opt_match_time"))
        self.match_time_chk.setToolTip(_TR("tip_opt_match_time"))
        self.match_time_chk.setChecked(
            QSettings().value("ui/match_by_time", True, type=bool))
        self.match_time_chk.toggled.connect(
            lambda on: QSettings().setValue("ui/match_by_time", on))
        sec.add_widget_row(self.match_time_chk)

        self.api_meta_label = QLabel()
        self.api_meta_label.setProperty("role", "muted")
        self.api_meta_label.setWordWrap(True)
        self.api_meta_label.hide()
        # Pusta etykieta wiersza też znika — inaczej ukryte metadane zostawiają
        # w formularzu pusty wiersz.
        meta_lab = sec.add_row("", self.api_meta_label)
        meta_lab.hide()
        self.source_seg.currentChanged.connect(
            lambda key: self.api_meta_label.setVisible(
                key == "id" and bool(self.api_meta_label.text())
            )
        )
        # Nadpisanie metadanych z API (albo uzupełnienie sesji z tekstu, która
        # ich nie ma). Puste pole = wartość z API; placeholder pokazuje, co API
        # podało, żeby było widać, CO się nadpisuje.
        self.meta_track_edit = QLineEdit()
        self.meta_participant_edit = QLineEdit()
        for edit, what in ((self.meta_track_edit, "nazwę toru"),
                           (self.meta_participant_edit, "uczestnika")):
            edit.setClearButtonEnabled(True)
            edit.setToolTip(
                f"Nadpisuje {what} na nakładce (panel strzału, nakładka metadanych,\n"
                "podsumowanie). Puste = wartość pobrana z API; przy źródle „Tekst”\n"
                "to jedyne miejsce, skąd metadane trafiają na film.")
            edit.textChanged.connect(self._on_meta_override_changed)
        self._set_meta_placeholders(None)
        sec.add_row("Tor", self.meta_track_edit)
        sec.add_row("Uczestnik", self.meta_participant_edit)
        # Komunikaty dotyczące danych wejściowych (brak wideo, brak ID w audio…).
        self.input_msg = InlineMessage()
        sec.add_widget_row(self.input_msg)
        self._refresh_timeline_summary()
        return sec

    def _sync_group(self):
        sec = self._section("sync", "sec_sync")

        self.anchor_combo = QComboBox()
        # Przechowujemy .value (czysty str) — PySide6 konwertuje str-subclassy
        # (enum dziedziczący po str) do plain str w QVariant, co łamie porównania is.
        self.anchor_combo.addItem("Sygnał startu", AnchorMode.START_SIGNAL.value)
        self.anchor_combo.addItem("Pierwszy strzał", AnchorMode.FIRST_SHOT.value)
        self._compact(self.anchor_combo)
        sec.add_row("Typ kotwicy", self.anchor_combo)

        detect = QPushButton("Wykryj kotwicę")
        detect.setToolTip("Szuka pierwszego wyraźnego onsetu w zaznaczonym fragmencie.")
        detect.clicked.connect(self._detect)
        self.detect_btn = detect
        nextc = QPushButton("Następny kandydat")
        nextc.setToolTip("Przeskakuje do kolejnego wykrytego onsetu.")
        set_kind(nextc, "ghost")
        nextc.clicked.connect(self._next_candidate)
        self.next_btn = nextc
        start_sig = QPushButton("Wykryj sygnał startu")
        start_sig.setToolTip(
            "Filtr pasmowy 2000–4800 Hz (pasmo buzzera shot-timera) + wybór\n"
            "najgłośniejszego bzyczka. Ustawia typ kotwicy na „Sygnał startu”\n"
            "i przelicza T0. Działa dobrze na nagraniach DJI Osmo. (Ctrl+D)")
        start_sig.clicked.connect(self.act_detect_start.trigger)
        self.start_sig_btn = start_sig
        drow = QHBoxLayout(); drow.setContentsMargins(0, 0, 0, 0)
        drow.addWidget(detect, 1); drow.addWidget(nextc, 1)
        sec.add_widget_row(_wrap(drow))
        srow2 = QHBoxLayout(); srow2.setContentsMargins(0, 0, 0, 0)
        srow2.addWidget(start_sig, 1)
        sec.add_widget_row(_wrap(srow2))

        self.t0_spin = _dspin(0, 100000, 0.05, " s")
        self._elastic(self.t0_spin)
        self.t0_spin.valueChanged.connect(self._on_t0_spin)
        sec.add_row("Kotwica", self.t0_spin)

        self.trim_start_spin = _dspin(0, 100000, 0.1, " s")
        self.trim_end_spin = _dspin(0, 100000, 0.1, " s")
        self.trim_start_spin.setToolTip("Początek przycięcia (od)")
        self.trim_end_spin.setToolTip("Koniec przycięcia (do)")
        self._elastic(self.trim_start_spin, self.trim_end_spin)
        self.trim_start_spin.valueChanged.connect(self._on_trim_spin)
        self.trim_end_spin.valueChanged.connect(self._on_trim_spin)
        # Walidacja przy `editingFinished` (nie przy każdym znaku — skill, qt §8).
        self.trim_start_spin.editingFinished.connect(self._validate_trim)
        self.trim_end_spin.editingFinished.connect(self._validate_trim)
        sec.add_pair_row("Przytnij", self.trim_start_spin, self.trim_end_spin, "→")

        self.tail_spin = _dspin(0.0, 60.0, 0.5, " s", _TRIM_TAIL_S)
        self.tail_spin.setToolTip("Margines (s) doliczany po ostatnim strzale przy auto-przycięciu.")
        self._elastic(self.tail_spin)
        autotrim_btn = QPushButton("Auto-przycięcie")
        autotrim_btn.setToolTip(
            "Ustaw zakres przycięcia: 5 s przed startem → ostatni strzał + margines. (Ctrl+T)")
        autotrim_btn.clicked.connect(self.act_auto_trim.trigger)
        mrow = QHBoxLayout(); mrow.setContentsMargins(0, 0, 0, 0)
        mrow.addWidget(self.tail_spin, 1)
        mrow.addWidget(autotrim_btn, 2)
        self.autotrim_btn = autotrim_btn
        sec.add_row("Margines końcowy", _wrap(mrow))
        # Komunikaty synchronizacji (detekcja bez wyniku, zły zakres przycięcia).
        self.sync_msg = InlineMessage()
        self.sync_msg.actionClicked.connect(self._on_sync_msg_action)
        sec.add_widget_row(self.sync_msg)
        return sec

    def _appearance_group(self):
        """Kontener wszystkich sekcji wyglądu — `self.appearance_box` (wyłączany
        w trybie „bez nakładki"), więc semantyka `setDisabled` zostaje jak dotąd."""
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(SPACING["sp_6"])
        v.addWidget(self._overlay_look_section())
        v.addWidget(self._colors_section())
        v.addWidget(self._meta_section())
        v.addWidget(self._clock_section())
        v.addWidget(self._banner_section())
        self.appearance_box = box
        return box

    def _overlay_look_section(self):
        sec = self._section("appearance", "appearance")

        self.lang_combo = QComboBox()
        self.lang_combo.addItem("Polski", Lang.PL)
        self.lang_combo.addItem("English", Lang.EN)
        self._compact(self.lang_combo)
        self.lang_combo.currentIndexChanged.connect(self._update_preview)
        sec.add_row("Język", self.lang_combo)

        self.scale_spin = _pct_spin()
        self._narrow(92, self.scale_spin)
        self.scale_spin.valueChanged.connect(self._update_preview)
        sec.add_row("Rozmiar", self.scale_spin)

        self.pos_combo = QComboBox()
        self._fill_positions(self.pos_combo)
        self._compact(self.pos_combo)
        self._set_data(self.pos_combo, "bottom-left")
        self.pos_combo.currentIndexChanged.connect(self._update_preview)
        sec.add_row("Pozycja", self.pos_combo)

        self.off_x = _ispin(0, 8000, _DEFAULT_OFFSET_PX)
        self.off_y = _ispin(0, 8000, _DEFAULT_OFFSET_PX)
        self.off_x.setPrefix("X ")
        self.off_y.setPrefix("Y ")
        self._narrow(110, self.off_x, self.off_y)
        self.off_x.valueChanged.connect(self._update_preview)
        self.off_y.valueChanged.connect(self._update_preview)
        sec.add_pair_row("Offset", self.off_x, self.off_y, "/")

        self.panel_mode_combo = QComboBox()
        self.panel_mode_combo.addItem("Klasyczny (jeden strzał)", "classic")
        self.panel_mode_combo.addItem("Lista ostatnich strzałów", "list")
        self.panel_mode_combo.setToolTip(
            "Klasyczny: pojedynczy panel „Strzał x z yy” z metadanymi.\n"
            "Lista: ostatnie strzały jako wiersze (numer | czas | split) — nowy strzał\n"
            "pojawia się na dole i przesuwa starsze w górę (starsze są wygaszane).")
        self._compact(self.panel_mode_combo)
        self.panel_mode_combo.currentIndexChanged.connect(self._update_preview)
        self.panel_mode_combo.currentIndexChanged.connect(self._sync_dependencies)
        sec.add_row("Styl panelu", self.panel_mode_combo)

        self.list_rows_spin = _ispin(2, 10, 5)
        self._narrow(90, self.list_rows_spin)
        self.list_rows_spin.setToolTip("Ile ostatnich strzałów pokazuje lista (tryb „Lista”).")
        self.list_rows_spin.valueChanged.connect(self._update_preview)
        sec.add_row("Wiersze listy", self.list_rows_spin)

        self.list_progress_chk = QCheckBox("Numer jako „x/yy”")
        self.list_progress_chk.setChecked(True)
        self.list_progress_chk.setToolTip(
            "W trybie „Lista” najnowszy wiersz pokazuje numer jako postęp przebiegu\n"
            "(np. „6/9” = szósty strzał z dziewięciu).")
        self.list_progress_chk.stateChanged.connect(self._update_preview)
        sec.add_row("", self.list_progress_chk)

        self.list_pin_chk = QCheckBox("Przypnij pierwszy strzał")
        self.list_pin_chk.setChecked(True)
        self.list_pin_chk.setToolTip(
            "W trybie „Lista” strzał nr 1 zostaje w górnym slocie (z odstępem od\n"
            "reszty), gdy wypadłby z okna ostatnich strzałów — czas pierwszego\n"
            "strzału jest widoczny przez cały przebieg.")
        self.list_pin_chk.stateChanged.connect(self._update_preview)
        sec.add_row("", self.list_pin_chk)

        # Presety dotyczą CAŁEGO stylu (kolory, zegar, plansza), ale własna sekcja
        # na dwa przyciski byłaby szumem — wiersz zamyka pierwszą sekcję wyglądu.
        preset_row = QHBoxLayout(); preset_row.setContentsMargins(0, 0, 0, 0)
        load_preset_btn = QPushButton("Wczytaj preset…")
        save_preset_btn = QPushButton("Zapisz preset…")
        for b in (load_preset_btn, save_preset_btn):
            set_kind(b, "ghost")
        load_preset_btn.clicked.connect(self._load_preset)
        save_preset_btn.clicked.connect(self._save_preset)
        preset_row.addWidget(load_preset_btn, 1)
        preset_row.addWidget(save_preset_btn, 1)
        sec.add_widget_row(_wrap(preset_row))
        return sec

    def _colors_section(self):
        sec = self._section("colors", "sec_colors")
        self.bg_btn = ColorSwatchButton((0, 0, 0, 170))
        self.text_btn = ColorSwatchButton((255, 255, 255, 255))
        self.accent_btn = ColorSwatchButton((255, 196, 0, 255))
        self.border_btn = ColorSwatchButton((255, 255, 255, 220))
        for b in (self.bg_btn, self.text_btn, self.accent_btn, self.border_btn):
            b.changed.connect(self._update_preview)
        sec.add_row("Tło", self.bg_btn)
        sec.add_row("Tekst", self.text_btn)
        sec.add_row("Akcent", self.accent_btn)
        sec.add_row("Obramowanie", self.border_btn)

        self.border_chk = QCheckBox("Włącz obramowanie"); self.border_chk.setChecked(True)
        self.border_chk.stateChanged.connect(self._update_preview)
        self.border_chk.stateChanged.connect(self._sync_dependencies)
        sec.add_row("", self.border_chk)
        self.border_w = _ispin(1, 30, 3)
        self._narrow(90, self.border_w)
        self.border_w.valueChanged.connect(self._update_preview)
        sec.add_row("Grubość", self.border_w, unit="px")
        return sec

    def _meta_section(self):
        sec = self._section("meta", "sec_meta", collapsed=True)
        self.meta_chk = QCheckBox("Pokaż nakładkę")
        self.meta_chk.setToolTip(
            "Osobna nakładka z nazwą toru i uczestnikiem („Jaro — 9 strzałów”),\n"
            "widoczna od T0 do końca filmu; pozycjonowana niezależnie (róg + offset\n"
            "poniżej), można ją też przeciągać w trybie edycji pozycji.")
        self.meta_chk.stateChanged.connect(self._update_preview)
        self.meta_chk.stateChanged.connect(self._sync_dependencies)
        sec.add_row("", self.meta_chk)

        self.meta_pos_combo = QComboBox()
        self._fill_positions(self.meta_pos_combo)
        self._compact(self.meta_pos_combo)
        self._set_data(self.meta_pos_combo, "top-left")
        self.meta_pos_combo.currentIndexChanged.connect(self._update_preview)
        sec.add_row("Pozycja", self.meta_pos_combo)

        self.meta_off_x = _ispin(0, 8000, _DEFAULT_OFFSET_PX)
        self.meta_off_y = _ispin(0, 8000, _DEFAULT_OFFSET_PX)
        self.meta_off_x.setPrefix("X ")
        self.meta_off_y.setPrefix("Y ")
        self._narrow(110, self.meta_off_x, self.meta_off_y)
        self.meta_off_x.valueChanged.connect(self._update_preview)
        self.meta_off_y.valueChanged.connect(self._update_preview)
        sec.add_pair_row("Offset", self.meta_off_x, self.meta_off_y, "/")
        return sec

    def _clock_section(self):
        sec = self._section("clock", "sec_clock", collapsed=True)
        self.clock_chk = QCheckBox("Płynący czas od T0")
        self.clock_chk.setToolTip(
            "Nad nakładką ze strzałami pokazuje płynący zegar „T+x.xs” liczony od\n"
            "sygnału startu (T0). Widoczny już od STARTU, jeszcze przed pierwszym strzałem.")
        self.clock_chk.stateChanged.connect(self._update_preview)
        self.clock_chk.stateChanged.connect(self._sync_dependencies)
        sec.add_row("", self.clock_chk)

        self.clock_pos_combo = QComboBox()
        self.clock_pos_combo.addItem(_TR("pos_clock_auto"), "auto")
        self._fill_positions(self.clock_pos_combo)
        self._compact(self.clock_pos_combo)
        self.clock_pos_combo.setToolTip(
            "Gdzie umieścić zegar. „Nad nakładką (auto)” trzyma go tuż nad panelem\n"
            "strzału; pozostałe opcje pozycjonują go niezależnie (róg + offset poniżej).")
        self.clock_pos_combo.currentIndexChanged.connect(self._update_preview)
        sec.add_row("Pozycja", self.clock_pos_combo)

        self.clock_off_x = _ispin(0, 8000, _DEFAULT_OFFSET_PX)
        self.clock_off_y = _ispin(0, 8000, _DEFAULT_OFFSET_PX)
        self.clock_off_x.setPrefix("X ")
        self.clock_off_y.setPrefix("Y ")
        self._narrow(110, self.clock_off_x, self.clock_off_y)
        self.clock_off_x.setToolTip("Offset zegara X (używany, gdy pozycja ≠ „auto”).")
        self.clock_off_y.setToolTip("Offset zegara Y (używany, gdy pozycja ≠ „auto”).")
        self.clock_off_x.valueChanged.connect(self._update_preview)
        self.clock_off_y.valueChanged.connect(self._update_preview)
        sec.add_pair_row("Offset", self.clock_off_x, self.clock_off_y, "/")
        return sec

    def _banner_section(self):
        # Słowo „START" jest w tytule sekcji — etykiety wierszy go nie powtarzają.
        sec = self._section("banner", "sec_banner", collapsed=True)
        self.banner_spin = _dspin(0.0, 10.0, 0.5, " s", 1.0)
        self._narrow(100, self.banner_spin)
        sec.add_row("Czas", self.banner_spin)

        self.banner_scale_spin = _pct_spin()
        self._narrow(92, self.banner_scale_spin)
        self.banner_scale_spin.valueChanged.connect(self._update_preview)
        sec.add_row("Rozmiar", self.banner_scale_spin)

        self.banner_bg_btn = ColorSwatchButton((0, 0, 0, 150))
        self.banner_bg_btn.changed.connect(self._update_preview)
        sec.add_row("Tło", self.banner_bg_btn)

        self.banner_text_btn = ColorSwatchButton((255, 196, 0, 255))
        self.banner_text_btn.changed.connect(self._update_preview)
        sec.add_row("Tekst", self.banner_text_btn)

        self.banner_border_btn = ColorSwatchButton((255, 196, 0, 220))
        self.banner_border_btn.changed.connect(self._update_preview)
        sec.add_row("Obramowanie", self.banner_border_btn)

        self.banner_border_chk = QCheckBox("Włącz obramowanie")
        self.banner_border_chk.setChecked(False)
        self.banner_border_chk.stateChanged.connect(self._update_preview)
        self.banner_border_chk.stateChanged.connect(self._sync_dependencies)
        sec.add_row("", self.banner_border_chk)

        self.banner_border_w = _ispin(1, 30, 3)
        self._narrow(90, self.banner_border_w)
        self.banner_border_w.valueChanged.connect(self._update_preview)
        sec.add_row("Grubość", self.banner_border_w, unit="px")
        return sec

    def _sync_dependencies(self, *_) -> None:
        """Kontrolki zależne są WYŁĄCZANE (nie ukrywane) — układ nie skacze,
        a użytkownik widzi, że opcja istnieje."""
        self.border_w.setEnabled(self.border_chk.isChecked())
        clock_on = self.clock_chk.isChecked()
        for w in (self.clock_pos_combo, self.clock_off_x, self.clock_off_y):
            w.setEnabled(clock_on)
        meta_on = self.meta_chk.isChecked()
        for w in (self.meta_pos_combo, self.meta_off_x, self.meta_off_y):
            w.setEnabled(meta_on)
        list_on = self.panel_mode_combo.currentData() == "list"
        for w in (self.list_rows_spin, self.list_progress_chk, self.list_pin_chk):
            w.setEnabled(list_on)
        self.banner_border_w.setEnabled(self.banner_border_chk.isChecked())

    def _apply_style(self, style: OverlayStyle) -> None:
        """Ustawia wszystkie widgety wyglądu z podanego OverlayStyle (bez pośrednich preview)."""
        widgets = [
            self.lang_combo, self.scale_spin, self.pos_combo,
            self.off_x, self.off_y, self.bg_btn, self.text_btn,
            self.panel_mode_combo, self.list_rows_spin, self.list_progress_chk,
            self.list_pin_chk,
            self.meta_chk, self.meta_pos_combo, self.meta_off_x, self.meta_off_y,
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
        _set_pct(self.scale_spin, style.scale)
        self._set_data(self.pos_combo, style.position)
        self.off_x.setValue(style.offset_x)
        self.off_y.setValue(style.offset_y)
        pidx = self.panel_mode_combo.findData(style.panel_mode)
        if pidx >= 0:
            self.panel_mode_combo.setCurrentIndex(pidx)
        self.list_rows_spin.setValue(style.list_max_rows)
        self.list_progress_chk.setChecked(style.list_show_progress)
        self.list_pin_chk.setChecked(style.list_pin_first_shot)
        self.meta_chk.setChecked(style.show_meta_panel)
        midx = self.meta_pos_combo.findData(style.meta_position)
        if midx >= 0:
            self.meta_pos_combo.setCurrentIndex(midx)
        self.meta_off_x.setValue(style.meta_offset_x)
        self.meta_off_y.setValue(style.meta_offset_y)
        self.bg_btn.set_rgba(style.bg_color, emit=False)
        self.text_btn.set_rgba(style.text_color, emit=False)
        self.accent_btn.set_rgba(style.accent_color, emit=False)
        self.border_btn.set_rgba(style.border_color, emit=False)
        self.border_chk.setChecked(style.border_enabled)
        self.border_w.setValue(style.border_width)
        self.clock_chk.setChecked(style.show_running_clock)
        cidx = self.clock_pos_combo.findData(style.clock_position)
        if cidx >= 0:
            self.clock_pos_combo.setCurrentIndex(cidx)
        self.clock_off_x.setValue(style.clock_offset_x)
        self.clock_off_y.setValue(style.clock_offset_y)
        self.banner_spin.setValue(style.start_banner_duration)
        _set_pct(self.banner_scale_spin, style.start_banner_scale)
        self.banner_bg_btn.set_rgba(style.start_banner_bg_color, emit=False)
        self.banner_text_btn.set_rgba(style.start_banner_text_color, emit=False)
        self.banner_border_btn.set_rgba(style.start_banner_border_color, emit=False)
        self.banner_border_chk.setChecked(style.start_banner_border_enabled)
        self.banner_border_w.setValue(style.start_banner_border_width)

        for w in widgets:
            w.blockSignals(False)
        # Stan „wyszarzenia" musi odpowiadać WCZYTANEMU stylowi, nie domyślnym
        # wartościom widgetów — sygnały były zablokowane, więc wołamy jawnie.
        self._sync_dependencies()
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
        sec = self._section("output", "sec_output")
        self.out_field = PathField(mode="save", filter="Wideo (*.mp4 *.webm *.gif)",
                                   placeholder=_TR("path_output_placeholder"))
        self.out_field.browse.setToolTip(_TR("tip_choose_output"))
        self.out_field.browse.clicked.disconnect()
        self.out_field.browse.clicked.connect(self._choose_output)
        sec.add_row("Plik wyjściowy", self.out_field)

        self.format_combo = QComboBox()
        self.format_combo.addItem("MP4 (H.264)", "mp4")
        self.format_combo.addItem("WebM (VP9)", "webm")
        self.format_combo.addItem("GIF (animowany)", "gif")
        self._compact(self.format_combo)
        self.format_combo.currentIndexChanged.connect(self._on_format_changed)
        sec.add_row("Format", self.format_combo)

        self.no_overlay_chk = QCheckBox("Bez nakładki (tylko przytnij)")
        self.no_overlay_chk.stateChanged.connect(self._on_no_overlay_toggled)
        sec.add_row("", self.no_overlay_chk)

        self.gpu_chk = QCheckBox("Akceleracja GPU (NVENC)")
        self.gpu_chk.setChecked(True)
        sec.add_row("", self.gpu_chk)

        diag = QPushButton("Diagnostyka NVENC")
        diag.setToolTip("Pokazuje status NVENC, użytą binarkę FFmpeg "
                        "i szczegóły błędu, gdy test kodowania nie przeszedł")
        cli_btn = QPushButton("Pokaż komendę CLI")
        cli_btn.setToolTip(
            "Buduje równoważne wywołanie bezgłowe (PiroOverlay.exe …) z bieżących\n"
            "ustawień — do skryptów/automatyzacji. Można je skopiować do schowka.")
        for b in (diag, cli_btn):
            set_kind(b, "ghost")
        diag.clicked.connect(self._show_nvenc_diag)
        cli_btn.clicked.connect(self._show_cli_command)
        hrow = QHBoxLayout(); hrow.setContentsMargins(0, 0, 0, 0)
        hrow.addWidget(diag, 1); hrow.addWidget(cli_btn, 1)
        sec.add_widget_row(_wrap(hrow))

        # Wiersz: Renderuj / Zatrzymaj (te same QAction co pasek akcji).
        brow = QHBoxLayout(); brow.setContentsMargins(0, 0, 0, 0)
        self.render_btn = QPushButton(_TR("render"))
        set_kind(self.render_btn, "primary")
        self.render_btn.setToolTip("Renderuj (Ctrl+R)")
        self.render_btn.clicked.connect(self.act_render.trigger)
        self.cancel_btn = QPushButton(_TR("act_cancel"))
        self.cancel_btn.setToolTip("Przerywa trwające renderowanie i usuwa niedokończony plik.")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.act_cancel.trigger)
        self.render_btn.setMaximumWidth(120)
        self.cancel_btn.setMaximumWidth(120)
        brow.addWidget(self.render_btn)
        brow.addWidget(self.cancel_btn)
        brow.addStretch(1)
        sec.add_widget_row(_wrap(brow))

        # Wiersz: kolejka renderów + wsad.
        qrow = QHBoxLayout(); qrow.setContentsMargins(0, 0, 0, 0)
        self.queue_add_btn = QPushButton("Dodaj do kolejki")
        self.queue_add_btn.setToolTip(
            "Dodaje render z bieżącymi ustawieniami jako zadanie kolejki")
        self.queue_add_btn.clicked.connect(self.act_queue_add.trigger)
        self.queue_show_btn = QPushButton("Kolejka")
        self.queue_show_btn.setToolTip("Otwiera okno kolejki renderów")
        self.queue_show_btn.clicked.connect(self.act_queue.trigger)
        self.batch_btn = QPushButton("Wsadowo…")
        self.batch_btn.setToolTip("Przetwarzanie wielu plików (tryb auto + ID)")
        self.batch_btn.clicked.connect(self.act_batch.trigger)
        qrow.addWidget(self.queue_add_btn, 2)
        qrow.addWidget(self.queue_show_btn, 1)
        qrow.addWidget(self.batch_btn, 1)
        sec.add_widget_row(_wrap(qrow))

        # Wiersz: otwarcie wyniku — widoczne dopiero PO zakończeniu renderu.
        self.open_btn = QPushButton("Otwórz folder z wynikiem")
        self.open_btn.setVisible(False)
        self.open_btn.clicked.connect(self._open_output_folder)
        orow2 = QHBoxLayout(); orow2.setContentsMargins(0, 0, 0, 0)
        orow2.addWidget(self.open_btn); orow2.addStretch(1)
        sec.add_widget_row(_wrap(orow2))
        return sec

    # ---------- logika ----------
    def current_style(self):
        return OverlayStyle(
            lang=self.lang_combo.currentData(),
            scale=_pct_value(self.scale_spin),
            position=self.pos_combo.currentData(),
            offset_x=self.off_x.value(), offset_y=self.off_y.value(),
            panel_mode=self.panel_mode_combo.currentData(),
            list_max_rows=self.list_rows_spin.value(),
            list_show_progress=self.list_progress_chk.isChecked(),
            list_pin_first_shot=self.list_pin_chk.isChecked(),
            show_meta_panel=self.meta_chk.isChecked(),
            meta_position=self.meta_pos_combo.currentData(),
            meta_offset_x=self.meta_off_x.value(),
            meta_offset_y=self.meta_off_y.value(),
            bg_color=self.bg_btn.rgba(), text_color=self.text_btn.rgba(),
            accent_color=self.accent_btn.rgba(), border_color=self.border_btn.rgba(),
            border_enabled=self.border_chk.isChecked(), border_width=self.border_w.value(),
            show_running_clock=self.clock_chk.isChecked(),
            clock_position=self.clock_pos_combo.currentData(),
            clock_offset_x=self.clock_off_x.value(),
            clock_offset_y=self.clock_off_y.value(),
            start_banner_duration=self.banner_spin.value(),
            start_banner_scale=_pct_value(self.banner_scale_spin),
            start_banner_bg_color=self.banner_bg_btn.rgba(),
            start_banner_text_color=self.banner_text_btn.rgba(),
            start_banner_border_enabled=self.banner_border_chk.isChecked(),
            start_banner_border_color=self.banner_border_btn.rgba(),
            start_banner_border_width=self.banner_border_w.value(),
        )

    def _choose_video(self):
        start_dir = config.load_last_dir("video") or ""
        path, _ = QFileDialog.getOpenFileName(self, _TR("choose_video"), start_dir,
                                              _VIDEO_FILTER)
        if path:
            config.save_last_dir("video", Path(path).parent)
            self._set_video(path)

    def _set_video(self, path: str):
        # Zanim podmienimy plik — zapisz ustawienia poprzedniego (jeśli były gotowe),
        # by nie zgubić zmian zrobionych bez renderu/kolejki (np. wpisane ID z API).
        if self.video_path and self._file_settings_ready:
            self._save_file_settings()
        self._file_settings_ready = False
        # Detekcja dla POPRZEDNIEGO pliku jest już nieaktualna — przerwij po cichu
        # (token pokolenia odrzuci wynik, gdyby zdążył dojść).
        self._cancel_operation(silent=True)
        self.video_path = path
        self.video_field.set_path(path, emit=False)
        self.setWindowTitle(f"{Path(path).name} — {_TR('app_title')}")
        self.preview_stack.setCurrentWidget(self.preview_label)
        self.input_msg.clear()
        self._sync_action_cb = None
        self.sync_msg.clear()
        self._t0_detector = 0  # nowy plik — dopóki coś go nie ustawi, T0=0 jest "ręczne"
        self._t0_recheck_busy = False  # sprawdzenie POPRZEDNIEGO pliku już nieaktualne
        self._set_render_enabled(not self._render_busy)
        p = Path(path)
        out_ext = _FORMAT_EXT.get(self.format_combo.currentData(), ".mp4")
        self.out_field.set_path(str(p.with_name(p.stem + "_PiRoOverlay" + out_ext)), emit=False)
        # Inwaliduj cache — nowe wideo, stara klatka nieaktualna
        self._cached_frame = None
        self._cached_frame_t = -1.0
        # Rozmiar wideo (do skalowania offsetów w podglądzie ≈ render).
        try:
            info = ffmpeg.probe(path)
            self._video_size = (info.width, info.height)
        except Exception:  # noqa: BLE001
            info = None
            self._video_size = None
        self._video_info = info   # cały VideoInfo (duration/creation_time) dla dopasowania po czasie

        # Zapamiętane ustawienia dla tego pliku (zastosujemy po analizie audio).
        self._pending_file_settings = config.load_file_settings(path)

        lrf = ffmpeg.find_lrf(path)
        self.lrf_path = str(lrf) if lrf else None
        audio_src = self.lrf_path or path
        # Player gra na proxy (LRF od DJI albo nasze 540p), jeśli jest — mały plik
        # dekoduje się od ręki, a offsety nakładek i tak skalujemy do rozdzielczości
        # ORYGINAŁU (`_video_size`), więc podgląd zostaje WYSIWYG.
        self._proxy_path = None
        self._proxy_wanted = None
        if self.lrf_path:
            self._set_player_source(self.lrf_path)
        elif self._needs_preview_proxy(info):
            cached = config.find_proxy(path)
            if cached is not None:
                self._proxy_path = str(cached)
                self._set_player_source(self._proxy_path)
            else:
                # Budowa czeka na koniec analizy audio/detekcji T0 (`_on_wave_done`)
                # — player jest do tego czasu nieaktywny, zostaje podgląd klatki.
                self._proxy_wanted = path
                self._set_player_pending()
        else:
            self._set_player_source(path)
        self._show_loading(_TR("busy_audio_lrf") if self.lrf_path else _TR("busy_audio"))

        self.wave_worker = WaveformWorker(audio_src)
        self.wave_worker.done.connect(self._on_wave_done)
        self.wave_worker.failed.connect(
            lambda m: self._show_loading(_TR("audio_failed").format(m), busy=False))
        self.wave_worker.start()
        self._request_frame()

    def _on_wave_done(self, env, dur, onsets):
        self.waveform.set_data(env, dur, onsets)
        self._show_preview_page()
        self._update_preview_time()
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
            status_message(self.statusBar(),
                           "Wczytano zapisane ustawienia dla tego pliku.", "info", 6000)
            # Sprawdzenie T0 (jeśli w ogóle potrzebne) ma pierwszeństwo przed
            # budową proxy — ten sam powód co auto-detekcja niżej: `_run_op`
            # ma jeden slot, a proxy sama spróbuje ponownie (`_maybe_start_proxy`).
            self._maybe_recheck_t0(pending)
            self._maybe_start_proxy()
            return
        # Pierwszy raz dla tego pliku → wykryj T0 (buzzer) i ustaw przycięcie.
        self._file_settings_ready = True
        self._auto_detect_t0()
        # Detekcja T0 zajmuje `_run_op`, więc budowa proxy poczeka w kolejce
        # (`_maybe_start_proxy` sam spróbuje ponownie) — analiza audio i T0 mają
        # pierwszeństwo, bo od nich zależy przycięcie i sensowny podgląd.
        self._maybe_start_proxy()

    # ---------- proxy podglądu (540p) ----------
    # Polityka źródła playera i scrubbera: proxy LRF (DJI) → nasze proxy 540p →
    # oryginał. Powód (zmierzony, patrz CLAUDE.md „Proxy podglądu"): QMediaPlayer
    # dekoduje 4K HEVC programowo — 4 klatki na 5 s odtwarzania; to samo nagranie
    # jako proxy 540p gra ~47 fps. Pliki ≤1080p H.264 grają wprost, bez proxy.

    def _needs_preview_proxy(self, info) -> bool:
        if info is None or not self.proxy_chk.isChecked():
            return False
        return info.height > 1080 or "hevc" in (info.codec or "").lower()

    def _frame_src(self) -> str:
        """Źródło do ekstrakcji klatek (scrubber, podgląd statyczny).

        Ta sama kolejność co dla playera: klatka z 4K HEVC wychodzi sekundami,
        z proxy — ułamkiem sekundy, a `PREVIEW_HEIGHT` (360) i tak jest niższe
        niż proxy (540), więc jakość podglądu się nie zmienia."""
        return self.lrf_path or self._proxy_path or self.video_path

    def _maybe_start_proxy(self) -> None:
        """Startuje budowę proxy, gdy nic ważniejszego nie trwa.

        Pierwszeństwo mają: analiza audio + detekcja T0 (`_run_op` ma jeden slot)
        oraz render/kolejka (proxy nie może odbierać im GPU/CPU). Gdy zajęte —
        próbujemy ponownie za sekundę. Świadomie proste odpytywanie zamiast
        łańcucha sygnałów: budowa jest jednorazowa i nieblokująca."""
        if not self._proxy_wanted:
            return
        if self._op_worker is not None or self._render_busy:
            if not self._proxy_poll_queued:
                self._proxy_poll_queued = True
                QTimer.singleShot(_PROXY_RETRY_MS, self._proxy_poll)
            return
        video = self._proxy_wanted
        self._proxy_wanted = None      # anulowanie nie ma restartować budowy
        out = config.proxy_path_for(video)
        self._proxy_started_at = time.monotonic()
        self._proxy_building = True

        def build(progress_cb, cancel_check, on_process):
            path = render.make_preview_proxy(
                video, out, height=render.PREVIEW_PROXY_HEIGHT,
                progress_cb=progress_cb, cancel_check=cancel_check,
                on_process=on_process)
            config.prune_proxies()
            return str(path)

        if not self._run_op(build, status_text=_TR("busy_proxy"),
                            progress=True, progress_text=_TR("busy_proxy"),
                            on_result=self._on_proxy_done,
                            on_error=self._on_proxy_failed):
            self._proxy_building = False
            self._proxy_wanted = video   # slot zajęty — spróbujemy jeszcze raz
            self._maybe_start_proxy()

    def _proxy_busy(self) -> bool:
        """Czy trwa (lub czeka) budowa proxy — do tooltipa transportu."""
        return bool(self._proxy_wanted) or self._proxy_building

    def _proxy_poll(self) -> None:
        self._proxy_poll_queued = False
        self._maybe_start_proxy()

    def _on_proxy_done(self, path: str) -> None:
        self._proxy_building = False
        self._proxy_path = path
        self._set_player_source(path)
        self._show_preview_page()
        self._rebuild_player_overlays()
        self._seek(self.t0_spin.value())
        took = time.monotonic() - self._proxy_started_at
        self._ok(_TR("msg_proxy_ready").format(_fmt_time_s(round(took, 1))))

    def _on_proxy_failed(self, msg: str) -> None:
        self._proxy_building = False
        # Proxy to DODATEK — bez niego zostaje podgląd klatki, więc to ostrzeżenie,
        # nie błąd krytyczny.
        self._notify("input", _TR("msg_proxy_failed").format(msg.splitlines()[0][:200]))

    def _auto_detect_t0(self) -> None:
        """Startuje detekcję bzyczka (T0) po imporcie pliku; po wykryciu ustawia
        kotwicę + przycięcie: 5 s przed T0 → max 75 s po T0.

        Idzie tą samą drogą co ręczne detekcje (`_run_op`), więc jest widoczna
        w pasku stanu i da się ją anulować.
        """
        if not self.video_path:
            return
        src = self.lrf_path or self.video_path
        self._run_op(partial(audio_sync.detect_dji_start, src),
                     status_text=_TR("busy_detect_start"),
                     on_result=self._on_autodetect_t0)

    def _on_autodetect_t0(self, detected) -> None:
        if detected is None:
            # Kiedyś cicho; teraz KAŻDA operacja kończy się widocznym wynikiem.
            self._notify("sync", _TR("msg_no_start_signal"))
            return
        self._force_start_signal_mode()
        self._set_t0(detected, detector=audio_sync.START_DETECTOR_VERSION)
        dur = self.waveform.duration or None
        start = max(0.0, detected - _LEAD_IN_S)
        end = detected + _IMPORT_TAIL_S
        if dur:
            end = min(end, dur)
        self.trim_start_spin.setValue(start)
        self.trim_end_spin.setValue(end)
        self._ok(_TR("msg_t0_detected").format(_fmt_time_s(round(detected, 2))))

    def _maybe_recheck_t0(self, pending: dict) -> None:
        """T0 wczytany z `file_settings.json` może pochodzić ze starszej wersji
        `audio_sync.detect_dji_start` (np. sprzed guardu obwiedni v0.42.0) —
        patrz CLAUDE.md „Wykrywanie przestarzałego T0 z pamięci pliku". Gdy
        `pipeline.t0_needs_recheck` mówi, że warto sprawdzić, odpalamy świeżą
        detekcję W TLE (bez nadpisywania T0) i porównujemy wynik.

        Nie może wyścigać się z inną operacją: gdy `_run_op` jest zajęty (np.
        cichym pobraniem sesji z API tuż po wczytaniu zapamiętanych ustawień,
        `_apply_file_settings` → `_fetch_id(silent=True)`), NIE zgłaszamy
        zajętości — po prostu próbujemy ponownie za chwilę (jak `_maybe_start_proxy`
        z budową proxy), aż slot się zwolni albo plik się zmieni.
        """
        video_path = self.video_path
        saved_t0 = float(pending.get("t0") or 0.0)
        if saved_t0 <= 0 or video_path is None:
            return
        if not pipeline.t0_needs_recheck(pending.get("t0_detector"),
                                         audio_sync.START_DETECTOR_VERSION):
            return
        self._t0_recheck_busy = True
        src = self.lrf_path or video_path
        started = self._run_op(partial(audio_sync.detect_dji_start, src),
                               status_text=_TR("busy_recheck_t0"),
                               on_result=partial(self._on_t0_recheck_done, saved_t0))
        if not started:
            QTimer.singleShot(_T0_RECHECK_RETRY_MS,
                              partial(self._retry_recheck_t0, pending, video_path))

    def _retry_recheck_t0(self, pending: dict, video_path: str) -> None:
        if self.video_path != video_path:
            self._t0_recheck_busy = False  # plik się zmienił — nieaktualne
            return
        self._maybe_recheck_t0(pending)

    def _on_t0_recheck_done(self, saved_t0: float, detected) -> None:
        self._t0_recheck_busy = False
        if detected is None:
            # Nowa detekcja nic nie znalazła — nie mamy z czym porównać zapisanego
            # T0, więc nie zgłaszamy niczego (cisza jest tu poprawna, nie "pusta").
            return
        if pipeline.t0_differs(saved_t0, detected):
            self._notify_sync_action(
                _TR("msg_t0_stale").format(_fmt_time_s(round(saved_t0, 2)),
                                          _fmt_time_s(round(detected, 2))),
                _TR("msg_t0_stale_use").format(_fmt_time_s(round(detected, 2))),
                partial(self._apply_t0_recheck, detected), kind="warning")
        else:
            # Różnica w granicy tolerancji — cicho podnieś zapisaną wersję
            # detektora (zapisze się przy najbliższym `_save_file_settings`),
            # żeby nie sprawdzać tego samego pliku przy każdym wczytaniu.
            self._t0_detector = audio_sync.START_DETECTOR_VERSION

    def _apply_t0_recheck(self, detected: float) -> None:
        """Akcja „Użyj X s" z komunikatu o przestarzałym T0: ustawia nowy T0,
        przelicza przycięcie jak `_apply_auto_trim` (które samo zamelduje wynik
        w pasku stanu — sukces albo, gdy sesja nie jest jeszcze gotowa, powód)."""
        self._force_start_signal_mode()
        self._set_t0(detected, detector=audio_sync.START_DETECTOR_VERSION)
        self._apply_auto_trim()

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
        current_text = self.out_field.path()
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
            self.out_field.set_path(path, emit=False)

    def _build_session(self):
        if self._source_is_id():
            return self._with_meta_override(api.fetch_session(self.id_spin.value()))
        shots = parse_timeline(self.timeline_edit.toPlainText())
        if self.session is not None:
            return replace(self.session, shots=shots)  # nadpisanie już nałożone
        return self._with_meta_override(Session(shots=shots))

    def _with_meta_override(self, session: Session) -> Session:
        """Sesja z nałożonymi polami „Tor”/„Uczestnik” (puste = bez zmian)."""
        return pipeline.apply_meta_override(
            session, self.meta_track_edit.text(), self.meta_participant_edit.text())

    def _set_meta_placeholders(self, session: Session | None) -> None:
        api_track = session.nazwa_toru if session else None
        api_part = session.uczestnik if session else None
        self.meta_track_edit.setPlaceholderText(api_track or "z API (albo puste)")
        self.meta_participant_edit.setPlaceholderText(api_part or "z API (albo puste)")

    def _on_meta_override_changed(self) -> None:
        if self._api_session is not None:
            self.session = self._with_meta_override(self._api_session)
        self._update_preview()

    # ---------- operacje w tle (detekcje, API) ----------
    # Jeden mechanizm dla WSZYSTKICH długich operacji okna: worker + busy na
    # przycisku + nieokreślony pasek postępu + „Anuluj" w pasku stanu.
    # WYMÓG (powód, dla którego część z nich była kiedyś synchroniczna):
    # każda ścieżka zakończenia — wynik, brak wyniku, błąd, anulowanie —
    # kończy się widocznym komunikatem. Nie ma „cichej pustki".

    def _run_op(self, fn, *, button: QPushButton | None = None,
                busy_text: str = "", status_text: str = "",
                on_result=None, on_error=None,
                progress: bool = False, progress_text: str = "") -> bool:
        """Startuje `fn()` w wątku. Zwraca False, gdy inna operacja już trwa.

        `progress=True` — operacja zna swój czas trwania (budowa proxy): pasek
        jest DETERMINISTYCZNY (0–100 %), a `fn` dostaje trzy uchwyty jak render:
        `fn(progress_cb, cancel_check, on_process)`.
        """
        if self._op_worker is not None:
            status_message(self.statusBar(), _TR("op_busy"), "warning", 6000)
            return False
        self._op_gen += 1
        self._op_button = button
        if button is not None:
            set_busy(button, True, busy_text or button.text())
        self._set_ops_enabled(False)
        if progress:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
        else:
            self.progress.setRange(0, 0)   # nieokreślony — czasu nie znamy
        self.op_cancel_btn.setVisible(True)
        status_message(self.statusBar(), status_text, "info", 0)
        worker = FuncWorker(fn, self._op_gen, with_callbacks=progress)
        worker.done.connect(lambda gen, res, cb=on_result: self._on_op_done(gen, res, cb))
        worker.failed.connect(lambda gen, msg, cb=on_error: self._on_op_failed(gen, msg, cb))
        if progress:
            self._op_progress_text = progress_text or status_text
            self._proxy_status_at = 0.0
            worker.progressed.connect(self._on_op_progress)
        self._op_worker = worker
        # Referencja żyje do `finished` — QThread zniszczony w trakcie = crash.
        self._op_workers.append(worker)
        worker.finished.connect(lambda w=worker: self._op_workers.remove(w)
                                if w in self._op_workers else None)
        worker.start()
        return True

    def _set_ops_enabled(self, on: bool) -> None:
        """Blokuje TYLKO przyciski zmieniające wejście operacji (nie cały inspektor)."""
        for btn in self._op_buttons:
            btn.setEnabled(on)
        for act in (self.act_fetch, self.act_detect_start, self.act_auto_trim):
            act.setEnabled(on)

    def _end_op(self) -> None:
        self._op_worker = None
        self.op_cancel_btn.setVisible(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self._set_ops_enabled(True)
        if self._op_button is not None:
            set_busy(self._op_button, False)   # po _set_ops_enabled: przywraca tekst
            self._op_button = None

    def _on_op_progress(self, gen: int, p: float) -> None:
        """Postęp operacji długiej: pasek na bieżąco, pasek stanu NIE częściej niż
        raz na sekundę (migotanie tekstu w statusbarze jest nieczytelne)."""
        if gen != self._op_gen:
            return
        self.progress.setValue(int(max(0.0, min(p, 1.0)) * 100))
        now = time.monotonic()
        if now - self._proxy_status_at < 1.0:
            return
        self._proxy_status_at = now
        status_message(self.statusBar(),
                       f"{self._op_progress_text} {int(p * 100)} %", "info", 0)

    def _on_op_done(self, gen: int, result, callback) -> None:
        if gen != self._op_gen:
            return    # anulowane albo przestarzałe (zmiana pliku)
        self._end_op()
        if callback is not None:
            callback(result)

    def _on_op_failed(self, gen: int, msg: str, callback) -> None:
        if gen != self._op_gen:
            return
        self._end_op()
        if callback is not None:
            callback(msg)
        else:
            status_message(self.statusBar(), f"{_TR('op_failed')}: {msg}", "danger", 10000)

    def _cancel_operation(self, silent: bool = False) -> None:
        worker = self._op_worker
        if worker is None:
            return
        self._proxy_building = False
        worker.cancel()
        self._op_gen += 1   # wynik, który i tak nadejdzie, zostanie odrzucony
        self._end_op()
        if not silent:
            status_message(self.statusBar(), _TR("op_cancelled"), "warning", 5000)

    # ---------- komunikaty ----------
    def _notify(self, where: str, text: str, kind: str = "warning") -> None:
        """Komunikat trzyczęściowy: pełny pod sekcją, pierwsze zdanie w pasku stanu."""
        if where == "sync":
            self._sync_action_cb = None  # komunikat bez akcji wygasza poprzednią
        widget = self.input_msg if where == "input" else self.sync_msg
        widget.show_message(text, kind)
        head = text.split(". ")[0].rstrip(".") + "."
        status_message(self.statusBar(), head, kind, 8000)

    def _notify_sync_action(self, text: str, action_text: str,
                            on_action: Callable[[], None], kind: str = "warning") -> None:
        """Jak `_notify("sync", ...)`, ale z przyciskiem akcji w komunikacie
        (np. „Użyj X s" przy przestarzałym T0 z pamięci pliku)."""
        self._sync_action_cb = on_action
        self.sync_msg.show_message(text, kind, action_text=action_text)
        head = text.split(". ")[0].rstrip(".") + "."
        status_message(self.statusBar(), head, kind, 8000)

    def _on_sync_msg_action(self) -> None:
        cb, self._sync_action_cb = self._sync_action_cb, None
        if cb is not None:
            cb()

    def _ok(self, text: str) -> None:
        """Sukces: pasek stanu + czyszczenie komunikatów sekcji."""
        self.input_msg.clear()
        self._sync_action_cb = None
        self.sync_msg.clear()
        status_message(self.statusBar(), text, "success", 8000)

    def _require_video(self) -> bool:
        if self.video_path:
            return True
        self._notify("input", _TR("msg_no_video"))
        return False

    # ---------- pobranie sesji z API ----------
    def _fetch_id(self, silent: bool = False, then=None) -> None:
        """Pobiera dane sesji z API po ID — w wątku (sieć potrafi wisieć).

        `silent=True` — błąd tylko w pasku stanu (automatyczne wczytanie ustawień
        pliku); inaczej modal, bo bez danych nie ma czego renderować.
        `then` — kontynuacja po udanym pobraniu (łańcuch „Pobierz i przytnij").
        """
        sid = self.id_spin.value()

        def failed(msg: str) -> None:
            if silent:
                status_message(self.statusBar(),
                               f"Nie udało się pobrać danych z API (ID {sid}): {msg}",
                               "warning", 8000)
                return
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Critical)
            box.setWindowTitle("Błąd API")
            box.setText(f"Nie udało się pobrać sesji {sid} z API.\n"
                        "Sprawdź numer ID i połączenie z siecią, potem spróbuj ponownie.")
            box.setDetailedText(msg)
            box.exec()

        self._run_op(partial(api.fetch_session, sid), button=self.fetch_btn,
                     busy_text=_TR("busy_fetch"), status_text=_TR("busy_fetch"),
                     on_result=lambda sess: self._on_session_fetched(sess, then),
                     on_error=failed)

    def _on_session_fetched(self, session, then=None) -> None:
        self._api_session = session
        self.session = self._with_meta_override(session)
        self._set_meta_placeholders(session)
        self.timeline_edit.setPlainText(
            " | ".join(self._shot_to_text(s) for s in session.shots))
        parts = []
        if session.nazwa_toru:
            parts.append(f"Tor: {session.nazwa_toru}")
        if session.uczestnik:
            parts.append(f"Zawodnik: {session.uczestnik}")
        self.api_meta_label.setText("  |  ".join(parts))
        self.api_meta_label.setVisible(bool(parts))
        self._update_preview()
        self._ok(_TR("msg_session_fetched").format(self.id_spin.value(), len(session.shots)))
        if then is not None:
            then()

    def _fetch_id_and_trim(self):
        """Pobiera dane z API, ustala T0 (wykrywa bzyczek jeśli trzeba) i przycina
        film: 5 s przed T0 → ostatni strzał + 5 s.

        Łańcuch dwóch operacji w tle (API → detekcja bzyczka). Do v0.46.0 było to
        celowo synchroniczne, bo detekcja w tle bywała „cicho pusta"; teraz każdy
        krok melduje wynik w pasku stanu, więc ten powód zniknął, a okno nie zamiera.
        """
        if not self._require_video():
            return
        self._fetch_id(then=self._trim_after_fetch)

    def _trim_after_fetch(self) -> None:
        session = self.session
        if not (session and session.shots):
            self._notify("input", _TR("msg_no_timeline"))
            return
        t0 = self.t0_spin.value()
        if t0 > 0:
            self._apply_trim_for_t0(t0)   # T0 wykryty przy imporcie — nie liczymy drugi raz
            return
        src = self.lrf_path or self.video_path
        self._run_op(partial(audio_sync.detect_dji_start, src),
                     button=self.fetch_trim_btn, busy_text=_TR("busy_detect_start"),
                     status_text=_TR("busy_detect_start"),
                     on_result=self._on_t0_for_trim)

    def _on_t0_for_trim(self, detected) -> None:
        if detected is None:
            self._notify("sync", _TR("msg_no_start_signal"))
            return
        self._force_start_signal_mode()
        self._set_t0(detected, detector=audio_sync.START_DETECTOR_VERSION)
        self._apply_trim_for_t0(detected)

    def _apply_trim_for_t0(self, t0: float) -> None:
        session = self.session
        dur = self.waveform.duration or None
        start, end = render.auto_trim_window(
            t0, session.shots[-1].czas,
            tail=_TRIM_TAIL_S, lead_in=_LEAD_IN_S, duration=dur)
        self.trim_start_spin.setValue(start)
        self.trim_end_spin.setValue(end)
        self._ok(_TR("msg_trimmed").format(_fmt_time_s(round(start, 2)),
                                           _fmt_time_s(round(end, 2)))
                 + f" (T0={_fmt_time_s(round(t0, 2))} s, "
                   f"ostatni strzał {_fmt_time_s(round(session.shots[-1].czas, 2))} s)")

    @staticmethod
    def _shot_to_text(shot):
        if shot.split is None:
            return f"{shot.numer}: {shot.czas:.2f}s"
        return f"{shot.numer}: {shot.czas:.2f}s (+{shot.split:.2f}s)"

    # ---------- detekcje ----------
    def _detect(self):
        if not self._require_video():
            return
        src = self.lrf_path or self.video_path
        s = self.trim_start_spin.value()
        e = self.trim_end_spin.value() or None
        self._run_op(partial(audio_sync.detect_start, src, start=s, end=e),
                     button=self.detect_btn, busy_text=_TR("busy_detect_anchor"),
                     status_text=_TR("busy_detect_anchor"),
                     on_result=self._on_anchor_detected)

    def _on_anchor_detected(self, detected) -> None:
        if detected is None:
            self._notify("sync", _TR("msg_no_anchor"))
            return
        self.t0_spin.setValue(detected)  # wywoła _on_t0_spin → waveform + podgląd
        self._ok(_TR("msg_anchor_detected").format(_fmt_time_s(round(detected, 2))))

    def _detect_start_signal(self):
        """Wykrywa bzyczek shot-timera (filtr 2–4.8 kHz) i ustawia go jako T0.

        Wymusza tryb kotwicy „Sygnał startu” — wykryty bzyczek JEST sygnałem
        startu, więc T0 = czas bzyczka (bez przesunięcia o pierwszy strzał).
        """
        if not self._require_video():
            return
        src = self.lrf_path or self.video_path
        s = self.trim_start_spin.value()
        e = self.trim_end_spin.value() or None
        self._run_op(partial(audio_sync.detect_dji_start, src, start=s, end=e),
                     button=self.start_sig_btn, busy_text=_TR("busy_detect_start"),
                     status_text=_TR("busy_detect_start"),
                     on_result=self._on_start_signal_detected)

    def _on_start_signal_detected(self, detected) -> None:
        if detected is None:
            self._notify("sync", _TR("msg_no_start_signal"))
            return
        self._force_start_signal_mode()
        self._set_t0(detected, detector=audio_sync.START_DETECTOR_VERSION)
        self._ok(_TR("msg_t0_detected").format(_fmt_time_s(round(detected, 2))))

    def _detect_id_tone(self):
        """Dekoduje ID sesji z sygnału tonowego (timer po zapisie w bazie),
        po czym od razu pobiera dane z API i przycina film (jak „Pobierz
        i przytnij") — wykryte ID przeszło checksumę, więc dodatkowe kliknięcie
        „Pobierz" było tylko zbędnym krokiem.

        Zawsze analizuje `self.video_path` — NIE proxy LRF (proxy nie było
        częścią pomiaru, którym dobrano pasmo 5000–7000 Hz, a sygnał ID gra
        pod koniec nagrania, poza oknem, na którym LRF jest zwykle używane
        do detekcji T0).
        """
        if not self._require_video():
            return
        self._run_op(partial(pipeline.detect_id_tone, self.video_path),
                     button=self.detect_id_btn, busy_text=_TR("busy_detect_id"),
                     status_text=_TR("busy_detect_id"),
                     on_result=self._on_id_tone_detected)

    def _on_id_tone_detected(self, detected) -> None:
        if detected is None:
            if self.match_time_chk.isChecked() and self.video_path:
                # Opcja awaryjna: brak sygnału ID → dopasowanie po czasie nagrania.
                # Poprzednia operacja właśnie się skończyła (`_end_op` przed
                # callbackiem), więc slot `_run_op` jest wolny.
                status_message(self.statusBar(), _TR("status_no_tone_match_time"),
                               "info", 0)
                if self._match_session_by_time():
                    return
            self._notify("input", _TR("msg_no_id_tone"))
            return
        if detected.is_db_id:
            self._apply_detected_id(detected.value, str(detected.value))
            return
        # Kod tymczasowy (sesja nagrana offline): ID wpisu trzeba dopiero znaleźć
        # w bazie po `temp_id`. Poprzednia operacja właśnie się skończyła
        # (`_end_op` przed callbackiem), więc slot `_run_op` jest wolny.
        t0 = self.t0_spin.value()
        fn = partial(pipeline.resolve_id_tone, detected, self.video_path,
                     t0=t0 if t0 > 0 else None, info=self._video_info)
        self._run_op(fn, button=self.detect_id_btn,
                     busy_text=_TR("busy_temp_id_lookup"),
                     status_text=_TR("status_temp_id_lookup").format(detected.label),
                     on_result=self._on_temp_id_resolved)

    def _on_temp_id_resolved(self, result) -> None:
        """Wynik zapytania o kod tymczasowy: jedno ID → jak wykryte ID, brak
        rozstrzygnięcia → jak nieczytelny sygnał (bez zgadywania)."""
        if result.session_id is None:
            self._notify("input", result.info or _TR("msg_no_id_tone"))
            return
        self._apply_detected_id(result.session_id, result.info)

    def _apply_detected_id(self, session_id: int, label: str) -> None:
        self.id_spin.setValue(session_id)
        self._set_source("id")  # render ma użyć sesji z API, nie pola tekstowego
        self._ok(_TR("msg_id_detected").format(label))
        self._fetch_id_and_trim()

    def _match_session_by_time(self) -> bool:
        """Dopasowanie nagrania do sesji z kalkulatora PO CZASIE (w tle, sieć).

        T0 ze spinboxa (gdy > 0) zawęża dopasowanie do sekund — bez niego sesja
        może być gdziekolwiek w nagraniu. `hint_id` = bieżące ID (skraca awaryjny
        skan po ID na starym serwerze). Zwraca False, gdy inna operacja trwa.
        """
        if not self._require_video():
            return False
        t0 = self.t0_spin.value()
        fn = partial(pipeline.find_session_by_time, self.video_path,
                     t0=t0 if t0 > 0 else None,
                     info=self._video_info,
                     hint_id=self.id_spin.value() or None)
        # busy_text pusty: przycisk jest icon-only, tekst „Dopasowywanie…" wlazłby
        # obok ikony; komunikat idzie paskiem stanu (`status_text`).
        return self._run_op(fn, button=self.match_time_btn,
                            status_text=_TR("busy_match_time"),
                            on_result=self._on_time_match)

    def _on_time_match(self, result) -> None:
        if result.recording is None:
            self._notify("input", _TR("msg_time_match_no_rec"))
            return
        start = result.recording.start.strftime("%Y-%m-%d %H:%M:%S")
        if result.picked is not None:
            self._apply_time_match(result.picked)
            return
        if not result.ambiguous:
            self._notify("input", _TR("msg_time_match_none").format(
                start, result.recording.source))
            return
        hits = [m for m in result.matches if m.in_window]
        chosen = self._pick_time_match(hits, start)
        if chosen is None:
            self._notify("input", _TR("msg_time_match_cancelled"))
            return
        self._apply_time_match(chosen)

    def _apply_time_match(self, m) -> None:
        """Jak po udanym ID z audio: wpisz ID, przełącz źródło, pobierz i przytnij."""
        c = m.candidate
        self.id_spin.setValue(c.id)
        self._set_source("id")
        self._ok(_TR("msg_time_matched").format(
            c.id, c.nazwa_toru or "—", c.uczestnik or "—",
            _TR(f"time_match_basis_{m.basis}"), f"{m.delta_s:+.0f}"))
        self._fetch_id_and_trim()

    def _pick_time_match(self, hits, start: str):
        """Modalny wybór spośród kilku pasujących sesji; None = anulowano."""
        dlg = QDialog(self)
        dlg.setWindowTitle(_TR("time_match_dialog_title"))
        dlg.setMinimumWidth(620)
        lay = QVBoxLayout(dlg)
        info = QLabel(_TR("msg_time_match_ambiguous").format(start))
        info.setWordWrap(True)
        lay.addWidget(info)
        lst = QListWidget()
        for m in hits:
            c = m.candidate
            item = QListWidgetItem(_TR("time_match_row").format(
                c.id, c.nazwa_toru or "—", c.uczestnik or "—", c.liczba_strzalow,
                _fmt_time_s(round(c.czas_bazowy, 2)),
                _TR(f"time_match_basis_{m.basis}"), f"{m.delta_s:+.0f}")
                + (_TR("time_match_score").format(f"{m.shot_score:.1f}")
                   if m.shot_score is not None else ""))
            item.setData(Qt.UserRole, m)
            lst.addItem(item)
        lst.setCurrentRow(0)
        lst.itemDoubleClicked.connect(lambda _i: dlg.accept())
        lay.addWidget(lst)
        btns = QHBoxLayout()
        ok_btn = QPushButton("OK"); set_kind(ok_btn, "primary")
        ok_btn.clicked.connect(dlg.accept)
        cancel_btn = QPushButton("Anuluj"); set_kind(cancel_btn, "ghost")
        cancel_btn.clicked.connect(dlg.reject)
        btns.addStretch(1); btns.addWidget(cancel_btn); btns.addWidget(ok_btn)
        lay.addLayout(btns)
        dlg.show()
        _dark_titlebar(dlg)
        if dlg.exec() != QDialog.Accepted or lst.currentItem() is None:
            return None
        return lst.currentItem().data(Qt.UserRole)

    def _next_candidate(self):
        """Proponuje kolejny wykryty onset (po aktualnej kotwicy) jako kotwicę."""
        onsets = self.waveform.onsets
        if not onsets:
            self._notify("sync", _TR("msg_no_candidates"))
            return
        cur = self.t0_spin.value()
        nxt = next((o for o in onsets if o > cur + 1e-3), onsets[0])  # wrap do pierwszego
        self.t0_spin.setValue(nxt)
        self._ok(_TR("msg_anchor_detected").format(_fmt_time_s(round(nxt, 2))))

    # --- synchronizacja waveform <-> spinboxy ---
    def _on_wave_anchor(self, t: float):
        self.t0_spin.setValue(t)

    def _on_wave_trim(self, start: float, end: float):
        self._set_trim_silently(start, end)

    def _set_t0(self, value: float, *, detector: int | None) -> None:
        """Ustawia T0 programowo, znacząc pochodzenie do pamięci per-plik.

        `detector`: None = nieznana wersja (wpis wczytany sprzed śledzenia),
        0 = ręczna (nigdy nie proponujemy nowej detekcji), >=1 = wersja
        `audio_sync.START_DETECTOR_VERSION` z chwili detekcji. `_on_t0_spin`
        NIE nadpisuje tego na „ręczna" — ustawiamy `_suppress_manual_t0` na
        czas `setValue`, bo ten sam sygnał obsługuje też ręczną edycję przez
        użytkownika (bez flagi nie dałoby się ich odróżnić)."""
        self._t0_detector = detector
        self._suppress_manual_t0 = True
        try:
            self.t0_spin.setValue(value)
        finally:
            self._suppress_manual_t0 = False

    def _on_t0_spin(self, v: float):
        if not self._suppress_manual_t0:
            self._t0_detector = 0  # ręczna zmiana (spinbox albo klik na osi)
        self.waveform.set_anchor(v)
        self._sync_wave_shots()   # markery strzałów są w czasie ABSOLUTNYM (T0 + czas)
        self._update_preview_time()
        self._schedule_player_rebuild()   # T0 przesuwa okna czasowe nakładek
        if (self._player_active() and not self._priming
                and self.player.playbackState() != QMediaPlayer.PlayingState):
            self._seek(v)     # w pauzie podgląd stoi na kotwicy — jak statyczny
        self._request_frame()  # nowy czas → nowa klatka w tle (debounced)

    def _apply_auto_trim(self, *_):
        """Przycisk: ustaw przycięcie od (T0 − 5 s) do (ostatni strzał + margines).

        Zostaje SYNCHRONICZNE — to czysta arytmetyka na już znanych wartościach
        (żadnego FFmpeg/FFT/sieci), więc wątek byłby tu tylko kosztem.
        """
        if not self._require_video():
            return
        session = self.session or self._safe_session()
        if session is None or not session.shots:
            self._notify("sync", _TR("msg_no_timeline"))
            return
        mode = self._anchor_mode()
        real_t0 = audio_sync.resolve_t0(self.t0_spin.value(), mode, session.shots[0].czas)
        dur = self.waveform.duration or None
        start, end = render.auto_trim_window(
            real_t0, session.shots[-1].czas, tail=self.tail_spin.value(), duration=dur)
        self.trim_start_spin.setValue(start)
        self.trim_end_spin.setValue(end)
        self._ok(_TR("msg_trimmed").format(_fmt_time_s(round(start, 2)),
                                           _fmt_time_s(round(end, 2))))

    def _on_trim_spin(self):
        self.waveform.set_trim(self.trim_start_spin.value(), self.trim_end_spin.value())

    def _validate_trim(self) -> None:
        """Od ≤ do — walidacja po zakończeniu edycji pola (nie przy każdym znaku)."""
        start = self.trim_start_spin.value()
        end = self.trim_end_spin.value()
        bad = end > 0 and start >= end
        for spin in (self.trim_start_spin, self.trim_end_spin):
            spin.setProperty("invalid", "true" if bad else "false")
            repolish(spin)
        if bad:
            dur = self.waveform.duration or self.trim_end_spin.maximum()
            self.sync_msg.show_message(
                _TR("msg_trim_invalid").format(_fmt_time_s(round(dur, 2))), "danger")
        elif self.sync_msg.isVisible():
            self.sync_msg.clear()

    def _on_preview_at(self, t: float) -> None:
        """Ctrl+klik na waveformie → przewinięcie podglądu do czasu t.

        Gdy działa podgląd w ruchu, wystarczy `setPosition` (klatkę pokazuje
        player) — nie uruchamiamy wtedy ekstrakcji FFmpeg ani drugiego markera
        na osi. Bez playera (brak QtMultimedia, tryb edycji) zostaje stara
        droga: kursor podglądu + klatka wyciągnięta w tle."""
        if not self.video_path:
            return
        if self._player_ready():
            self.waveform.preview_t = None
            self._seek(t)
            return
        self._scrubber_t = t
        self._update_preview_time()
        self._scrubber_timer.start(_SCRUBBER_DEBOUNCE_MS)

    def _do_scrubber_preview(self) -> None:
        t = getattr(self, "_scrubber_t", None)
        if t is None or not self.video_path:
            return
        if self._frame_worker and self._frame_worker.isRunning():
            self._scrubber_timer.start(_BUSY_RETRY_MS)
            return
        self._frame_worker = FrameExtractWorker(self._frame_src(), t)
        self._frame_worker.done.connect(self._on_scrubber_frame_ready)
        self._frame_worker.failed.connect(
            lambda m: self.preview_label.setText("Błąd podglądu klatki:\n" + m))
        self._frame_worker.start()

    def _on_scrubber_frame_ready(self, frame: Image.Image, t: float) -> None:
        """Klatka scrubber gotowa → nałóż panel aktywny dla czasu t."""
        # Klatka scrubbera nie liczy `_preview_rects` (inny czas = inne panele),
        # więc stare ramki edycji znikają do najbliższego `_update_preview`.
        self.preview_label.set_edit_rects({})
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
            # Bez `break` — nakładka metadanych gra RÓWNOLEGLE z panelem strzału.
            for ev in events:
                if ev.start <= t < ev.end:
                    panel = ev.image
                    if ev.xy is not None:
                        x, y = ev.xy
                    elif ev.centered:
                        x = (frame.size[0] - panel.size[0]) // 2
                        y = (frame.size[1] - panel.size[1]) // 2
                    else:
                        x, y = overlay.panel_origin(panel.size, frame.size, pstyle)
                    composite.alpha_composite(panel, (x, y))
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
        self._frame_worker = FrameExtractWorker(self._frame_src(), anchor_t)
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
        self._sync_wave_shots()   # markery strzałów na osi idą z tej samej osi czasu
        if not self.video_path:
            return
        self._schedule_player_rebuild()
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
            if style.show_meta_panel:
                meta = overlay.render_meta_panel(session, pstyle, frame.size)
                if meta is not None:
                    mx, my = overlay.panel_origin_at(
                        meta.size, frame.size, pstyle.meta_position,
                        pstyle.meta_offset_x, pstyle.meta_offset_y)
                    frame.alpha_composite(meta, (mx, my))
                    self._preview_rects["meta"] = (mx, my, meta.size[0], meta.size[1])
            if style.show_running_clock:
                elapsed = (session.shots[0].czas
                           if (mode != AnchorMode.START_SIGNAL or edit) else 0.0)
                self._composite_clock(frame, pstyle, session, elapsed)
            self._show_image(frame)
            # Ramki nakładek w trybie edycji rysuje sam `PreviewLabel`.
            self.preview_label.set_edit_rects(self._preview_rects)
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
            meta_offset_x=int(round(style.meta_offset_x * s)),
            meta_offset_y=int(round(style.meta_offset_y * s)),
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

    # ---------- podgląd w ruchu (QMediaPlayer + nakładki na scenie) ----------
    # Nakładki NIE są malowane Pillow na każdą klatkę: `render.build_events` daje
    # te same okna czasowe co render, każde zdarzenie ląduje raz jako pixmapa na
    # scenie, a przy klatce przełączamy tylko widoczność. Zegar jest wyjątkiem
    # (treść zależy od czasu) — renderujemy go co dziesiątą sekundy i keszujemy.

    def _build_player(self) -> None:
        self.player = None
        self.player_page: VideoPlayerPage | None = None
        self._audio_out = None
        self._player_size: tuple[int, int] | None = None
        self._player_failed = False
        self._player_frames = 0            # licznik klatek (diagnostyka/weryfikacja)
        self._playhead_t = 0.0
        self._player_t0 = 0.0
        self._player_style: OverlayStyle | None = None
        self._player_session: Session | None = None
        self._clock_cache: dict[float, tuple[QPixmap, tuple[int, int]]] = {}
        self._clock_key: float | None = None
        self._frame_step_ms = _DEFAULT_FRAME_MS
        self._priming = False   # „rozgrzewanie": pierwsza klatka po wczytaniu pliku
        self._primed = False    # rozgrzewanie robimy RAZ na plik
        self._prime_pending = False
        if not _HAS_MULTIMEDIA:
            return
        self.player_page = VideoPlayerPage()
        self.player = QMediaPlayer(self)
        self._audio_out = QAudioOutput(self)
        self.player.setAudioOutput(self._audio_out)
        self.player.setVideoOutput(self.player_page.video_item)
        self.player.positionChanged.connect(self._on_player_position)
        self.player.playbackStateChanged.connect(self._on_player_state)
        self.player.errorOccurred.connect(self._on_player_error)
        self.player.mediaStatusChanged.connect(self._on_media_status)
        # Czas KLATKI (µs) jest dokładniejszy niż `position()` (ten idzie zegarem
        # odtwarzania), a nakładki muszą zmieniać się razem z obrazem.
        self.player_page.video_item.videoSink().videoFrameChanged.connect(
            self._on_video_frame)

    def _build_transport(self, bar: QHBoxLayout) -> None:
        """Pasek transportu: skok do T0, ±1 s, play/pauza, skok do „Do", pętla.

        Ikony ZAMIAST unikodowych glifów (`|◀`/`◀◀`/…) — glify jako sam tekst
        ucinały „Edytuj pozycje" przy 1180 px; `ToolButtonIconOnly` 20 px trzyma
        skróty w tooltipie (`_TR(tip_key)` ma już „(J)"/„(L)"/…).
        """
        self.transport_btns: list[QToolButton] = []
        # (button, icon name, fallback glyph key) — the `tr_*` string is the OLD
        # unicode glyph (`_apply_icon` falls back to it when the SVG plugin is
        # missing), not shown when the icon loads.
        self._transport_icon_btns: list[tuple[QToolButton, str, str]] = []

        def tbtn(key: str, tip_key: str, icon_name: str, slot, checkable: bool = False,
                 kind: str = "ghost") -> QToolButton:
            btn = QToolButton()
            btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
            btn.setIconSize(QSize(20, 20))
            btn.setCheckable(checkable)
            btn.setToolTip(_TR(tip_key))
            set_kind(btn, kind)
            (btn.toggled if checkable else btn.clicked).connect(slot)
            bar.addWidget(btn)
            self.transport_btns.append(btn)
            self._transport_icon_btns.append((btn, icon_name, key))
            return btn

        tbtn("tr_t0", "tip_tr_t0", "skip-start", self._seek_t0)
        tbtn("tr_back", "tip_tr_back", "step-back", partial(self._seek_by, -_SEEK_STEP_S))
        self.play_btn = tbtn("tr_play", "tip_tr_play", "play", self._on_play_toggled,
                             checkable=True, kind="secondary")
        tbtn("tr_fwd", "tip_tr_fwd", "step-forward", partial(self._seek_by, _SEEK_STEP_S))
        tbtn("tr_to", "tip_tr_to", "skip-end", self._seek_out)
        self.loop_btn = tbtn("tr_loop", "tip_tr_loop", "loop", lambda *_: None, checkable=True)
        self._refresh_transport()
        self._refresh_transport_icons()

    def _refresh_transport_icons(self) -> None:
        for btn, name, key in getattr(self, "_transport_icon_btns", []):
            _apply_icon(btn, name, 20, _TR(key))

    def _refresh_transport(self) -> None:
        enabled = self._player_active()
        for btn in self.transport_btns:
            btn.setEnabled(enabled)
            if not _HAS_MULTIMEDIA:
                btn.setToolTip(_TR("msg_no_multimedia"))
            elif not enabled and self._proxy_busy():
                btn.setToolTip(_TR("tip_proxy_building"))

    def _player_active(self) -> bool:
        """Player ma sprawne źródło (jest moduł, jest plik, backend nie odmówił)."""
        return (self.player is not None and not self._player_failed
                and self._player_size is not None)

    def _player_ready(self) -> bool:
        """Dodatkowo: nie jesteśmy w trybie edycji pozycji (tam rządzi Pillow)."""
        return self._player_active() and not self.edit_pos_btn.isChecked()

    def _show_preview_page(self) -> None:
        self.preview_stack.setCurrentWidget(
            self.player_page if self._player_ready() else self.preview_label)

    def _set_player_source(self, path: str) -> None:
        """Podmienia plik w playerze. Stary MUSI zostać zwolniony (stop + pusty
        QUrl), inaczej backend trzyma uchwyt i pamięć poprzedniego nagrania."""
        if self.player is None:
            return
        self._release_player()
        self._player_failed = False
        self._player_frames = 0
        self._priming = False
        self._primed = False
        self._prime_pending = False
        self._playhead_t = 0.0
        self.waveform.set_playhead(None)
        try:
            info = ffmpeg.probe(path)
            height = min(info.height, _PLAYER_OVERLAY_H) or _PLAYER_OVERLAY_H
            width = max(1, int(round(info.width * height / max(info.height, 1))))
            self._player_size = (width, height)
            self._frame_step_ms = (int(round(1000 / info.fps)) if info.fps
                                   else _DEFAULT_FRAME_MS)
        except Exception:  # noqa: BLE001 — bez metadanych nie ma czego odtwarzać
            self._player_size = None
            self._frame_step_ms = _DEFAULT_FRAME_MS
        if self._player_size is not None:
            self.player_page.set_canvas(self._player_size)
            self.player.setSource(QUrl.fromLocalFile(str(Path(path).resolve())))
        self._refresh_transport()

    def _set_player_pending(self) -> None:
        """Player bez źródła: proxy podglądu dopiero powstaje. Transport jest
        wyłączony (`_player_active()` = False), zostaje podgląd klatki."""
        self._release_player()
        self._player_failed = False
        self._player_frames = 0
        self._priming = False
        self._primed = False
        self._prime_pending = False
        self._playhead_t = 0.0
        self._player_size = None
        self.waveform.set_playhead(None)
        self._refresh_transport()

    def _release_player(self) -> None:
        if self.player is None:
            return
        self.player.stop()
        self.player.setSource(QUrl())
        if self.player_page is not None:
            self.player_page.clear_overlays()
        self._clock_cache.clear()
        self._clock_key = None
        self._player_size = None

    # --- sterowanie ---
    def _seek(self, t: float) -> None:
        if not self._player_active():
            return
        limit = self.waveform.duration or t
        t = max(0.0, min(t, limit))
        self.player.setPosition(int(round(t * 1000)))
        self._playhead_t = t
        self.waveform.set_playhead(t)
        self._update_preview_time()
        # W pauzie klatka przyjdzie asynchronicznie — nakładki ustawiamy od razu,
        # żeby panel nie „doganiał" obrazu o jedno zdarzenie.
        self._sync_overlays(t)
        # Klatka po przewinięciu bywa spóźniona ALBO przychodzi ze starym
        # znacznikiem czasu (backend dosyła to, co miał w kolejce) — po chwili
        # sprawdzamy, czy scena zgadza się z `position()`.
        QTimer.singleShot(_SEEK_VERIFY_MS, self._verify_seek_overlays)

    def _verify_seek_overlays(self) -> None:
        if not self._player_active() or self._priming:
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            return
        self._sync_overlays(self.player.position() / 1000.0)

    def _sync_overlays(self, t: float) -> None:
        """Ustawia scenę (widoczność zdarzeń + zegar) na czas `t`."""
        self._playhead_t = t
        self.player_page.update_time(t)
        self._update_player_clock(t)

    def _seek_by(self, delta: float) -> None:
        self._seek(self._playhead_t + delta)

    def _seek_frames(self, n: int) -> None:
        self._seek(self._playhead_t + n * self._frame_step_ms / 1000.0)

    def _seek_t0(self) -> None:
        self._seek(self.t0_spin.value())

    def _seek_out(self) -> None:
        self._seek(self.trim_end_spin.value())

    def _pause(self) -> None:
        if (self._player_active()
                and self.player.playbackState() == QMediaPlayer.PlayingState):
            self.player.pause()

    def _toggle_play(self) -> None:
        """Spacja i przycisk mają jedno wejście — stan trzyma przycisk."""
        if not self._player_active():
            status_message(self.statusBar(), _TR("msg_no_multimedia"), "warning", 6000)
            return
        self.play_btn.toggle()

    def _on_play_toggled(self, on: bool) -> None:
        if not self._player_active():
            self.play_btn.setChecked(False)
            return
        if on:
            self._priming = False   # świadomy start użytkownika kończy rozgrzewanie
            self._primed = True
            self._prime_pending = False
            self._audio_out.setMuted(False)
            # Odtwarzanie i edycja pozycji wykluczają się (różne strony stosu).
            if self.edit_pos_btn.isChecked():
                self.edit_pos_btn.setChecked(False)
            resume = self._playhead_t
            self.player.play()
            # PUŁAPKA (backend ffmpeg Qt): `setPosition` zrobione w PAUZIE na
            # nagraniu, które jeszcze nie było odtwarzane, bywa gubione przy
            # starcie — odtwarzanie rusza od 0 zamiast od kursora (zmierzone:
            # po prime + seek na T0-1 `play()` grał od zera). Po starcie
            # sprawdzamy pozycję i w razie czego przewijamy jeszcze raz.
            if resume > _PLAY_RESUME_TOL_S:
                QTimer.singleShot(_PLAY_RESUME_MS,
                                  partial(self._restore_play_pos, resume))
        else:
            self.player.pause()

    def _restore_play_pos(self, target: float) -> None:
        if (not self._player_active()
                or self.player.playbackState() != QMediaPlayer.PlayingState):
            return
        if abs(self.player.position() / 1000.0 - target) > _PLAY_RESUME_TOL_S:
            self.player.setPosition(int(round(target * 1000)))

    def _on_player_state(self, state) -> None:
        playing = state == QMediaPlayer.PlayingState
        self.play_btn.blockSignals(True)
        self.play_btn.setChecked(playing)
        self.play_btn.blockSignals(False)
        self.play_btn.setToolTip(_TR("tip_tr_pause") if playing else _TR("tip_tr_play"))
        _apply_icon(self.play_btn, "pause" if playing else "play", 20,
                    _TR("tr_pause") if playing else _TR("tr_play"))

    def _on_player_error(self, error, msg: str = "") -> None:
        if error == QMediaPlayer.NoError:
            return
        # Funkcja jest DODATKIEM — awaria backendu nie może zabrać użytkownikowi
        # podglądu klatki, więc wracamy na stronę statyczną i mówimy dlaczego.
        self._player_failed = True
        self.play_btn.setChecked(False)
        self._refresh_transport()
        self._show_preview_page()
        status_message(self.statusBar(),
                       _TR("msg_player_error").format(msg or str(error)), "warning", 10000)

    def _on_media_status(self, status) -> None:
        """Po wczytaniu pliku scena jest PUSTA, dopóki player czegoś nie zdekoduje —
        „rozgrzewamy" go wyciszonym play→pauza, żeby podgląd pokazywał klatkę T0
        od razu (jak podgląd statyczny), bez klikania „Odtwórz"."""
        # `LoadedMedia` wraca też po przewinięciach — rozgrzewamy RAZ na plik,
        # inaczej pauza z rozgrzewania potrafi przerwać odtwarzanie użytkownikowi.
        if status != QMediaPlayer.LoadedMedia or self._primed or self._priming:
            return
        self._primed = True
        self._priming = True
        self._audio_out.setMuted(True)
        self.player.play()

    def _finish_prime(self) -> None:
        self._prime_pending = False
        if not self._priming or not self._player_active():
            return
        self._priming = False
        self.player.pause()
        self._audio_out.setMuted(False)
        self._seek(self.t0_spin.value())

    def _on_player_position(self, ms: int) -> None:
        t = ms / 1000.0
        self._playhead_t = t
        self.waveform.set_playhead(t)
        self._update_preview_time()
        if self.player.playbackState() != QMediaPlayer.PlayingState:
            # W pauzie JEDYNĄ wiarygodną osią czasu jest `position()`: klatki
            # przychodzą rzadko i bywają sprzed przewinięcia.
            self._sync_overlays(t)
            return
        end = self.trim_end_spin.value()
        if end > 0 and t >= end - 0.03:
            if self.loop_btn.isChecked():
                self._seek(self.trim_start_spin.value())
            else:
                self.player.pause()

    def _on_video_frame(self, frame) -> None:
        if not frame.isValid():
            return
        self._player_frames += 1
        if self._priming:
            # Pauza i przewinięcie NIE mogą lecieć z wnętrza sygnału sinka
            # (reentrancja w backendzie) — odkładamy je na pętlę zdarzeń.
            # `_priming` gaśnie dopiero w `_finish_prime`: dopóki świeci, nikt
            # (także zrzuty i testy) nie uzna rozgrzewania za zakończone.
            if not self._prime_pending:
                self._prime_pending = True
                QTimer.singleShot(0, self._finish_prime)
            return
        pos = self.player.position() / 1000.0
        start_us = frame.startTime()
        frame_t = start_us / 1_000_000.0 if start_us >= 0 else -1.0
        if self.player.playbackState() != QMediaPlayer.PlayingState:
            # PUŁAPKA (v0.51.1): po `setPosition` w pauzie backend potrafi dosłać
            # klatkę ze znacznikiem SPRZED przewinięcia — nakładki zostawały wtedy
            # na starym zdarzeniu (plansza START zamiast panelu strzału na zrzucie
            # `09-icons-dark.png`). W pauzie prawdą jest `position()`, a wyraźnie
            # spóźniona klatka jest ignorowana.
            if frame_t >= 0 and pos - frame_t > _FRAME_STALE_S:
                return
            self._sync_overlays(pos)
            return
        self._sync_overlays(frame_t if frame_t >= 0 else pos)

    # --- nakładki ---
    def _schedule_player_rebuild(self) -> None:
        if self._player_active():
            self._player_rebuild_timer.start(_PLAYER_REBUILD_MS)

    def _rebuild_player_overlays(self) -> None:
        """Buduje pixmapy nakładek dla bieżącej sesji/stylu/T0 (jedna funkcja —
        wołana z `_update_preview`, zmiany T0 i po wczytaniu sesji)."""
        if not self._player_active():
            return
        self.player_page.clear_overlays()
        self._clock_cache.clear()
        self._clock_key = None
        self._player_session = None
        self._player_style = None
        session = self.session or self._safe_session()
        if session is None or not session.shots:
            return
        try:
            size = self._player_size
            pstyle = self._scaled_style(self.current_style(), size[1])
            t0 = audio_sync.resolve_t0(self.t0_spin.value(), self._anchor_mode(),
                                       session.shots[0].czas)
            duration = self.waveform.duration or (t0 + session.shots[-1].czas + 10)
            items = []
            for ev in render.build_events(session, t0, pstyle, size, duration):
                x, y = render._overlay_xy(ev, pstyle, size)
                items.append((_pil_to_pixmap(ev.image), x, y, ev.start, ev.end))
            self.player_page.set_overlays(items)
            self._player_session = session
            self._player_style = pstyle
            self._player_t0 = t0
        except Exception:  # noqa: BLE001 — jak w podglądzie: ślad, nie modal
            _log_ui_error("podgląd w ruchu")
            return
        self.player_page.update_time(self._playhead_t)
        self._update_player_clock(self._playhead_t)

    def _update_player_clock(self, t: float) -> None:
        """Zegar w podglądzie w ruchu: treść co dziesiątą sekundy (jak w renderze),
        zamrożony na ostatnim strzale, rozmiar stały (`clock_panel_max_size`)."""
        style, session = self._player_style, self._player_session
        if (style is None or session is None or not style.show_running_clock
                or not session.shots):
            self.player_page.set_clock(None)
            return
        if t < self._player_t0 - 1e-6:
            self.player_page.set_clock(None)
            self._clock_key = None
            return
        key = round(min(t - self._player_t0, session.shots[-1].czas), 1)
        if key == self._clock_key:
            return
        self._clock_key = key
        cached = self._clock_cache.get(key)
        if cached is None:
            size = self._player_size
            fixed = overlay.clock_panel_max_size(style, size, session.shots[-1].czas)
            panel = overlay.render_clock_panel(style, size, key, fixed)
            if style.clock_position == "auto":
                shot_fixed = overlay.shot_panel_max_size(session, style, size)
                xy = render._clock_xy(style, size, panel.size, shot_fixed[1],
                                      render._clock_gap(size, style))
            else:
                xy = render._clock_xy(style, size, panel.size, 0, 0)
            cached = (_pil_to_pixmap(panel), xy)
            if len(self._clock_cache) < _CLOCK_CACHE_MAX:
                self._clock_cache[key] = cached
        self.player_page.set_clock(*cached)

    # --- skróty transportu ---
    def _transport_shortcut(self, slot, is_space: bool = False) -> None:
        """Skróty jednoliterowe i Spacja działają tylko poza polami (skill §11)."""
        focused = QApplication.focusWidget()
        if isinstance(focused, (QLineEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox)):
            return
        if is_space and isinstance(focused, QAbstractButton):
            focused.click()   # Spacja na przycisku ma go kliknąć, nie odtwarzać
            return
        slot()

    def _home_key(self) -> None:
        # Na osi Home/End nadal ustawiają kotwicę na granicach zakresu — skrót
        # okna nie może tego zabrać widżetowi, który ma fokus.
        if QApplication.focusWidget() is self.waveform:
            self.waveform.commit_anchor(self.waveform.trim_start)
            return
        self._seek(self.trim_start_spin.value())

    def _end_key(self) -> None:
        if QApplication.focusWidget() is self.waveform:
            self.waveform.commit_anchor(self.waveform.trim_end)
            return
        self._seek(self.trim_end_spin.value())

    def _on_wave_add_shot(self, t: float) -> None:
        """M na osi → dopisz strzał w bieżącym czasie do ręcznej osi czasu.

        Czas strzału jest WZGLĘDEM T0 (model czasu aplikacji), a numery i splity
        przelicza `parser.format_timeline` — dzięki temu wstawienie strzału
        w środek sesji nie zostawia niespójnej numeracji."""
        if self._source_is_id():
            self._notify("input", _TR("msg_shot_text_only"))
            return
        text = self.timeline_edit.toPlainText().strip()
        try:
            shots = parse_timeline(text) if text else []
        except Exception:  # noqa: BLE001 — niedokończony tekst nie może zjeść klawisza
            self._notify("input", _TR("timeline_invalid"))
            return
        first = shots[0].czas if shots else 0.0
        t0 = audio_sync.resolve_t0(self.t0_spin.value(), self._anchor_mode(), first)
        rel = t - t0
        if rel < 0:
            self._notify("sync", _TR("msg_shot_before_t0"))
            return
        shots = sorted([*shots, Shot(numer=0, czas=round(rel, 2))], key=lambda sh: sh.czas)
        self.timeline_edit.setPlainText(format_timeline(shots))
        self._set_source("text")
        self._refresh_timeline_summary()
        self._update_preview()
        idx = next(i for i, sh in enumerate(shots) if abs(sh.czas - round(rel, 2)) < 1e-9)
        self._ok(_TR("msg_shot_added").format(idx + 1, _fmt_time_s(round(rel, 2))))

    def _sync_wave_shots(self) -> None:
        """Znaczniki strzałów na osi = czas ABSOLUTNY (T0 + czas strzału).

        W trybie „ID (API)" bierzemy pobraną sesję (`_build_session` odpytałoby
        tam sieć!), w trybie „Tekst" — aktualną zawartość pola osi czasu.
        """
        session = self.session if self._source_is_id() else self._safe_session()
        if session is None or not session.shots:
            self.waveform.set_shots([])
            return
        t0 = audio_sync.resolve_t0(self.t0_spin.value(), self._anchor_mode(),
                                   session.shots[0].czas)
        self.waveform.set_shots([t0 + sh.czas for sh in session.shots])

    def _editable_shots(self):
        """Strzały z pola tekstowego do edycji (None = nie da się edytować,
        komunikat już pokazany)."""
        if self._source_is_id():
            self._notify("input", _TR("msg_shot_text_only"))
            return None
        text = self.timeline_edit.toPlainText().strip()
        try:
            return parse_timeline(text) if text else []
        except Exception:  # noqa: BLE001 — niedokończony tekst nie może zjeść klawisza
            self._notify("input", _TR("timeline_invalid"))
            return None

    def _apply_edited_shots(self, shots, select: int | None) -> None:
        """Zapisuje zmienioną listę strzałów do pola osi (splity i numery
        przelicza `format_timeline`) i odświeża podsumowanie, podgląd oraz oś."""
        self.timeline_edit.setPlainText(format_timeline(shots))
        self._set_source("text")
        self._refresh_timeline_summary()
        self._update_preview()       # w środku woła `_sync_wave_shots`
        self._sync_wave_shots()      # …ale podgląd bywa wcześnie przerywany
        self.waveform.select_shot(select)

    def _on_wave_shot_moved(self, index: int, t: float) -> None:
        """Przeciągnięcie/←/→ na zaznaczonym strzale → nowy czas WZGLĘDEM T0.

        Po przesunięciu lista jest sortowana, więc strzał może zmienić numer —
        zaznaczenie wędruje za nim (nowy indeks), a nie za starym numerem."""
        shots = self._editable_shots()
        if shots is None:
            self._sync_wave_shots()   # cofnij podgląd przeciągnięcia
            return
        first = shots[0].czas if shots else 0.0
        t0 = audio_sync.resolve_t0(self.t0_spin.value(), self._anchor_mode(), first)
        rel = round(t - t0, 2)
        if rel < 0:
            self._notify("sync", _TR("msg_shot_before_t0"))
            self._sync_wave_shots()
            return
        try:
            shots = move_shot(shots, index, rel)
        except (IndexError, ValueError):
            self._sync_wave_shots()
            return
        idx = next((i for i, sh in enumerate(shots) if abs(sh.czas - rel) < 1e-9), None)
        self._apply_edited_shots(shots, idx)
        self._ok(_TR("msg_shot_moved").format((idx or 0) + 1, _fmt_time_s(rel)))

    def _on_wave_shot_deleted(self, index: int) -> None:
        """Delete/Backspace na zaznaczonym strzale — zaznaczenie po usunięciu gaśnie."""
        shots = self._editable_shots()
        if shots is None:
            return
        try:
            shots = delete_shot(shots, index)
        except IndexError:
            return
        self._apply_edited_shots(shots, None)
        self._ok(_TR("msg_shot_deleted").format(index + 1))

    # --- edycja pozycji nakładek przez przeciąganie w podglądzie ---
    def _on_edit_pos_toggled(self, on: bool) -> None:
        self.preview_label.set_edit_mode(on)
        self.preview_label.setCursor(Qt.OpenHandCursor if on else Qt.ArrowCursor)
        self._grab = None
        # Edycja pozycji dzieje się na statycznym podglądzie (Pillow = źródło
        # prawdy WYSIWYG), więc na czas edycji player pauzuje i schodzi ze sceny.
        if on:
            self._pause()
        self._show_preview_page()
        if on:
            status_message(
                self.statusBar(),
                "Tryb edycji pozycji: przeciągnij panel strzału, metadane lub zegar "
                "w podglądzie.", "info", 6000)
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
        # Zegar rysowany na wierzchu → ma priorytet w trafieniu; potem metadane.
        for key in ("clock", "meta", "panel"):
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
            pos = self.pos_combo.currentData()
            ox, oy, _ = self._invert_offset(pos, (nx, ny), (g["w"], g["h"]), (fw, fh))
            if ox is not None:
                self.off_x.setValue(int(round(ox / scale)))
            self.off_y.setValue(int(round(oy / scale)))
        elif g["key"] == "meta":
            pos = self.meta_pos_combo.currentData()
            ox, oy, _ = self._invert_offset(pos, (nx, ny), (g["w"], g["h"]), (fw, fh))
            if ox is not None:
                self.meta_off_x.setValue(int(round(ox / scale)))
            self.meta_off_y.setValue(int(round(oy / scale)))
        else:  # zegar
            cp = self.clock_pos_combo.currentData()
            if cp == "auto":
                # Przeciąganie wymaga konkretnego rogu — przejdź na róg panelu.
                cp = self.pos_combo.currentData()
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

    # ---------- źródło osi czasu (warstwa zgodności po zamianie radio → segmenty) ----------
    def _source_is_id(self) -> bool:
        """Czy oś czasu bierzemy z API po ID (zamiennik `rb_id.isChecked()`)."""
        return self.source_seg.value() == "id"

    def _set_source(self, key: str) -> None:
        """Ustawia źródło ("id"/"text"); klucze są te same co w `file_settings.json`."""
        self.source_seg.set_value(key)

    def _refresh_timeline_summary(self) -> None:
        """Walidacja inline osi czasu: podsumowanie albo powód błędu pod polem."""
        text = self.timeline_edit.toPlainText().strip()
        invalid = False
        if not text:
            self.timeline_label.setText("")
            set_role(self.timeline_label, "muted")
        else:
            try:
                shots = parse_timeline(text)
                if not shots:
                    raise ValueError(_TR("timeline_empty"))
            except Exception as exc:  # noqa: BLE001 — parser rzuca TimelineParseError
                invalid = True
                self.timeline_label.setText(f"{_TR('timeline_invalid')}: {exc}")
                set_role(self.timeline_label, "danger")
            else:
                first, last = shots[0].czas, shots[-1].czas
                self.timeline_label.setText(
                    f"{len(shots)} {_TR('timeline_shots')}, "
                    f"{_fmt_time_s(first)}–{_fmt_time_s(last)} s")
                set_role(self.timeline_label, "muted")
        # Pusta etykieta znika, żeby nie zostawiać dziury pod polem.
        self.timeline_label.setVisible(bool(self.timeline_label.text()))
        self.timeline_edit.setProperty("invalid", "true" if invalid else "false")
        repolish(self.timeline_edit)

    def _safe_session(self):
        try:
            return self._build_session()
        except Exception:  # noqa: BLE001
            return None

    def _show_image(self, pil_img):
        # Klatka bywa gotowa przed analizą audio — wtedy kończymy stan „ładowanie".
        # W trybie playera strona NIE jest przełączana (statyczny podgląd dalej
        # liczy `_preview_rects` dla trybu edycji, ale nie zasłania odtwarzania).
        self._show_preview_page()
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
        if not self.out_field.path():
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
            style=self.current_style(), mode=mode, out_path=self.out_field.path(),
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
            "source": self.source_seg.value(),
            "id": self.id_spin.value(),
            "timeline": self.timeline_edit.toPlainText(),
            "meta_track": self.meta_track_edit.text(),
            "meta_participant": self.meta_participant_edit.text(),
            "anchor": self._anchor_mode().value,
            "t0": self.t0_spin.value(),
            "t0_detector": self._t0_detector,  # None = nieznana wersja detektora
            "trim_start": self.trim_start_spin.value(),
            "trim_end": self.trim_end_spin.value(),
            "tail": self.tail_spin.value(),
            "gpu": self.gpu_chk.isChecked(),
            "no_overlay": self.no_overlay_chk.isChecked(),
            "format": self.format_combo.currentData(),
            "output": self.out_field.path(),
        }

    def _apply_file_settings(self, data: dict) -> None:
        """Przywraca parametry pliku zapisane przy poprzednim renderze/kolejce.

        Wywoływane po analizie audio (spiny czasu mają już poprawny zakres)."""
        try:
            style = OverlayStyle.from_dict(data["style"])
            self._apply_style(style)  # ustawia też język, zegar, planszę START
        except Exception:  # noqa: BLE001
            pass
        self._set_source("text" if data.get("source") == "text" else "id")
        if data.get("id"):
            self.id_spin.setValue(int(data["id"]))
        if data.get("timeline"):
            self.timeline_edit.setPlainText(data["timeline"])
        self.meta_track_edit.setText(str(data.get("meta_track") or ""))
        self.meta_participant_edit.setText(str(data.get("meta_participant") or ""))
        aidx = self.anchor_combo.findData(data.get("anchor", AnchorMode.START_SIGNAL.value))
        if aidx >= 0:
            self.anchor_combo.setCurrentIndex(aidx)
        self._set_t0(float(data.get("t0", 0.0)), detector=data.get("t0_detector"))
        self.trim_start_spin.setValue(float(data.get("trim_start", 0.0)))
        self.trim_end_spin.setValue(float(data.get("trim_end", 0.0)))
        self.tail_spin.setValue(float(data.get("tail", _TRIM_TAIL_S)))
        self.gpu_chk.setChecked(bool(data.get("gpu", True)))
        self.no_overlay_chk.setChecked(bool(data.get("no_overlay", False)))
        fidx = self.format_combo.findData(data.get("format", "mp4"))
        if fidx >= 0:
            self.format_combo.setCurrentIndex(fidx)
        if data.get("output"):
            self.out_field.set_path(data["output"], emit=False)
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
        video = self.video_field.path() or (self.video_path or "<wideo>")
        parts += ["--video", _cli_quote(video)]

        no_overlay = self.no_overlay_chk.isChecked()
        if not no_overlay:
            if self._source_is_id():
                parts += ["--id", str(self.id_spin.value())]
            else:
                tl = self.timeline_edit.toPlainText().strip()
                if tl:
                    parts += ["--timeline", _cli_quote(tl)]
            track = self.meta_track_edit.text().strip()
            if track:
                parts += ["--track-name", _cli_quote(track)]
            part = self.meta_participant_edit.text().strip()
            if part:
                parts += ["--participant", _cli_quote(part)]

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

        out = self.out_field.path()
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
            "Uwaga: CLI odwzorowuje wideo, źródło osi (ID/tekst), tor/uczestnika, T0,\n"
            "kotwicę, język, przycięcie, enkoder, płynący zegar i tryb „bez nakładki”. Szczegóły wyglądu\n"
            "nakładki (kolory, skala, pozycja panelu, offsety, plansza START) NIE są\n"
            "obsługiwane w CLI i zostały pominięte.")
        note.setProperty("role", "muted")
        note.setWordWrap(True)
        lay.addWidget(note)
        btns = QHBoxLayout()
        copy_btn = QPushButton("Kopiuj do schowka")
        copy_btn.clicked.connect(
            lambda: (QApplication.clipboard().setText(cmd),
                     status_message(self.statusBar(),
                                    "Skopiowano komendę CLI do schowka.", "success", 4000)))
        close_btn = QPushButton("Zamknij")
        close_btn.clicked.connect(dlg.accept)
        btns.addStretch(1); btns.addWidget(copy_btn); btns.addWidget(close_btn)
        lay.addLayout(btns)
        dlg.show()
        _dark_titlebar(dlg)
        dlg.exec()

    def _start_render(self):
        if self._render_busy:
            status_message(self.statusBar(), _TR("msg_render_busy"), "warning", 8000)
            return
        kwargs = self._collect_render_kwargs()
        if kwargs is None:
            return
        self._save_file_settings()  # zapamiętaj parametry tego pliku
        self._render_busy = True
        self._set_render_enabled(False)
        self.open_btn.setVisible(False)  # pokaż dopiero po udanym renderze
        self.act_open_folder.setVisible(False)
        status_message(self.statusBar(), "Renderowanie…", "info", 0)
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

    def _set_render_enabled(self, idle: bool) -> None:
        """Stan „Renderuj"/„Zatrzymaj" w formularzu I w pasku akcji (jedno źródło prawdy).

        Bez wczytanego wideo „Renderuj" jest wyłączone — w stanie pustym jedynym
        przyciskiem primary jest „Otwórz wideo…".
        """
        can_render = idle and bool(self.video_path)
        self.render_btn.setEnabled(can_render)
        self.act_render.setEnabled(can_render)
        self.cancel_btn.setEnabled(not idle)
        self.act_cancel.setEnabled(not idle)
        self.act_cancel.setVisible(not idle)
        # „Zapisz klatkę" nie zależy od stanu renderu (czytanie oryginału FFmpeg-iem
        # obok trwającego renderu jest bezpieczne) — tylko od wczytanego pliku.
        if getattr(self, "save_frame_btn", None) is not None:
            self.save_frame_btn.setEnabled(bool(self.video_path))

    def _cancel_render(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.cancel_btn.setEnabled(False)
            self.act_cancel.setEnabled(False)
            self.cancel_btn.setText("Zatrzymywanie…")

    def _reset_render_ui(self) -> None:
        """Przywraca przyciski renderu po zakończeniu (sukces/błąd/anulowanie)."""
        self._render_busy = False
        self._set_render_enabled(True)
        self.cancel_btn.setText(_TR("act_cancel"))
        self._maybe_start_proxy()   # render miał pierwszeństwo — teraz można

    def _on_cancelled(self):
        self._reset_render_ui()
        self.progress.setValue(0)
        status_message(self.statusBar(), _TR("msg_render_cancelled"), "warning", 8000)

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
            set_role(self.nvenc_label, "success")
        elif ffmpeg.has_nvenc():
            self.nvenc_label.setText("NVENC: wykryty, ale test nie przeszedł — "
                                     "render na CPU (najedź, by zobaczyć powód)")
            set_role(self.nvenc_label, "warning")
            self.nvenc_label.setToolTip(render.nvenc_diagnostic() or "")
        else:
            self.nvenc_label.setText("NVENC: niedostępny — render na CPU "
                                     "(zainstaluj pełny FFmpeg)")
            set_role(self.nvenc_label, "warning")

    def _on_format_changed(self, *_):
        """Aktualizuje rozszerzenie pliku wyjściowego gdy zmienia się format."""
        current = self.out_field.path()
        if not current:
            return
        p = Path(current)
        fmt = self.format_combo.currentData()
        new_ext = _FORMAT_EXT.get(fmt, ".mp4")
        # Zamień obecne rozszerzenie tylko jeśli jest znane (mp4/webm/gif/mov/avi/mkv).
        if p.suffix.lower() in (".mp4", ".webm", ".gif", ".mov", ".avi", ".mkv"):
            self.out_field.set_path(str(p.with_suffix(new_ext)), emit=False)

    def _on_no_overlay_toggled(self, state):
        self.appearance_box.setDisabled(bool(state))

    def _on_done(self, path: str):
        """Sukces = pasek stanu + droga do pliku; modal TYLKO gdy jest ostrzeżenie
        (np. fallback enkodera) — udany render nie wymaga decyzji użytkownika."""
        self._reset_render_ui()
        self.last_output = path
        self.open_btn.setVisible(True)
        self.open_btn.setEnabled(True)
        self.act_open_folder.setVisible(True)
        enc = {"h264_nvenc": "GPU (NVENC)", "libx264": "CPU (x264)"}.get(self._used_encoder, "")
        text = _TR("msg_render_done").format(Path(path).name)
        if enc:
            text += f" [{enc}]"
        status_message(self.statusBar(), text, "success", 10000)
        if self._render_warn:
            QMessageBox.information(self, "Gotowe", f"Zapisano:\n{path}\n\n⚠ {self._render_warn}")

    def _on_fail(self, msg: str):
        """Błąd blokujący → modal, ale bez ściany tekstu: zdanie + „Pokaż szczegóły"
        z pełnym wyjściem FFmpeg (skill §10 — traceback nie idzie na front)."""
        self._reset_render_ui()
        status_message(self.statusBar(), _TR("render_failed_title"), "danger", 10000)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle(_TR("render_failed_title"))
        box.setText(_TR("render_failed_text"))
        box.setDetailedText(msg)
        box.exec()

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
        _dark_titlebar(win)
        win.raise_()

    def _show_queue_window(self):
        win = self._get_queue_window()
        win.show()
        _dark_titlebar(win)
        win.raise_()

    def _show_batch_window(self):
        # Współdziel runner/okno kolejki — wsad tylko dokłada do nich zadania.
        queue_win = self._get_queue_window()
        if self._batch_window is None:
            self._batch_window = BatchDialog(
                self._queue_runner, queue_win, self.current_style(), parent=None)
        else:
            # odśwież wspólny styl (mógł się zmienić w głównym oknie); zegar we wsadzie
            # to wariant wyjścia (QSettings), nie kopia checkboxa z głównego okna
            self._batch_window._base_style = self.current_style()
        self._batch_window.show()
        _dark_titlebar(self._batch_window)
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
                lambda: self._set_render_enabled(True)
            )
            self._queue_window = RenderQueueWindow(runner, parent=None)
        return self._queue_window

    def closeEvent(self, event):
        # Zapisz ustawienia bieżącego pliku (np. wpisane ID z API), by były przy
        # następnym otwarciu — nawet bez renderu/kolejki.
        if self.video_path and self._file_settings_ready:
            self._save_file_settings()
        # Player musi zwolnić plik i backend PRZED zamknięciem okna — inaczej
        # zdarza się crash przy niszczeniu sceny z żywym strumieniem.
        self._release_player()
        # Przerwij bezpośredni render, by nie niszczyć działającego QThread.
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(_THREAD_JOIN_MS)
        if self._queue_runner is not None and self._queue_runner._running:
            self._queue_runner.stop()  # pauzuje kolejkę + ubija biegnące rendery
            for w in self._queue_runner.active_workers():
                w.wait(_THREAD_JOIN_MS)
        # Operacje w tle (detekcje, API) — ta sama pułapka QThread co niżej.
        for worker in list(self._op_workers):
            worker.cancel()
            worker.wait(_THREAD_JOIN_MS)
        # Poczekaj na workery przygotowania wsadu (QThread niszczony w trakcie = crash).
        if self._batch_window is not None:
            for worker in list(self._batch_window._workers.values()):
                worker.wait(_THREAD_JOIN_MS)
        # Miniatura kolejki: worker żyje niezależnie od stanu renderu/kolejki.
        if self._queue_window is not None and self._queue_window._thumb_worker is not None:
            self._queue_window._thumb_worker.wait(_THREAD_JOIN_MS)
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


def _pct_spin() -> QSpinBox:
    """Skala nakładki pokazywana jako procent (30–500 %), zapisywana jako ułamek.

    Konwersja ×/÷100 żyje WYŁĄCZNIE w widoku (`_pct_value` / `_set_pct`) —
    `OverlayStyle.scale` i pliki ustawień nadal trzymają float (0.8, 1.25).
    """
    s = QSpinBox()
    s.setRange(30, 500)
    s.setSingleStep(5)
    s.setSuffix(" %")
    s.setValue(100)
    s.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return s


def _pct_value(spin: QSpinBox) -> float:
    return spin.value() / 100.0


def _set_pct(spin: QSpinBox, value: float) -> None:
    spin.setValue(int(round(value * 100)))


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


def _theme_mode() -> str:
    """Tryb motywu zapisany w QSettings (`ui/theme`); domyślnie ciemny."""
    try:
        value = QSettings().value("ui/theme", "dark")
        return "light" if str(value) == "light" else "dark"
    except Exception:  # noqa: BLE001
        return "dark"


def _dark_titlebar(widget) -> None:
    """Ciemna belka okna wg bieżącego motywu — wołaj PO `show()`."""
    try:
        set_windows_dark_titlebar(widget, _theme_mode() == "dark")
    except Exception:  # noqa: BLE001 — brak uchwytu okna (offscreen)
        pass


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


def _pop_flag(argv: list[str], name: str) -> bool:
    """Usuń flagę bez wartości z `argv`; True gdy była obecna."""
    if name in argv:
        argv.remove(name)
        return True
    return False


def _pop_option(argv: list[str], name: str) -> str | None:
    """Usuń flagę z wartością z `argv` i zwróć tę wartość (albo None)."""
    if name not in argv:
        return None
    i = argv.index(name)
    value = argv[i + 1] if i + 1 < len(argv) else None
    del argv[i:i + (2 if value is not None else 1)]
    return value


# Oś czasu do zrzutów (--screenshot --video): kilka strzałów z widocznymi splitami.
_SHOT_DEMO_TIMELINE = ("1: 1.5s | 2: 2.1s (+0.6s) | 3: 2.9s (+0.8s) | "
                       "4: 3.6s (+0.7s) | 5: 4.4s (+0.8s) | 6: 5.3s (+0.9s)")


def _screenshot_helper_window(win: "MainWindow", kind: str,
                              video_path: str | None = None) -> QWidget:
    """Buduje okno pomocnicze (`kind` = "queue"/"batch") z kilkoma przykładowymi
    wierszami w różnych statusach — TYLKO do zrzutów `--screenshot --window`.

    `video_path` (z `--screenshot --window queue --video PLIK`): gdy podany,
    wiersze demo dostają PRAWDZIWĄ ścieżkę wideo (miniatura wyciąga realną
    klatkę zamiast placeholdera) — bez niego video_path == etykieta wiersza
    (`"plik → wyjście"`), co i tak nie jest czytelną ścieżką dla FFmpeg, więc
    miniatura zostaje placeholderem (świadomie dopuszczalne, patrz CLAUDE.md)."""
    if kind == "queue":
        qwin = win._get_queue_window()
        demo = (
            (JobStatus.PENDING, "sesja_042.mp4 → sesja_042_PiRoOverlay.mp4", 0.0, None),
            (JobStatus.RUNNING, "sesja_043.mp4 → sesja_043_PiRoOverlay.mp4", 0.42, None),
            (JobStatus.FAILED, "sesja_044.mp4 → sesja_044_PiRoOverlay.mp4", 0.0,
             "FFmpeg: kod wyjścia 1 — Nothing was written (drugi strumień wideo)"),
        )
        for status, label, progress, error in demo:
            kwargs = {"video_path": video_path or label}
            if video_path:
                kwargs["t0"] = 1.0
            job = RenderJob(id=uuid.uuid4().hex, label=label, kwargs=kwargs)
            qwin.add_job(job)
            row = qwin._rows[job.id]
            row.update_status(status)
            if status == JobStatus.RUNNING:
                row.update_progress(progress)
            if error:
                row.set_error(error)
        qwin.resize(760, 420)
        qwin.show()
        qwin.raise_()
        return qwin

    if kind == "batch":
        win._show_batch_window()
        bwin = win._batch_window
        demo = (
            (BatchRowStatus.NEEDS_ID, 0, ""),
            (BatchRowStatus.READY, 305, ""),
            (BatchRowStatus.FAILED, 306, "API: sesja o tym ID nie istnieje"),
        )
        for i, (status, session_id, error) in enumerate(demo):
            path = f"D:/nagrania/sesja_{40 + i}.mp4"
            row = bwin._add_row(path, session_id=session_id)
            if row is None:
                continue
            row.status = status
            row.error = error
            if status == BatchRowStatus.READY:
                row.id_source = "tone"
                row.prep = {"t0": 3.42, "trim_start": 0.0, "trim_end": 45.2,
                            "session": Session(shots=[Shot(1, 1.5), Shot(2, 2.6, 1.1)],
                                               nazwa_toru="Tor 3 — Bill drill",
                                               uczestnik="Jan K.")}
            if status == BatchRowStatus.FAILED:
                row.id_source = "time"
            bwin._sync_row(row)
        bwin._refresh()
        bwin.resize(820, 720)
        bwin.show()
        bwin.raise_()
        return bwin

    raise ValueError(f"nieznane okno do zrzutu: {kind!r}")


def main():
    _install_crash_logging()

    # Flagi deweloperskie GUI (bez argparse — `app.py` przekazuje KAŻDY argument
    # do CLI, więc te flagi żyją wyłącznie tutaj i są zdejmowane przed QApplication).
    argv = list(sys.argv)
    shot_path = _pop_option(argv, "--screenshot")
    shot_video = _pop_option(argv, "--video")   # tylko z --screenshot (zrzut z nagraniem)
    shot_edit = _pop_flag(argv, "--edit")       # zrzut w trybie „Edytuj pozycje"
    shot_id = _pop_option(argv, "--id")         # z --video: prawdziwa sesja z API zamiast demo osi
    shot_at = _pop_option(argv, "--at")         # z --video: pauza playera na T0+N s (domyślnie 1.5)
    # z --video: zapisz klatkę z nakładką (jak przycisk „Zapisz klatkę") do PATH,
    # bez dialogu — weryfikacja `preview.render_still` na realnym nagraniu
    shot_save_frame = _pop_option(argv, "--save-frame")
    # z --video (bez --id): zaznacz N-ty strzał na osi (numeracja jak na pastylce, od 1)
    shot_select = _pop_option(argv, "--select-shot")
    # zrzut okna pomocniczego zamiast głównego: "queue" (kolejka) albo "batch" (wsad)
    shot_window = _pop_option(argv, "--window")
    scale = _pop_option(argv, "--scale")
    force_light = _pop_flag(argv, "--light")
    if shot_path:
        # Zmienne środowiskowe z powłoki WSL nie docierają pewnie do procesu
        # Windows — tryb zrzutu ustawia je sam, PRZED utworzeniem QApplication.
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        if sys.platform == "win32":
            # Platforma offscreen na Windows nie ma własnej bazy fontów —
            # bez tego tekst renderuje się jako prostokąty.
            os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
    if scale:
        os.environ["QT_SCALE_FACTOR"] = str(scale)

    setup_hidpi()                          # musi być przed QApplication
    set_app_user_model_id("Piro.Overlay")  # ikona i grupowanie w pasku zadań (.exe)

    app = QApplication(argv)
    app.setApplicationName("PiroOverlay")
    app.setOrganizationName("Piro")        # QSettings wymaga org + app
    app.setApplicationVersion(__version__)
    app.setWindowIcon(QIcon(resources.icon_path()))
    load_app_fonts(Path(resources.font_path()).parent)

    mode = "light" if force_light else _theme_mode()
    theme = apply_theme(app, mode)

    app._wheel_guard = WheelGuard(app)   # referencja, by filtr nie zniknął (GC)
    app.installEventFilter(app._wheel_guard)

    settings = QSettings()
    win = MainWindow()
    win.setMinimumSize(960, 600)   # inspektor + podgląd bez ucinania
    win.sync_theme_action(theme["mode"])
    if shot_path:
        win.resize(1180, 760)   # stały rozmiar = powtarzalne zrzuty
    elif not restore_window_state(win, settings, win.splitter):
        win.resize(1180, 760)
    win.show()
    try:
        set_windows_dark_titlebar(win, theme["mode"] == "dark")
    except Exception:  # noqa: BLE001 — offscreen nie ma uchwytu okna
        pass

    if shot_path and shot_window:
        sub = _screenshot_helper_window(win, shot_window, video_path=shot_video)
        for _ in range(10):
            app.processEvents()
        if shot_window == "queue" and shot_video:
            # Miniatury się wyciągają w tle (jeden `QueueThumbWorker` naraz) —
            # zrzut musi je doczekać, inaczej łapie placeholdery mimo realnego pliku.
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                app.processEvents()
                if sub._thumb_worker is None and not sub._thumb_pending:
                    break
                time.sleep(0.05)
        try:
            set_windows_dark_titlebar(sub, theme["mode"] == "dark")
        except Exception:  # noqa: BLE001 — offscreen nie ma uchwytu okna
            pass
        for _ in range(5):
            app.processEvents()
        ok = sub.grab().save(shot_path)
        print(("zapisano " if ok else "BŁĄD ") + shot_path)
        return 0 if ok else 1

    if shot_path:
        if shot_video:
            # WYJĄTEK od zakazu `processEvents` w pętli: tryb zrzutu nie ma pętli
            # zdarzeń, a musi doczekać analizy audio i detekcji T0 w wątkach.
            win._set_video(shot_video)
            # Budowa proxy podglądu (4K/HEVC) potrafi trwać kilkadziesiąt sekund
            # — zrzut MUSI jej doczekać, inaczej łapie stronę „przygotowuję".
            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                app.processEvents()
                if (win.waveform.duration and win._op_worker is None
                        and not win._proxy_busy() and not win._t0_recheck_busy):
                    break
                time.sleep(0.05)
            for _ in range(10):
                app.processEvents()
            if shot_id:
                # Prawdziwa sesja z API (zrzuty do README): „Pobierz i przytnij"
                # = fetch + T0 + auto-przycięcie, jak kliknięcie w GUI.
                win.id_spin.setValue(int(shot_id))
                win._set_source("id")
                # Świeża detekcja T0 — zapisane ustawienia pliku (`file_settings.json`)
                # mają pierwszeństwo i mogą nieść stary T0 sprzed poprawek detekcji.
                win._detect_start_signal()
                deadline = time.monotonic() + 120
                while time.monotonic() < deadline:
                    app.processEvents()
                    if win._op_worker is None:
                        break
                    time.sleep(0.05)
                win._fetch_id_and_trim()
                deadline = time.monotonic() + 120
                while time.monotonic() < deadline:
                    app.processEvents()
                    if win.session is not None and win._op_worker is None:
                        break
                    time.sleep(0.05)
                for _ in range(10):
                    app.processEvents()
            else:
                # Oś bez markerów niczego nie pokazuje — zrzut dostaje demo osi czasu.
                win.timeline_edit.setPlainText(_SHOT_DEMO_TIMELINE)
                win._set_source("text")
                win._refresh_timeline_summary()
            if shot_edit:
                win.edit_pos_btn.setChecked(True)
            dur = win.waveform.duration
            if dur and not shot_id:
                t0 = win.t0_spin.value()
                # zrzut ma pokazać WĘŻSZY zakres Od…Do niż całe nagranie
                win.trim_start_spin.setValue(max(0.0, t0 - 2.0))
                win.trim_end_spin.setValue(min(dur, t0 + 8.0))
            if dur:
                # kursor podglądu i fokus na osi (pierścień fokusu musi być widoczny)
                win.waveform.preview_t = min(dur, win.t0_spin.value() + 2.0)
            win.waveform.setFocus()
            win._update_preview()
            win._update_preview_time()
            if shot_select:
                win.waveform.select_shot(int(shot_select) - 1)
            for _ in range(10):
                app.processEvents()
            # Podgląd w ruchu: rusz odtwarzanie, poczekaj na pierwszą klatkę,
            # zapauzuj i stań na T0+1,5 s (panel strzału musi być widoczny).
            if win._player_active():
                def _wait(cond, limit=15.0):
                    end = time.monotonic() + limit
                    while time.monotonic() < end and not cond():
                        app.processEvents()
                        time.sleep(0.03)

                win._rebuild_player_overlays()
                # Player sam się „rozgrzewa" po wczytaniu pliku (play→pauza na
                # pierwszej klatce); zrzut czeka, aż to się skończy.
                _wait(lambda: win._primed and not win._priming)
                if win._player_frames == 0:
                    win.player.play()
                    _wait(lambda: win._player_frames > 0)
                    win.player.pause()
                # Pauza i przewinięcie są ASYNCHRONICZNE — bez czekania na stan
                # i na pozycję zrzut łapie losową klatkę (albo pustą scenę).
                _wait(lambda: win.player.playbackState()
                      != QMediaPlayer.PlayingState, 5.0)
                target = win.t0_spin.value() + (float(shot_at) if shot_at else 1.5)
                frames_before = win._player_frames
                win._seek(target)
                _wait(lambda: abs(win.player.position() / 1000.0 - target) < 0.25, 5.0)
                # Klatka po seeku przychodzi asynchronicznie — bez tego zrzut
                # potrafi złapać pustą scenę (same nakładki na tle).
                _wait(lambda: win._player_frames > frames_before, 8.0)
                for _ in range(10):
                    app.processEvents()
                print(f"player: klatki={win._player_frames} "
                      f"pos={win.player.position()} ms (cel {target:.2f} s)")
            if shot_save_frame:
                # Ta sama ścieżka domenowa co przycisk „Zapisz klatkę" (Ctrl+S),
                # ale synchronicznie i bez dialogu — tryb zrzutu nie ma pętli
                # zdarzeń dla `_run_op`/QThread.
                still_t = win._current_still_time()
                still_session = win.session or win._safe_session()
                still_mode = win._anchor_mode()
                still_first_shot = (still_session.shots[0].czas
                                    if still_session and still_session.shots else 0.0)
                still_t0 = audio_sync.resolve_t0(win.t0_spin.value(), still_mode,
                                                 still_first_shot)
                still_dur = win.waveform.duration or (still_t + 10.0)
                still_img = preview.render_still(
                    win.video_path, still_t, still_session, still_t0,
                    win.current_style(), still_dur)
                still_img.save(shot_save_frame)
                print(f"zapisano klatkę {shot_save_frame} (t={still_t:.2f} s, "
                      f"{still_img.size[0]}x{still_img.size[1]})")
        for _ in range(5):
            app.processEvents()
        ok = win.grab().save(shot_path)
        print(("zapisano " if ok else "BŁĄD ") + shot_path)
        area = win.findChild(QScrollArea)
        if area is not None and area.widget() is not None:
            inner_w = area.widget()
            print(f"inspektor minimumSizeHint: {inner_w.minimumSizeHint().width()} px, "
                  f"viewport: {area.viewport().width()} px")
            if os.environ.get("PIRO_UI_DEBUG"):
                for child in inner_w.findChildren(QWidget):
                    mw = child.minimumSizeHint().width()
                    if mw > 120:
                        print(f"  {type(child).__name__} "
                              f"{child.objectName() or child.accessibleName() or ''} "
                              f"min={mw} text={getattr(child, 'text', lambda: '')()!r:.40}")
            root_name, ext = os.path.splitext(shot_path)
            insp = root_name + "_inspector" + ext
            inner = area.widget()
            # QScrollArea ma przezroczyste tło (QSS), a `grab()` na przezroczystym
            # płótnie gubi krycie tekstu etykiet — renderujemy na tło z tokenów.
            pix = QPixmap(inner.size())
            pix.fill(QColor(ui_theme.TOKENS[theme["mode"]]["bg"]))
            inner.render(pix)
            if pix.save(insp):
                print("zapisano " + insp)
        # Tryb zrzutu kończy się bez pętli zdarzeń — żywy QThread (klatka/audio)
        # ginie razem z interpreterem i Qt wywala proces PO wypisaniu wyniku.
        for worker in (win._frame_worker, win.wave_worker):
            if worker is not None and worker.isRunning():
                worker.wait(_THREAD_JOIN_MS)
        win._release_player()
        return 0 if ok else 1

    app.aboutToQuit.connect(lambda: save_window_state(win, settings, win.splitter))

    checker = UpdateChecker()
    checker.update_available.connect(lambda v: _show_update_dialog(win, v))
    checker.start()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
