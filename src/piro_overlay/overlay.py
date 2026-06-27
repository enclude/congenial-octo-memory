"""Render paneli nakładki jako obrazy RGBA (Pillow).

Każda funkcja zwraca `PIL.Image.Image` (RGBA) o rozmiarze samego panelu — render.py
nakłada go na klatkę wideo w pozycji wynikającej z `OverlayStyle`. Rozmiary czcionek
skalują się względem wysokości wideo (`video_size[1]`) i `style.scale`, dzięki czemu
nakładka wygląda spójnie niezależnie od rozdzielczości.

Renderowanie jest deterministyczne (te same wejścia → identyczny PNG), co umożliwia
testy snapshotowe.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from PIL import Image, ImageDraw, ImageFont

from .i18n import get_translator
from .models import OverlayStyle, Session
from .resources import font_path

_PAD = 0.6          # padding wewn. panelu jako wielokrotność rozmiaru bazowego fontu
_LINE_GAP = 0.28    # odstęp między liniami jako wielokrotność wysokości linii


@dataclass
class _Line:
    text: str
    font: ImageFont.FreeTypeFont
    color: tuple[int, int, int, int]


def _base_font_size(video_height: int, style: OverlayStyle) -> int:
    return max(12, int(video_height * 0.038 * style.scale))


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(font_path(bold=bold), size)


def _fmt_time(value: float) -> str:
    return f"{value:.2f}s"


def _fmt_split(value: float | None) -> str:
    return "—" if value is None else f"+{value:.2f}s"


def _text_size(font: ImageFont.FreeTypeFont, text: str) -> tuple[int, int]:
    box = font.getbbox(text)
    return box[2] - box[0], box[3] - box[1]


def _render_panel(lines: list[_Line], style: OverlayStyle, base: int) -> Image.Image:
    """Składa panel z listy linii: tło z zaokrąglonymi rogami + obramowanie + tekst."""
    pad = int(base * _PAD)
    gap = int(base * _LINE_GAP)

    sizes = [_text_size(ln.font, ln.text) for ln in lines]
    content_w = max((w for w, _ in sizes), default=0)
    content_h = sum(h for _, h in sizes) + gap * (len(lines) - 1 if lines else 0)

    panel_w = content_w + 2 * pad
    panel_h = content_h + 2 * pad

    img = Image.new("RGBA", (panel_w, panel_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    radius = max(0, int(style.corner_radius * style.scale))
    draw.rounded_rectangle(
        [(0, 0), (panel_w - 1, panel_h - 1)],
        radius=radius,
        fill=style.bg_color,
        outline=style.border_color if style.border_enabled else None,
        width=max(1, int(style.border_width * style.scale)) if style.border_enabled else 1,
    )

    y = pad
    for ln, (_, h) in zip(lines, sizes):
        draw.text((pad, y), ln.text, font=ln.font, fill=ln.color)
        y += h + gap
    return img


def render_shot_panel(session: Session, idx: int, style: OverlayStyle,
                      video_size: tuple[int, int]) -> Image.Image:
    """Panel dla strzału o indeksie `idx` (0-based) z listy `session.shots`."""
    tr = get_translator(style.lang)
    shot = session.shots[idx]
    base = _base_font_size(video_size[1], style)

    f_head = _font(int(base * 0.7))
    f_big = _font(int(base * 1.4), bold=True)
    f_body = _font(base)

    lines: list[_Line] = []
    if session.nazwa_toru:
        lines.append(_Line(session.nazwa_toru, f_head, style.text_color))
    if session.uczestnik:
        lines.append(_Line(session.uczestnik, f_head, style.text_color))

    counter = f"{tr('shot')} {shot.numer} {tr('of')} {session.total_shots}"
    lines.append(_Line(counter, f_big, style.accent_color))
    lines.append(_Line(_fmt_time(shot.czas), f_body, style.text_color))
    lines.append(_Line(f"{tr('split')}: {_fmt_split(shot.split)}", f_body, style.text_color))

    return _render_panel(lines, style, base)


def render_summary_panel(session: Session, style: OverlayStyle,
                         video_size: tuple[int, int]) -> Image.Image:
    """Panel podsumowania: czas bazowy, suma kar, czas końcowy, hit factor."""
    tr = get_translator(style.lang)
    base = _base_font_size(video_size[1], style)

    f_head = _font(int(base * 1.1), bold=True)
    f_body = _font(base)

    lines: list[_Line] = [_Line(tr("summary"), f_head, style.accent_color)]

    base_time = session.base_time
    if base_time is not None:
        lines.append(_Line(f"{tr('base_time')}: {_fmt_time(base_time)}", f_body, style.text_color))
    if session.suma_kar is not None:
        lines.append(_Line(f"{tr('penalties')}: {_fmt_time(session.suma_kar)}", f_body, style.text_color))
    if session.czas_koncowy is not None:
        lines.append(_Line(f"{tr('final_time')}: {_fmt_time(session.czas_koncowy)}",
                           f_body, style.accent_color))
    # Hit Factor pomijamy, gdy 0 (zwykle = brak punktów / niepoliczony) lub brak.
    if session.hit_factor:
        lines.append(_Line(f"{tr('hit_factor')}: {session.hit_factor:.4f}",
                           f_body, style.text_color))

    return _render_panel(lines, style, base)


def clock_text(elapsed: float) -> str:
    """Etykieta płynącego zegara od T0 — sekundy z jedną cyfrą po przecinku."""
    return f"T+{max(0.0, elapsed):.1f}s"


def render_clock_panel(style: OverlayStyle, video_size: tuple[int, int],
                       elapsed: float) -> Image.Image:
    """Panel płynącego zegara „T+x.xs" (do podglądu; w renderze używamy drawtext)."""
    base = _base_font_size(video_size[1], style)
    f_clock = _font(int(base * 1.2), bold=True)
    return _render_panel([_Line(clock_text(elapsed), f_clock, style.accent_color)], style, base)


def render_start_banner(style: OverlayStyle, video_size: tuple[int, int]) -> Image.Image:
    """Duża plansza „START" (wyśrodkowywana przez render.py)."""
    tr = get_translator(style.lang)
    banner_style = replace(
        style,
        scale=style.scale * style.start_banner_scale,
        bg_color=style.start_banner_bg_color,
        border_enabled=style.start_banner_border_enabled,
        border_color=style.start_banner_border_color,
        border_width=style.start_banner_border_width,
    )
    base = _base_font_size(video_size[1], banner_style)
    f_start = _font(int(base * 3.0), bold=True)
    return _render_panel([_Line(tr("start"), f_start, style.start_banner_text_color)], banner_style, base)


def panel_origin(panel_size: tuple[int, int], video_size: tuple[int, int],
                 style: OverlayStyle) -> tuple[int, int]:
    """Oblicza lewy-górny róg panelu na klatce wg pozycji i offsetu ze stylu."""
    pw, ph = panel_size
    vw, vh = video_size
    ox, oy = style.offset_x, style.offset_y

    vert, _, horiz = style.position.partition("-")
    if horiz == "left":
        x = ox
    elif horiz == "right":
        x = vw - pw - ox
    else:  # center
        x = (vw - pw) // 2

    if vert == "top":
        y = oy
    else:  # bottom
        y = vh - ph - oy
    return x, y
