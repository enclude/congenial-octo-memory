"""Testy domenowej kompozycji podglądu (preview) — syntetyczna klatka, bez FFmpeg."""

from __future__ import annotations

from PIL import Image

from piro_overlay import preview
from piro_overlay.models import OverlayStyle, Session, Shot

_BG = (10, 60, 10, 255)


def _frame(size=(640, 360)) -> Image.Image:
    return Image.new("RGBA", size, _BG)


def _session() -> Session:
    return Session(shots=[Shot(1, 1.0), Shot(2, 2.5, 1.5)])


def _differs(img: Image.Image) -> bool:
    """Czy obraz różni się gdziekolwiek od jednolitego tła."""
    return img.getextrema() != tuple((c, c) for c in _BG)


def test_no_session_returns_plain_copy():
    frame = _frame()
    out = preview.compose_preview(frame, None, 5.0, 2.0, OverlayStyle(), 60.0)
    assert out is not frame
    assert not _differs(out)


def test_panel_visible_in_shot_window():
    # t0=2, strzał 1 o czasie 1.0 → panel widoczny od t=3.0
    out = preview.compose_preview(_frame(), _session(), 3.2, 2.0, OverlayStyle(), 60.0)
    assert _differs(out)


def test_nothing_before_t0_and_banner():
    # Przed T0 (i przed planszą START) nakładki nie ma.
    out = preview.compose_preview(_frame(), _session(), 0.5, 2.0, OverlayStyle(), 60.0)
    assert not _differs(out)


def test_summary_after_last_shot_hold():
    # Długo po ostatnim strzale → panel podsumowania (do końca filmu).
    out = preview.compose_preview(_frame(), _session(), 30.0, 2.0, OverlayStyle(), 60.0)
    assert _differs(out)


def test_clock_frozen_after_last_shot_matches_last_shot_frame():
    style = OverlayStyle(show_running_clock=True)
    session = _session()
    # Zegar po ostatnim strzale = zegar dokładnie na ostatnim strzale (zamrożenie),
    # porównujemy sam pasek zegara (górna część klatki, poza panelami podsumowania).
    at_last = preview.compose_preview(_frame(), session, 2.0 + 2.5, 2.0, style, 60.0)
    later = preview.compose_preview(_frame(), session, 2.0 + 2.5 + 0.05, 2.0, style, 60.0)
    assert at_last.tobytes() == later.tobytes()


def test_scaled_style_scales_offsets():
    style = OverlayStyle(offset_x=100, offset_y=50, clock_offset_x=64, clock_offset_y=32)
    scaled = preview.scaled_style(style, video_h=1080, frame_h=540)
    assert (scaled.offset_x, scaled.offset_y) == (50, 25)
    assert (scaled.clock_offset_x, scaled.clock_offset_y) == (32, 16)


def test_scaled_style_identity_when_same_height():
    style = OverlayStyle(offset_x=100)
    assert preview.scaled_style(style, 540, 540) is style
