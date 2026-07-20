"""Testy snapshotowe/regresyjne renderu paneli nakładki.

Renderowanie panelu z bundlowanym fontem DejaVu jest deterministyczne, więc:
- weryfikujemy determinizm (te same wejścia → identyczny PNG),
- porównujemy z zapisanym snapshotem (z tolerancją na drobne różnice wersji Pillow),
- sprawdzamy, że zmiana stylu zmienia wynik.

Aby (prze)generować snapshoty: PIRO_UPDATE_SNAPSHOTS=1 pytest tests/test_overlay.py
"""

import io
import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from piro_overlay import overlay
from piro_overlay.models import Lang, OverlayStyle, Session
from piro_overlay.parser import parse_timeline

SNAP_DIR = Path(__file__).parent / "snapshots"
VIDEO_SIZE = (1920, 1080)
MAX_MEAN_DIFF = 2.0  # tolerancja (0–255) na różnice między wersjami Pillow


@pytest.fixture
def session() -> Session:
    shots = parse_timeline("1: 2.81s | 2: 4.63s (+1.82s) | 3: 6.28s (+1.65s)")
    return Session(
        shots=shots, nazwa_toru="Tor 1", uczestnik="Jan Kowalski",
        liczba_strzalow=3, czas_bazowy=6.28, suma_kar=4.0,
        czas_koncowy=10.28, hit_factor=3.0599,
    )


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _assert_snapshot(img: Image.Image, name: str) -> None:
    SNAP_DIR.mkdir(exist_ok=True)
    ref_path = SNAP_DIR / f"{name}.png"
    if os.environ.get("PIRO_UPDATE_SNAPSHOTS") or not ref_path.exists():
        img.save(ref_path)
        pytest.skip(f"Snapshot {name} zapisany/odświeżony.")
    ref = Image.open(ref_path).convert("RGBA")
    assert img.size == ref.size, f"{name}: rozmiar {img.size} != {ref.size}"
    diff = np.abs(np.asarray(img, float) - np.asarray(ref, float))
    assert diff.mean() < MAX_MEAN_DIFF, f"{name}: średnia różnica {diff.mean():.3f}"


def test_shot_panel_is_deterministic(session):
    style = OverlayStyle()
    a = overlay.render_shot_panel(session, 1, style, VIDEO_SIZE)
    b = overlay.render_shot_panel(session, 1, style, VIDEO_SIZE)
    assert _png_bytes(a) == _png_bytes(b)
    assert a.mode == "RGBA" and a.size[0] > 0 and a.size[1] > 0


def test_shot_panel_snapshot(session):
    img = overlay.render_shot_panel(session, 1, OverlayStyle(), VIDEO_SIZE)
    _assert_snapshot(img, "shot_panel_pl")


def test_summary_panel_snapshot(session):
    img = overlay.render_summary_panel(session, OverlayStyle(), VIDEO_SIZE)
    _assert_snapshot(img, "summary_panel_pl")


def test_start_banner_snapshot():
    img = overlay.render_start_banner(OverlayStyle(), VIDEO_SIZE)
    _assert_snapshot(img, "start_banner_pl")


def test_language_changes_output(session):
    pl = overlay.render_shot_panel(session, 1, OverlayStyle(lang=Lang.PL), VIDEO_SIZE)
    en = overlay.render_shot_panel(session, 1, OverlayStyle(lang=Lang.EN), VIDEO_SIZE)
    assert _png_bytes(pl) != _png_bytes(en)  # "Strzał" vs "Shot"


def test_hit_factor_zero_hidden(session):
    import dataclasses
    with_hf = overlay.render_summary_panel(session, OverlayStyle(), VIDEO_SIZE)
    zero_hf = overlay.render_summary_panel(
        dataclasses.replace(session, hit_factor=0), OverlayStyle(), VIDEO_SIZE)
    none_hf = overlay.render_summary_panel(
        dataclasses.replace(session, hit_factor=None), OverlayStyle(), VIDEO_SIZE)
    # bez HF panel ma mniej linii -> jest niższy; HF=0 zachowuje się jak brak
    assert zero_hf.size[1] < with_hf.size[1]
    assert zero_hf.size == none_hf.size


def test_style_scale_changes_size(session):
    small = overlay.render_shot_panel(session, 1, OverlayStyle(scale=1.0), VIDEO_SIZE)
    big = overlay.render_shot_panel(session, 1, OverlayStyle(scale=2.0), VIDEO_SIZE)
    assert big.size[0] > small.size[0] and big.size[1] > small.size[1]


def test_shot_panel_fixed_size_uniform():
    # „Strzał 1 z 18" .. „18 z 18" + różne czasy → różna szerokość; fixed_size ujednolica.
    from piro_overlay.models import Shot
    shots = [Shot(i, round(0.7 * i, 2), (None if i == 1 else 0.7)) for i in range(1, 19)]
    sess = Session(shots=shots, nazwa_toru="Tor 1", uczestnik="Jan Kowalski",
                   liczba_strzalow=18)
    style = OverlayStyle()
    raw = {overlay.render_shot_panel(sess, i, style, VIDEO_SIZE).size for i in range(18)}
    assert len(raw) > 1                       # bez fixed_size rozmiary się różnią
    fixed = overlay.shot_panel_max_size(sess, style, VIDEO_SIZE)
    fx = {overlay.render_shot_panel(sess, i, style, VIDEO_SIZE, fixed).size for i in range(18)}
    assert fx == {fixed}                      # z fixed_size wszystkie identyczne (= max)


