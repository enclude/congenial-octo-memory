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


def _panel_size(lines: list[_Line], style: OverlayStyle, base: int) -> tuple[int, int]:
    """Rozmiar panelu (px) dla danych linii — bez rysowania (do liczenia max rozmiaru)."""
    pad = int(base * _PAD)
    gap = int(base * _LINE_GAP)
    sizes = [_text_size(ln.font, ln.text) for ln in lines]
    content_w = max((w for w, _ in sizes), default=0)
    content_h = sum(h for _, h in sizes) + gap * (len(lines) - 1 if lines else 0)
    return content_w + 2 * pad, content_h + 2 * pad


def _render_panel(lines: list[_Line], style: OverlayStyle, base: int,
                  fixed_size: tuple[int, int] | None = None) -> Image.Image:
    """Składa panel z listy linii: tło z zaokrąglonymi rogami + obramowanie + tekst.

    `fixed_size` — wymuszony minimalny rozmiar panelu (px). Gdy podany, tło i
    obramowanie mają stały rozmiar (max, jaki panel kiedykolwiek przyjmie), więc
    nie „pulsują" przy zmianie długości tekstu (np. „Strzał 6 z 18" vs „18 z 18").
    """
    pad = int(base * _PAD)
    gap = int(base * _LINE_GAP)

    sizes = [_text_size(ln.font, ln.text) for ln in lines]
    content_w = max((w for w, _ in sizes), default=0)
    content_h = sum(h for _, h in sizes) + gap * (len(lines) - 1 if lines else 0)

    panel_w = content_w + 2 * pad
    panel_h = content_h + 2 * pad
    if fixed_size is not None:
        panel_w = max(panel_w, fixed_size[0])
        panel_h = max(panel_h, fixed_size[1])

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


def _shot_lines(session: Session, idx: int, style: OverlayStyle, base: int) -> list[_Line]:
    """Linie panelu strzału (panel z informacjami o strzale)."""
    tr = get_translator(style.lang)
    shot = session.shots[idx]

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
    return lines


def render_shot_panel(session: Session, idx: int, style: OverlayStyle,
                      video_size: tuple[int, int],
                      fixed_size: tuple[int, int] | None = None) -> Image.Image:
    """Panel dla strzału o indeksie `idx` (0-based) z listy `session.shots`.

    `fixed_size` — wymuszony rozmiar tła/obramowania (zwykle `shot_panel_max_size`),
    by panel nie zmieniał szerokości/wysokości między kolejnymi strzałami.
    Przy `style.panel_mode == "list"` zwraca panel-listę ostatnich strzałów
    (rozmiar stały z konstrukcji — `fixed_size` jest wtedy ignorowany); dispatch
    tutaj sprawia, że render/preview/gui nie muszą znać trybu panelu."""
    if style.panel_mode == "list":
        return render_shot_list_panel(session, idx, style, video_size)
    base = _base_font_size(video_size[1], style)
    return _render_panel(_shot_lines(session, idx, style, base), style, base, fixed_size)


def shot_panel_max_size(session: Session, style: OverlayStyle,
                        video_size: tuple[int, int]) -> tuple[int, int]:
    """Maksymalny rozmiar panelu strzału po WSZYSTKICH strzałach sesji (px).

    Render.py renderuje każdy panel strzału z tym rozmiarem → stałe tło/obramowanie."""
    base = _base_font_size(video_size[1], style)
    if style.panel_mode == "list":
        return _list_metrics(session, style, base).panel_size
    w = h = 0
    for idx in range(len(session.shots)):
        pw, ph = _panel_size(_shot_lines(session, idx, style, base), style, base)
        w, h = max(w, pw), max(h, ph)
    return w, h


# --- Panel „lista strzałów" (panel_mode="list") ---------------------------------
# Pigułki per wiersz: numer | czas | split; najnowszy strzał na dole (większy,
# pełna nieprzezroczystość), starsze przesunięte wyżej i stopniowo wygaszane.
# Rozmiar panelu jest STAŁY z konstrukcji: wysokość = `list_max_rows` slotów
# (wiersze dosunięte do dołu, puste sloty przezroczyste — najnowszy strzał zawsze
# w tym samym miejscu ekranu), szerokości kolumn liczone po WSZYSTKICH strzałach.

