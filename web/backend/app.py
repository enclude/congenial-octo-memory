"""Fabryka aplikacji FastAPI — `uvicorn web.backend.app:create_app --factory`.

WYMÓG: dokładnie JEDEN proces uvicorn (`--workers 1`) — magazyn zadań jest
in-memory, a równoległość dają pule wątków (analiza / render).
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from piro_overlay import __version__

from . import api, cleanup
from .jobs import JobStore
from .ratelimit import TokenBucket, general_rate
from .settings import load_settings

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def create_app() -> FastAPI:
    settings = load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        # Pętla zdarzeń zapisana dla wątków roboczych (publish_threadsafe).
        app.state.loop = asyncio.get_running_loop()
        app.state.analyze_pool = ThreadPoolExecutor(
            max_workers=settings.analyze_workers, thread_name_prefix="analyze")
        app.state.render_pool = ThreadPoolExecutor(
            max_workers=settings.render_workers, thread_name_prefix="render")
        cleanup_task = asyncio.create_task(cleanup.cleanup_loop(
            app.state.store, settings,
            [app.state.general_bucket, app.state.render_bucket]))
        yield
        cleanup_task.cancel()
        app.state.render_pool.shutdown(wait=False, cancel_futures=True)
        app.state.analyze_pool.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="Piro Overlay Web", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.store = JobStore()
    app.state.general_bucket = TokenBucket(settings.rate_per_min, 60.0)
    app.state.render_bucket = TokenBucket(settings.renders_per_hour, 3600.0)
    app.include_router(api.router, dependencies=[Depends(general_rate)])
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html")

    return app
