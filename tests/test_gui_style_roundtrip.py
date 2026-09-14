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


def test_meta_override_applies_to_session_and_settings(app):
    from piro_overlay.models import Session, Shot

    win = gui.MainWindow()
    api_session = Session(shots=[Shot(1, 1.0), Shot(2, 2.0, 1.0)],
                          nazwa_toru="Z API", uczestnik="Ktoś")
    win._on_session_fetched(api_session)
    # Puste pola → sesja z API bez zmian, placeholdery pokazują wartości API.
    assert (win.session.nazwa_toru, win.session.uczestnik) == ("Z API", "Ktoś")
    assert win.meta_track_edit.placeholderText() == "Z API"

    win.meta_track_edit.setText("Tor 3")
    win.meta_participant_edit.setText("  Jaro ")
    assert (win.session.nazwa_toru, win.session.uczestnik) == ("Tor 3", "Jaro")
    assert win._api_session is api_session  # surowa kopia nietknięta

    # Źródło „Tekst” buduje sesję z pól + nadpisania (metadane trafiają na film).
    win._set_source("text")
    win.timeline_edit.setPlainText("1: 1.0s | 2: 2.5s")
    built = win._build_session()
    assert [s.czas for s in built.shots] == [1.0, 2.5]
    assert (built.nazwa_toru, built.uczestnik) == ("Tor 3", "Jaro")

    settings = win._collect_file_settings()
    assert settings["meta_track"] == "Tor 3"
    assert settings["meta_participant"] == "  Jaro "
    assert "--track-name" in win._build_cli_command()

    # Wyczyszczenie pola przywraca wartość z API.
    win.meta_track_edit.clear()
    assert win.session.nazwa_toru == "Z API"
