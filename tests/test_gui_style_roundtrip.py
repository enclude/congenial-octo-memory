"""Round-trip stylu przez widgety GUI (pomijany bez PySide6 — WSL/build .exe).

Strażnik iteracji III odświeżenia UI: zamiana kontrolek (ColorSwatchButton,
skala pokazywana w procentach) NIE może zmienić wartości zapisywanych w
`OverlayStyle` ani w plikach ustawień.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from piro_overlay import gui  # noqa: E402
from piro_overlay.models import Lang, OverlayStyle  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_style_roundtrip_through_widgets(app):
    style = OverlayStyle(
        lang=Lang.EN,
        scale=0.75,
        position="top-right",
        offset_x=33, offset_y=44,
        panel_mode="list",
        list_max_rows=4,
        list_show_progress=False,
        list_pin_first_shot=False,
        show_meta_panel=True,
        meta_position="bottom-right",
        meta_offset_x=12, meta_offset_y=13,
        bg_color=(1, 2, 3, 4),
        text_color=(250, 249, 248, 247),
        accent_color=(10, 20, 30, 40),
        border_color=(5, 6, 7, 8),
        border_enabled=False,
        border_width=7,
        show_running_clock=True,
        clock_position="top-left",
        clock_offset_x=21, clock_offset_y=22,
        start_banner_duration=2.5,
        start_banner_scale=1.25,
        start_banner_bg_color=(9, 8, 7, 6),
        start_banner_text_color=(11, 22, 33, 44),
        start_banner_border_enabled=True,
        start_banner_border_color=(1, 1, 1, 1),
        start_banner_border_width=2,
    )
    win = gui.MainWindow()
    win._apply_style(style)
    assert win.current_style().to_dict() == style.to_dict()


def test_source_segments_keep_settings_keys(app):
    win = gui.MainWindow()
    win._set_source("text")
    assert win.source_seg.value() == "text"
    assert not win._source_is_id()
    assert win._collect_file_settings()["source"] == "text"
    win._set_source("id")
    assert win._source_is_id()
    assert win._collect_file_settings()["source"] == "id"