_LIST_PAD_X = 0.55   # padding poziomy pigułki (× base)
_LIST_PAD_Y = 0.32   # padding pionowy pigułki (× base)
_LIST_ROW_GAP = 0.22  # odstęp między pigułkami (× base)
_LIST_COL_GAP = 0.55  # odstęp między kolumnami (× base)
_LIST_ALPHA_NEW = 235          # bazowa alfa najnowszego wiersza
_LIST_ALPHA_OLD = (155, 120, 90, 90)  # alfa starszych wg wieku (age-1)


@dataclass
class _ListMetrics:
    f_num: ImageFont.FreeTypeFont
    f_time: ImageFont.FreeTypeFont
    f_split: ImageFont.FreeTypeFont
    f_num_new: ImageFont.FreeTypeFont
    f_time_new: ImageFont.FreeTypeFont
    f_split_new: ImageFont.FreeTypeFont
    pad_x: int
    pad_y: int
    row_gap: int
    col_gap: int
    w_num: int
    w_time: int
    w_split: int
    row_h_old: int
    row_h_new: int
    panel_size: tuple[int, int]


def _list_num_label(session: Session, shot_numer: int, style: OverlayStyle,
                    newest: bool) -> str:
    if newest and style.list_show_progress:
        return f"{shot_numer}/{session.total_shots}"
    return str(shot_numer)


def _list_fmt_time(value: float) -> str:
    return f"{value:.2f}"


def _list_fmt_split(value: float | None) -> str:
    return "—" if value is None else f"+{value:.2f}"


def _list_metrics(session: Session, style: OverlayStyle, base: int) -> _ListMetrics:
    f_num = _font(int(base * 0.85), bold=True)
    f_time = _font(base)
    f_split = _font(base, bold=True)
    f_num_new = _font(base, bold=True)
    f_time_new = _font(int(base * 1.25), bold=True)
    f_split_new = _font(int(base * 1.25), bold=True)

    pad_x = int(base * _LIST_PAD_X)
    pad_y = int(base * _LIST_PAD_Y)
    row_gap = int(base * _LIST_ROW_GAP)
    col_gap = int(base * _LIST_COL_GAP)

    shots = session.shots
    w_num = max((_text_size(f_num_new, _list_num_label(session, s.numer, style, True))[0]
                 for s in shots), default=0)
    w_time = max((_text_size(f_time_new, _list_fmt_time(s.czas))[0] for s in shots),
                 default=0)
    w_split = max((_text_size(f_split_new, _list_fmt_split(s.split))[0] for s in shots),
                  default=0)

    # Wysokość wiersza z cyfr (bez dolnych wydłużeń) — stała dla wszystkich wierszy.
    row_h_old = _text_size(f_time, "0.00")[1] + 2 * pad_y
    row_h_new = _text_size(f_time_new, "0.00")[1] + 2 * pad_y
    rows = max(1, style.list_max_rows)
    panel_w = 2 * pad_x + w_num + col_gap + w_time + col_gap + w_split
    panel_h = (rows - 1) * (row_h_old + row_gap) + row_h_new

    return _ListMetrics(f_num, f_time, f_split, f_num_new, f_time_new, f_split_new,
                        pad_x, pad_y, row_gap, col_gap, w_num, w_time, w_split,
                        row_h_old, row_h_new, (panel_w, panel_h))


def _list_row_alpha(newest: bool, age: int) -> int:
    if newest:
        return _LIST_ALPHA_NEW
    return _LIST_ALPHA_OLD[min(age - 1, len(_LIST_ALPHA_OLD) - 1)]