def test_clock_panel_fixed_size_uniform():
    style = OverlayStyle(show_running_clock=True)
    # max przy 99.9 s (najwięcej cyfr); wszystkie elapsed mieszczą się w stałym rozmiarze.
    fixed = overlay.clock_panel_max_size(style, VIDEO_SIZE, 99.9)
    sizes = {overlay.render_clock_panel(style, VIDEO_SIZE, e, fixed).size
             for e in (0.0, 9.9, 10.0, 99.9)}
    assert sizes == {fixed}


# --- panel „lista strzałów" (panel_mode="list") ---

@pytest.fixture
def long_session() -> Session:
    from piro_overlay.models import Shot
    shots = [Shot(i, round(0.73 * i + 10, 2), (None if i == 1 else 0.73))
             for i in range(1, 10)]
    return Session(shots=shots, nazwa_toru="Tor 3+4", uczestnik="Jaro",
                   liczba_strzalow=9)


def test_list_panel_dispatch_and_constant_size(long_session):
    # render_shot_panel z panel_mode="list" ma STAŁY rozmiar dla każdego strzału
    # (fixed_size niepotrzebny) i zgadza się z shot_panel_max_size.
    style = OverlayStyle(panel_mode="list")
    sizes = {overlay.render_shot_panel(long_session, i, style, VIDEO_SIZE).size
             for i in range(len(long_session.shots))}
    assert sizes == {overlay.shot_panel_max_size(long_session, style, VIDEO_SIZE)}


def test_list_panel_content_changes_between_shots(long_session):
    style = OverlayStyle(panel_mode="list")
    a = overlay.render_shot_panel(long_session, 3, style, VIDEO_SIZE)
    b = overlay.render_shot_panel(long_session, 4, style, VIDEO_SIZE)
    assert _png_bytes(a) != _png_bytes(b)


def test_list_panel_snapshot(long_session):
    img = overlay.render_shot_panel(long_session, 5, OverlayStyle(panel_mode="list"),
                                    VIDEO_SIZE)
    _assert_snapshot(img, "shot_list_panel_pl")


def test_list_panel_progress_label(long_session):
    with_p = overlay.render_shot_panel(
        long_session, 5, OverlayStyle(panel_mode="list", list_show_progress=True),
        VIDEO_SIZE)
    without = overlay.render_shot_panel(
        long_session, 5, OverlayStyle(panel_mode="list", list_show_progress=False),
        VIDEO_SIZE)
    # „6/9" jest szersze niż „6" → kolumna numeru (i cały panel) szersza.
    assert with_p.size[0] > without.size[0]


def test_list_panel_max_rows_changes_height(long_session):
    s3 = OverlayStyle(panel_mode="list", list_max_rows=3)
    s5 = OverlayStyle(panel_mode="list", list_max_rows=5)
    h3 = overlay.render_shot_panel(long_session, 8, s3, VIDEO_SIZE).size[1]
    h5 = overlay.render_shot_panel(long_session, 8, s5, VIDEO_SIZE).size[1]
    assert h5 > h3


def test_classic_mode_unchanged_by_default(session):
    # Domyślny styl to "classic" — dispatch nie może zmienić dotychczasowego renderu.
    default = overlay.render_shot_panel(session, 1, OverlayStyle(), VIDEO_SIZE)
    classic = overlay.render_shot_panel(session, 1, OverlayStyle(panel_mode="classic"),
                                        VIDEO_SIZE)
    assert _png_bytes(default) == _png_bytes(classic)


# --- nakładka metadanych ---

def test_meta_panel_snapshot(session):
    img = overlay.render_meta_panel(session, OverlayStyle(), VIDEO_SIZE)
    assert img is not None
    _assert_snapshot(img, "meta_panel_pl")


def test_meta_panel_none_without_metadata():
    from piro_overlay.models import Shot
    bare = Session(shots=[Shot(1, 1.0)])
    assert overlay.render_meta_panel(bare, OverlayStyle(), VIDEO_SIZE) is None


def test_meta_panel_partial_metadata():
    from piro_overlay.models import Shot
    only_track = Session(shots=[Shot(1, 1.0)], nazwa_toru="Tor 1")
    only_user = Session(shots=[Shot(1, 1.0)], uczestnik="Jaro")
    both = Session(shots=[Shot(1, 1.0)], nazwa_toru="Tor 1", uczestnik="Jaro")
    t = overlay.render_meta_panel(only_track, OverlayStyle(), VIDEO_SIZE)
    u = overlay.render_meta_panel(only_user, OverlayStyle(), VIDEO_SIZE)
    b = overlay.render_meta_panel(both, OverlayStyle(), VIDEO_SIZE)
    assert t is not None and u is not None and b is not None
    assert b.size[1] > t.size[1]  # dwie linie wyższe niż jedna


def test_meta_panel_language(session):
    pl = overlay.render_meta_panel(session, OverlayStyle(lang=Lang.PL), VIDEO_SIZE)
    en = overlay.render_meta_panel(session, OverlayStyle(lang=Lang.EN), VIDEO_SIZE)
    assert _png_bytes(pl) != _png_bytes(en)  # "strzałów" vs "shots"
