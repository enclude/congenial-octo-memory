"""Testy limitów backendu WWW: zadania per sesja, rate limit, sprzątanie TTL."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from web.backend import cleanup  # noqa: E402
from web.backend.jobs import JobState  # noqa: E402
from web.backend.ratelimit import TokenBucket  # noqa: E402


def _app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **env: str):
    monkeypatch.setenv("PIRO_WEB_DATA_DIR", str(tmp_path / "jobs"))
    for key, value in env.items():
        monkeypatch.setenv(f"PIRO_WEB_{key}", value)
    from web.backend.app import create_app
    return create_app()


def _upload(client: TestClient, video: Path):
    return client.post("/api/jobs", content=video.read_bytes(),
                       headers={"X-Filename": "tiny.mp4"})


def test_max_jobs_per_session(tmp_path, tiny_video, monkeypatch):
    app = _app(tmp_path, monkeypatch, MAX_JOBS_PER_SESSION="2")
    with TestClient(app) as c:
        assert _upload(c, tiny_video).status_code == 201
        assert _upload(c, tiny_video).status_code == 201
        r = _upload(c, tiny_video)
        assert r.status_code == 429


def test_delete_frees_session_slot(tmp_path, tiny_video, monkeypatch):
    app = _app(tmp_path, monkeypatch, MAX_JOBS_PER_SESSION="1")
    with TestClient(app) as c:
        job_id = _upload(c, tiny_video).json()["id"]
        assert _upload(c, tiny_video).status_code == 429
        assert c.delete(f"/api/jobs/{job_id}").status_code == 204
        assert _upload(c, tiny_video).status_code == 201


def test_general_rate_limit_429(tmp_path, tiny_video, monkeypatch):
    app = _app(tmp_path, monkeypatch, RATE_PER_MIN="3")
    with TestClient(app) as c:
        # Upload idzie BEZ cookie (klucz = IP), dopiero kolejne żądania mają
        # sid — limit 3/min wyczerpują więc 3 GET-y po uploadzie.
        job_id = _upload(c, tiny_video).json()["id"]
        for _ in range(3):
            assert c.get(f"/api/jobs/{job_id}").status_code == 200
        r = c.get(f"/api/jobs/{job_id}")               # 4. na sid — ponad limit
        assert r.status_code == 429
        assert "retry-after" in r.headers


def test_token_bucket_refills():
    bucket = TokenBucket(rate=60, per_seconds=60.0)  # 1 token/s
    for _ in range(60):
        assert bucket.allow("k")
    assert not bucket.allow("k")
    time.sleep(1.1)
    assert bucket.allow("k")


def test_cleanup_ttl_and_orphans(tmp_path, tiny_video, monkeypatch):
    app = _app(tmp_path, monkeypatch, JOB_TTL_MIN="1")
    with TestClient(app) as c:
        job_id = _upload(c, tiny_video).json()["id"]
        store = app.state.store
        settings = app.state.settings
        job = store.all()[0]
        # Zakończone zadanie starsze niż TTL → sweep usuwa wpis i katalog.
        job.state = JobState.DONE
        job.finished = time.time()
        assert cleanup.sweep(store, settings, now=job.finished + 120) == 1
        assert store.get(job_id, job.sid) is None
        assert not job.dir.exists()
        # Osierocony katalog (bez wpisu w magazynie) też znika.
        orphan = settings.data_dir / "stale-sid" / "deadbeef"
        orphan.mkdir(parents=True)
        (orphan / "source.mp4").write_bytes(b"x")
        cleanup.sweep(store, settings)
        assert not orphan.exists()


def test_cleanup_max_age_kills_active(tmp_path, tiny_video, monkeypatch):
    app = _app(tmp_path, monkeypatch, MAX_JOB_AGE_MIN="1")
    with TestClient(app) as c:
        _upload(c, tiny_video)
        store = app.state.store
        job = store.all()[0]
        assert cleanup.sweep(store, app.state.settings,
                             now=job.created + 120) == 1
        assert job.cancel.is_set()
        assert not job.dir.exists()
