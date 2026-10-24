"""Background worker: `python -m app.worker`.

Each step runs in its own loop at a fixed interval, never overlapping itself. The DB is
the only coordination point, so the API talks to the worker by writing rows (e.g.
"check now" sets source.next_poll_at). SIGTERM stops new work; an upload finishes its
current chunk and resumes from the DB on the next start.
"""

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable

from app.config import get_settings
from app.db import dispose_engine, session_factory, utcnow
from app.logs import setup_logging
from app.models import WorkerStatus
from app.services import staging, youtube
from app.services.downloader import write_cookies, ytdlp_version
from app.services.tiktok import TikTokClient
from app.worker.cleanup import cleanup_step, recover_on_start
from app.worker.context import WorkerContext
from app.worker.download_step import download_step
from app.worker.poller import poll_step
from app.worker.status_step import status_step
from app.worker.tokens import tokens_step
from app.worker.upload_step import upload_step

log = logging.getLogger("app.worker")

Step = Callable[[WorkerContext], Awaitable[None]]


async def heartbeat_step(ctx: WorkerContext) -> None:
    async with session_factory()() as session:
        ws = await session.get(WorkerStatus, 1) or WorkerStatus(id=1, started_at=utcnow())
        ws.heartbeat_at = utcnow()
        ws.ytdlp_version = ytdlp_version()
        session.add(ws)
        await session.commit()


STEPS: list[tuple[str, Step, float]] = [
    ("heartbeat", heartbeat_step, 30),
    ("poll", poll_step, 30),
    ("download", download_step, 10),
    ("upload", upload_step, 20),
    ("status", status_step, 15),
    ("cleanup", cleanup_step, 60),
    ("tokens", tokens_step, 1800),
]


async def run_loop(ctx: WorkerContext, name: str, step: Step, interval: float) -> None:
    while not ctx.stopping.is_set():
        try:
            await step(ctx)
        except Exception:
            log.exception("step failed", extra={"step": name})
        try:
            await asyncio.wait_for(ctx.stopping.wait(), timeout=interval)
        except TimeoutError:
            pass


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    staging.ensure(settings.staging_dir)
    write_cookies(settings)

    ctx = WorkerContext(
        settings=settings,
        tiktok=TikTokClient(settings.tiktok_client_key, settings.tiktok_client_secret),
        feed_http=youtube.feed_client(),
    )
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, ctx.stopping.set)

    await recover_on_start()
    async with session_factory()() as session:
        ws = await session.get(WorkerStatus, 1) or WorkerStatus(id=1)
        ws.started_at = utcnow()
        session.add(ws)
        await session.commit()

    log.info("worker started", extra={"yt_dlp": ytdlp_version()})
    try:
        await asyncio.gather(*(run_loop(ctx, n, s, i) for n, s, i in STEPS))
    finally:
        await ctx.tiktok.aclose()
        await ctx.feed_http.aclose()
        await dispose_engine()
        log.info("worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
