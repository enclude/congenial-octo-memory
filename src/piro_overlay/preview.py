"""Kompozycja podglądu klatki z nakładką — domena (Pillow, bez Qt).

Odtwarza to, co robi scrubber w GUI (`gui._on_scrubber_frame_ready` +
`gui._composite_clock`), ale jako czysta funkcja: klatka + sesja + czas →
klatka z panelem aktywnym dla t i (opcjonalnie) zamrożonym zegarem. Dzięki
temu backend WWW pokazuje dokładnie to, co wyrenderuje `render.render_video`.
"""

from __future__ import annotations

from dataclasses import replace

from PIL import Image

from . import overlay, render
from .models import OverlayStyle, Session


def scaled_style(style: OverlayStyle, video_h: int, frame_h: int) -> OverlayStyle:
    """Kopia stylu z offsetami przeskalowanymi do rozdzielczości podglądu.

    Offsety w stylu są w pikselach WYJŚCIA; podgląd bywa pomniejszony
    (`extract_frame(..., scale_height=...)`), więc skalujemy je o
    frame_h/video_h — podgląd ≈ render (WYSIWYG), jak `gui._scaled_style`.
    """
    if video_h <= 0 or frame_h == video_h:
        return style
    s = frame_h / video_h
    return replace(
        style,
        offset_x=int(round(style.offset_x * s)),
        offset_y=int(round(style.offset_y * s)),
        clock_offset_x=int(round(style.clock_offset_x * s)),
        clock_offset_y=int(round(style.clock_offset_y * s)),
        meta_offset_x=int(round(style.meta_offset_x * s)),
        meta_offset_y=int(round(style.meta_offset_y * s)),
    )


def _composite_clock(frame: Image.Image, style: OverlayStyle,
                     session: Session, elapsed: float) -> None:
    """Nakłada panel zegara — pozycja i STAŁY rozmiar jak w renderze."""
    max_elapsed = session.shots[-1].czas if session.shots else elapsed
    clock_fixed = overlay.clock_panel_max_size(style, frame.size, max_elapsed)
    clock = overlay.render_clock_panel(style, frame.size, elapsed, clock_fixed)
    if style.clock_position == "auto":
        shot_fixed = overlay.shot_panel_max_size(session, style, frame.size)
        gap = render._clock_gap(frame.size, style)
        xy = render._clock_xy(style, frame.size, clock.size, shot_fixed[1], gap)
    else:
        xy = render._clock_xy(style, frame.size, clock.size, 0, 0)
    frame.alpha_composite(clock, xy)


def compose_preview(frame: Image.Image, session: Session | None, t: float,
                    t0: float, style: OverlayStyle, duration: float,
                    video_h: int | None = None) -> Image.Image:
    """Klatka `frame` (czas `t` osi wideo) z nakładką aktywną dla tego czasu.

    `video_h` — wysokość ORYGINALNEGO wideo; gdy podana i różna od wysokości
    klatki, offsety stylu są skalowane (WYSIWYG). Zegar liczy czas od T0
    i zamarza na ostatnim strzale — tak samo jak w renderze.
    """
    composite = frame.convert("RGBA")
    if composite is frame:
        composite = frame.copy()
    if session is None or not session.shots:
        return composite
    pstyle = scaled_style(style, video_h or frame.size[1], frame.size[1])
    events = render.build_events(session, t0, pstyle, composite.size, duration)
    # Bez `break` — nakładka metadanych gra RÓWNOLEGLE z panelem strzału
    # (dwa aktywne zdarzenia naraz), jak w łańcuchu overlay w renderze.
    for ev in events:
        if ev.start <= t < ev.end:
            panel = ev.image
            if ev.xy is not None:
                x, y = ev.xy
            elif ev.centered:
                x = (composite.size[0] - panel.size[0]) // 2
                y = (composite.size[1] - panel.size[1]) // 2
            else:
                x, y = overlay.panel_origin(panel.size, composite.size, pstyle)
            composite.alpha_composite(panel, (x, y))
    if pstyle.show_running_clock and t >= t0 - 1e-6:
        # Render zamraża zegar na ostatnim strzale — podgląd tak samo.
        elapsed = min(t - t0, session.shots[-1].czas)
        _composite_clock(composite, pstyle, session, elapsed)
    return composite