def render_shot_list_panel(session: Session, idx: int, style: OverlayStyle,
                           video_size: tuple[int, int]) -> Image.Image:
    """Panel-lista: ostatnie ≤`list_max_rows` strzałów do `idx` włącznie."""
    base = _base_font_size(video_size[1], style)
    m = _list_metrics(session, style, base)
    panel_w, panel_h = m.panel_size

    lo = max(0, idx - (max(1, style.list_max_rows) - 1))
    rows = session.shots[lo:idx + 1]
    n = len(rows)

    img = Image.new("RGBA", (panel_w, panel_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    bg, text, accent = style.bg_color, style.text_color, style.accent_color
    y = panel_h
    for k in range(n - 1, -1, -1):
        shot = rows[k]
        newest = (k == n - 1)
        alpha = _list_row_alpha(newest, (n - 1) - k)
        rh = m.row_h_new if newest else m.row_h_old
        y -= rh
        fn, ft, fs = ((m.f_num_new, m.f_time_new, m.f_split_new) if newest
                      else (m.f_num, m.f_time, m.f_split))

        draw.rounded_rectangle(
            [(0, y), (panel_w - 1, y + rh - 1)],
            radius=int(rh * 0.28),
            fill=(*bg[:3], int(bg[3] * alpha / _LIST_ALPHA_NEW)),
        )
        # Kotwica "lm" = pionowy środek metryk fontu → kolumny o różnych rozmiarach
        # fontu (numer 0.85× vs czas 1.0×) siedzą na wspólnej osi wiersza.
        ty = y + rh // 2
        num_alpha = alpha if newest else int(alpha * 0.6)
        draw.text((m.pad_x, ty), _list_num_label(session, shot.numer, style, newest),
                  font=fn, fill=(*text[:3], int(text[3] * num_alpha / 255)), anchor="lm")
        x = m.pad_x + m.w_num + m.col_gap
        draw.text((x, ty), _list_fmt_time(shot.czas), font=ft,
                  fill=(*text[:3], int(text[3] * alpha / 255)), anchor="lm")
        x += m.w_time + m.col_gap
        draw.text((x, ty), _list_fmt_split(shot.split), font=fs,
                  fill=(*accent[:3], int(accent[3] * alpha / 255)), anchor="lm")
        y -= m.row_gap
    return img


def render_meta_panel(session: Session, style: OverlayStyle,
                      video_size: tuple[int, int]) -> Image.Image | None:
    """Nakładka metadanych (jedno tło): nazwa toru + „uczestnik — x strzałów".

    Zwraca None, gdy sesja nie ma żadnych metadanych do pokazania."""
    tr = get_translator(style.lang)
    base = _base_font_size(video_size[1], style)
    f_top = _font(base, bold=True)
    f_bot = _font(int(base * 0.85))

    lines: list[_Line] = []
    if session.nazwa_toru:
        lines.append(_Line(session.nazwa_toru, f_top, style.accent_color))
    if session.uczestnik:
        lines.append(_Line(f"{session.uczestnik} — {session.total_shots} "
                           f"{tr('shots_label')}", f_bot, style.text_color))
    if not lines:
        return None

    pad_x = int(base * _LIST_PAD_X)
    pad_y = int(base * _LIST_PAD_Y)
    line_gap = int(base * _LINE_GAP)

    # Wysokość linii z "Ag" (stała, niezależna od treści) — panel nie zmienia
    # wysokości między sesjami o różnych znakach diakrytycznych.
    heights = [_text_size(ln.font, "Ag")[1] for ln in lines]
    panel_w = max(_text_size(ln.font, ln.text)[0] for ln in lines) + 2 * pad_x
    panel_h = 2 * pad_y + sum(heights) + line_gap * (len(lines) - 1)

    img = Image.new("RGBA", (panel_w, panel_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([(0, 0), (panel_w - 1, panel_h - 1)],
                           radius=int(panel_h * 0.18), fill=style.bg_color)
    y = pad_y
    for ln, h in zip(lines, heights):
        draw.text((pad_x, y + h // 2), ln.text, font=ln.font, fill=ln.color, anchor="lm")
        y += h + line_gap
    return img


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
                       elapsed: float,
                       fixed_size: tuple[int, int] | None = None) -> Image.Image:
    """Panel płynącego zegara „T+x.xs". `fixed_size` (zwykle `clock_panel_max_size`)
    daje stałe tło/obramowanie, by dolna/prawa krawędź nie skakały przy zmianie cyfr."""
    base = _base_font_size(video_size[1], style)
    f_clock = _font(int(base * 1.2), bold=True)
    return _render_panel([_Line(clock_text(elapsed), f_clock, style.accent_color)],
                         style, base, fixed_size)


def clock_panel_max_size(style: OverlayStyle, video_size: tuple[int, int],
                         max_elapsed: float) -> tuple[int, int]:
    """Maksymalny rozmiar panelu zegara (przy największym `max_elapsed` = najwięcej cyfr)."""
    base = _base_font_size(video_size[1], style)
    f_clock = _font(int(base * 1.2), bold=True)
    return _panel_size([_Line(clock_text(max_elapsed), f_clock, style.accent_color)], style, base)


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
    return panel_origin_at(panel_size, video_size, style.position,
                           style.offset_x, style.offset_y)


def panel_origin_at(panel_size: tuple[int, int], video_size: tuple[int, int],
                    position: str, offset_x: int, offset_y: int) -> tuple[int, int]:
    """Jak `panel_origin`, ale dla dowolnej pozycji/offsetu (np. nakładka metadanych)."""
    pw, ph = panel_size
    vw, vh = video_size
    ox, oy = offset_x, offset_y

    vert, _, horiz = position.partition("-")
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
