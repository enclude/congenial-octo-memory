"""Testy zapisu/odczytu konfiguracji w AppData (styl, katalogi, per-plik, kolejka)."""

from __future__ import annotations

import importlib

import pytest

from piro_overlay import config
from piro_overlay.models import OverlayStyle


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """Izoluje katalog konfiguracji w tmp (osobno dla Windows/Unix)."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return importlib.reload(config)


def test_file_settings_roundtrip(cfg):
    data = {"t0": 3.25, "trim_start": 1.0, "trim_end": 60.0, "style": {"scale": 1.5}}
    cfg.save_file_settings("/some/dir/clip.mp4", data)
    assert cfg.load_file_settings("/some/dir/clip.mp4") == data


def test_file_settings_missing_returns_none(cfg):
    assert cfg.load_file_settings("/never/seen.mp4") is None


def test_file_settings_keyed_per_file(cfg):
    cfg.save_file_settings("/a.mp4", {"t0": 1.0})
    cfg.save_file_settings("/b.mp4", {"t0": 2.0})
    assert cfg.load_file_settings("/a.mp4") == {"t0": 1.0}
    assert cfg.load_file_settings("/b.mp4") == {"t0": 2.0}


def test_file_settings_overwrite(cfg):
    cfg.save_file_settings("/a.mp4", {"t0": 1.0})
    cfg.save_file_settings("/a.mp4", {"t0": 9.0})
    assert cfg.load_file_settings("/a.mp4") == {"t0": 9.0}


def test_file_settings_cap_drops_oldest(cfg, monkeypatch):
    monkeypatch.setattr(cfg, "_MAX_FILE_ENTRIES", 3)
    for i in range(5):
        cfg.save_file_settings(f"/clip{i}.mp4", {"i": i})
    # Najstarsze (0, 1) usunięte; ostatnie trzy zostają.
    assert cfg.load_file_settings("/clip0.mp4") is None
    assert cfg.load_file_settings("/clip1.mp4") is None
    assert cfg.load_file_settings("/clip4.mp4") == {"i": 4}


def test_file_settings_corrupt_store_is_safe(cfg):
    cfg._file_settings_path().write_text("{not json", encoding="utf-8")
    assert cfg.load_file_settings("/a.mp4") is None
    # Zapis nadpisuje uszkodzony plik bez wyjątku.
    cfg.save_file_settings("/a.mp4", {"t0": 1.0})
    assert cfg.load_file_settings("/a.mp4") == {"t0": 1.0}


# --- ostatni styl nakładki ---
def test_last_style_roundtrip(cfg):
    style = OverlayStyle(scale=1.7, position="top-right", offset_x=64)
    cfg.save_last_style(style)
    loaded = cfg.load_last_style()
    assert loaded == style


def test_last_style_missing_returns_none(cfg):
    assert cfg.load_last_style() is None


def test_last_style_corrupt_returns_none(cfg):
    cfg.last_style_path().write_text("{not json", encoding="utf-8")
    assert cfg.load_last_style() is None


# --- ostatnio używane katalogi ---
def test_last_dir_roundtrip(cfg, tmp_path):
    cfg.save_last_dir("video", tmp_path)
    assert cfg.load_last_dir("video") == str(tmp_path)


def test_last_dir_missing_key_returns_none(cfg):
    assert cfg.load_last_dir("nigdy") is None


def test_last_dir_nonexistent_dir_returns_none(cfg, tmp_path):
    cfg.save_last_dir("output", tmp_path / "usunięty")
    assert cfg.load_last_dir("output") is None


# --- kolejka renderów ---
def test_queue_roundtrip(cfg):
    payload = {"version": 1, "jobs": [{"id": "abc", "label": "x", "kwargs": {}}]}
    cfg.save_queue(payload)
    assert cfg.load_queue() == payload


def test_queue_missing_returns_none(cfg):
    assert cfg.load_queue() is None


def test_queue_corrupt_returns_none(cfg):
    cfg.queue_path().write_text("[1, 2", encoding="utf-8")
    assert cfg.load_queue() is None
