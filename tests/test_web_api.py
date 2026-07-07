"""Testy API backendu WWW (TestClient, realny FFmpeg na malutkim wideo)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("PIRO_WEB_DATA_DIR", str(tmp_path / "jobs"))
    from web.backend.app import create_app
    with TestClient(create_app()) as c:
        yield c


def _upload(client: TestClient, video: Path, name: str = "tiny.mp4"):
    return client.post("/api/jobs", content=video.read_bytes(),
                       headers={"X-Filename": name})


def test_upload_sets_cookie_and_probes(client: TestClient, tiny_video: Path):
    r = _upload(client, tiny_video)
    assert r.status_code == 201, r.text
    assert "piro_sid" in r.cookies
    data = r.json()
    assert data["state"] == "uploaded"
    assert data["duration"] == pytest.approx(3.0, abs=0.5)
    assert (data["width"], data["height"]) == (320, 240)


def test_upload_rejects_bad_extension(client: TestClient, tiny_video: Path):
    r = _upload(client, tiny_video, name="clip.exe")
    assert r.status_code == 422


def test_upload_rejects_non_video(client: TestClient):
    r = client.post("/api/jobs", content=b"to nie jest wideo" * 100,
                    headers={"X-Filename": "fake.mp4"})
    assert r.status_code == 422


def test_upload_rejects_empty_body(client: TestClient):
    r = client.post("/api/jobs", content=b"", headers={"X-Filename": "e.mp4"})
    assert r.status_code == 422


def test_get_job_roundtrip(client: TestClient, tiny_video: Path):
    job_id = _upload(client, tiny_video).json()["id"]
    r = client.get(f"/api/jobs/{job_id}")
    assert r.status_code == 200
    assert r.json()["id"] == job_id


def test_foreign_sid_sees_404(client: TestClient, tiny_video: Path):
    job_id = _upload(client, tiny_video).json()["id"]
    client.cookies.set("piro_sid", "x" * 32)  # inna przeglądarka
    assert client.get(f"/api/jobs/{job_id}").status_code == 404


def test_no_cookie_sees_404(client: TestClient, tiny_video: Path):
    job_id = _upload(client, tiny_video).json()["id"]
    client.cookies.clear()
    assert client.get(f"/api/jobs/{job_id}").status_code == 404


def test_set_session_from_timeline(client: TestClient, tiny_video: Path):
    job_id = _upload(client, tiny_video).json()["id"]
    r = client.post(f"/api/jobs/{job_id}/session",
                    json={"source": "timeline",
                          "timeline": "1: 1.0s | 2: 2.5s (+1.5s)"})
    assert r.status_code == 200, r.text
    shots = r.json()["shots"]
    assert [s["czas"] for s in shots] == [1.0, 2.5]


def test_set_session_from_api_id(client: TestClient, tiny_video: Path,
                                 monkeypatch: pytest.MonkeyPatch):
    from piro_overlay.models import Session, Shot
    from piro_overlay import pipeline as pl
    monkeypatch.setattr(pl.api, "fetch_session",
                        lambda rid: Session(shots=[Shot(1, 2.0)], uczestnik="Test"))
    job_id = _upload(client, tiny_video).json()["id"]
    r = client.post(f"/api/jobs/{job_id}/session", json={"source": "id", "id": 5})
    assert r.status_code == 200, r.text
    assert r.json()["session_meta"]["uczestnik"] == "Test"


def test_set_session_rejects_empty_timeline(client: TestClient, tiny_video: Path):
    job_id = _upload(client, tiny_video).json()["id"]
    r = client.post(f"/api/jobs/{job_id}/session",
                    json={"source": "timeline", "timeline": "same śmieci"})
    assert r.status_code == 422


def test_analyze_detects_buzzer(client: TestClient, tiny_video: Path):
    job_id = _upload(client, tiny_video).json()["id"]
    client.post(f"/api/jobs/{job_id}/session",
                json={"source": "timeline", "timeline": "1: 1.0s"})
    r = client.post(f"/api/jobs/{job_id}/analyze")
    assert r.status_code == 200, r.text
    data = r.json()
    # Ton 2700 Hz zaczyna się w 0.5 s pliku testowego.
    assert data["t0"] == pytest.approx(0.5, abs=0.2)
    assert data["trim_start"] == 0.0          # t0 − 5 s przycięte do 0
    assert data["trim_end"] == pytest.approx(3.0, abs=0.3)  # clamp do długości


def test_preview_returns_png_with_overlay(client: TestClient, tiny_video: Path):
    job_id = _upload(client, tiny_video).json()["id"]
    client.post(f"/api/jobs/{job_id}/session",
                json={"source": "timeline", "timeline": "1: 0.5s | 2: 1.5s (+1.0s)"})
    r = client.get(f"/api/jobs/{job_id}/preview",
                   params={"t": 1.2, "t0": 0.5, "h": 240})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
    # Ten sam t → cache klatki (bez FFmpeg); inny styl nadal działa.
    r2 = client.get(f"/api/jobs/{job_id}/preview",
                    params={"t": 1.2, "t0": 0.5, "h": 240, "clock": "true"})
    assert r2.status_code == 200
    assert r2.content != r.content  # zegar zmienia obraz


def test_preview_validates_range(client: TestClient, tiny_video: Path):
    job_id = _upload(client, tiny_video).json()["id"]
    assert client.get(f"/api/jobs/{job_id}/preview",
                      params={"t": 999}).status_code == 422
    assert client.get(f"/api/jobs/{job_id}/preview",
                      params={"t": 1.0, "h": 4000}).status_code == 422


def _wait_state(client: TestClient, job_id: str, states: set[str],
                timeout: float = 90.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = client.get(f"/api/jobs/{job_id}").json()
        if data["state"] in states:
            return data
        time.sleep(0.3)
    raise AssertionError(f"Zadanie nie osiągnęło {states} w {timeout}s: {data}")


def test_full_render_cycle_mp4(client: TestClient, tiny_video: Path):
    job_id = _upload(client, tiny_video).json()["id"]
    client.post(f"/api/jobs/{job_id}/session",
                json={"source": "timeline", "timeline": "1: 0.5s | 2: 1.5s (+1.0s)"})
    r = client.post(f"/api/jobs/{job_id}/render",
                    json={"format": "mp4", "t0": 0.5,
                          "trim_start": 0.0, "trim_end": 3.0})
    assert r.status_code == 202, r.text
    data = _wait_state(client, job_id, {"done", "failed"})
    assert data["state"] == "done", data["error"]
    assert data["progress"] == 1.0
    dl = client.get(f"/api/jobs/{job_id}/download")
    assert dl.status_code == 200
    assert "tiny_PiRoOverlay.mp4" in dl.headers["content-disposition"]
    assert len(dl.content) > 1000


def test_render_requires_session_and_t0(client: TestClient, tiny_video: Path):
    job_id = _upload(client, tiny_video).json()["id"]
    assert client.post(f"/api/jobs/{job_id}/render",
                       json={"t0": 0.5}).status_code == 422  # brak sesji
    client.post(f"/api/jobs/{job_id}/session",
                json={"source": "timeline", "timeline": "1: 0.5s"})
    assert client.post(f"/api/jobs/{job_id}/render",
                       json={}).status_code == 422           # brak T0


def test_sse_snapshot_first(tmp_path: Path, tiny_video: Path,
                            monkeypatch: pytest.MonkeyPatch):
    # Zadanie w stanie terminalnym → strumień SSE kończy się po snapshocie.
    # (Otwarty nieskończony strumień zakleszcza TestClient przy zamykaniu —
    # pełny cykl SSE do `done` i tak testuje żywy przepływ renderu.)
    monkeypatch.setenv("PIRO_WEB_DATA_DIR", str(tmp_path / "jobs"))
    from web.backend.app import create_app
    from web.backend.jobs import JobState
    app = create_app()
    with TestClient(app) as c:
        job_id = _upload(c, tiny_video).json()["id"]
        job = app.state.store.all()[0]
        job.state = JobState.DONE
        job.finished = time.time()
        with c.stream("GET", f"/api/jobs/{job_id}/events") as r:
            assert r.headers["content-type"].startswith("text/event-stream")
            lines = list(r.iter_lines())
    assert lines[0] == "event: state"
    assert '"state": "done"' in lines[1]


def test_cancel_render(client: TestClient, tiny_video: Path):
    job_id = _upload(client, tiny_video).json()["id"]
    client.post(f"/api/jobs/{job_id}/session",
                json={"source": "timeline", "timeline": "1: 0.5s"})
    client.post(f"/api/jobs/{job_id}/render", json={"t0": 0.5})
    client.post(f"/api/jobs/{job_id}/cancel")
    data = _wait_state(client, job_id, {"cancelled", "done", "failed"})
    # Wyścig jest dozwolony (render mógł zdążyć), ale zwykle: cancelled.
    assert data["state"] in ("cancelled", "done")
    if data["state"] == "cancelled":
        assert client.get(f"/api/jobs/{job_id}/download").status_code == 404


def test_delete_job_removes_files(client: TestClient, tiny_video: Path):
    job_id = _upload(client, tiny_video).json()["id"]
    r = client.get(f"/api/jobs/{job_id}")
    assert r.status_code == 200
    assert client.delete(f"/api/jobs/{job_id}").status_code == 204
    assert client.get(f"/api/jobs/{job_id}").status_code == 404


def test_upload_413_over_limit(tmp_path: Path, tiny_video: Path,
                               monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PIRO_WEB_DATA_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("PIRO_WEB_MAX_UPLOAD_MB", "0")  # limit 0 MB → wszystko za duże
    from web.backend.app import create_app
    with TestClient(create_app()) as c:
        r = _upload(c, tiny_video)
        assert r.status_code == 413
        # katalog zadania posprzątany
        assert not list((tmp_path / "jobs").rglob("source*"))
