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
