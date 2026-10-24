"""FastAPI app: `uvicorn app.api.main:app`. Every route lives under /api so the Next.js
rewrite can forward /api/* unchanged."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routers import alerts, auth, jobs, mappings, sources, system, targets, tiktok_oauth
from app.config import get_settings
from app.db import dispose_engine
from app.logs import setup_logging


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    setup_logging(get_settings().log_level)
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(
        title="OnePublish YT→TikTok",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    for router in (
        auth.router,
        sources.router,
        targets.router,
        tiktok_oauth.router,
        mappings.router,
        jobs.router,
        alerts.router,
        system.router,
    ):
        app.include_router(router, prefix="/api")
    return app


app = create_app()
