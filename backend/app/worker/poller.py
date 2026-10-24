"""Detection (SRS §3.2): read each source's Shorts feed and record unseen video IDs."""

import logging
from datetime import timedelta

from sqlalchemy import or_
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db import session_factory, utcnow
from app.models import (
    DownloadStatus,
    Job,
    Mapping,
    Source,
    SourceStatus,
    Target,
    TargetStatus,
    WorkerStatus,
)
from app.models import Video as VideoRow
from app.services.alerts import log_event
from app.services.youtube import FeedEntry, YouTubeRateLimited, fetch_shorts_feed
from app.worker.context import WorkerContext

log = logging.getLogger(__name__)

MAX_BACKOFF_S = 3600


async def _youtube_backoff_active(session: AsyncSession) -> bool:
    ws = await session.get(WorkerStatus, 1)
    return bool(ws and ws.youtube_backoff_until and ws.youtube_backoff_until > utcnow())


async def _set_backoff(session: AsyncSession, ctx: WorkerContext) -> None:
    ctx.youtube_backoff_s = min(MAX_BACKOFF_S, max(120, ctx.youtube_backoff_s * 2))
    ws = await session.get(WorkerStatus, 1) or WorkerStatus(id=1)
    ws.youtube_backoff_until = utcnow() + timedelta(seconds=ctx.youtube_backoff_s)
    session.add(ws)


async def record_entries(session: AsyncSession, source: Source, entries: list[FeedEntry]) -> int:
    """Inserts unseen Shorts and one job per enabled mapping. Returns the number of new videos."""
    cutoff = source.start_from or source.created_at
    mappings = list(
        await session.exec(
            select(Mapping)
            .join(Target, Target.id == Mapping.target_id)  # type: ignore[arg-type]
            .where(Mapping.source_id == source.id, Mapping.enabled)
            .where(col(Target.status).in_([TargetStatus.ACTIVE, TargetStatus.PAUSED]))
        )
    )
    if not mappings:
        has_any = (
            await session.exec(select(Mapping.id).where(Mapping.source_id == source.id).limit(1))
        ).first()
        if has_any is None:
            # A source that hasn't been mapped yet records nothing, so the first mapping
            # still gets every Short since start_from. Disabled mappings do record (as
            # SKIPPED) so re-enabling one doesn't back-fill (FR-24).
            return 0
    new = 0
    for entry in entries:
        if entry.published_at < cutoff:
            continue
        stmt = (
            insert(VideoRow)
            .values(
                source_id=source.id,
                yt_video_id=entry.video_id,
                title=entry.title,
                description=entry.description,
                published_at=entry.published_at,
                download_status=DownloadStatus.NEW if mappings else DownloadStatus.SKIPPED,
                skip_reason=None if mappings else "no active mappings",
            )
            .on_conflict_do_nothing(index_elements=["yt_video_id"])
            .returning(VideoRow.id)  # type: ignore[arg-type]
        )
        video_id = (await session.exec(stmt)).scalar_one_or_none()  # type: ignore[call-overload]
        if video_id is None:
            continue  # seen before (FR-7)
        new += 1
        for m in mappings:
            await session.exec(  # type: ignore[call-overload]
                insert(Job)
                .values(video_id=video_id, target_id=m.target_id, mapping_id=m.id)
                .on_conflict_do_nothing(index_elements=["video_id", "target_id"])
            )
        log_event(
            session,
            f"New Short detected: {entry.title}",
            video_id=video_id,
            payload={"yt_video_id": entry.video_id, "targets": len(mappings)},
        )
    return new


async def poll_step(ctx: WorkerContext) -> None:
    now = utcnow()
    async with session_factory()() as session:
        if await _youtube_backoff_active(session):
            return
        sources = list(
            await session.exec(
                select(Source)
                .where(Source.status == SourceStatus.ACTIVE)
                .where(or_(col(Source.next_poll_at).is_(None), col(Source.next_poll_at) <= now))
                .order_by(col(Source.next_poll_at).asc().nulls_first())
                .limit(20)
            )
        )
        for source in sources:
            if ctx.stopping.is_set():
                return
            try:
                entries = await fetch_shorts_feed(source.shorts_playlist_id, ctx.feed_http)
            except YouTubeRateLimited as e:
                await _set_backoff(session, ctx)
                await session.commit()
                log.warning("YouTube rate limited; backing off", extra={"err": str(e)})
                return
            except Exception as e:  # noqa: BLE001 - one bad feed must not stop the rest
                source.last_error = str(e)[:500]
                source.next_poll_at = utcnow() + timedelta(seconds=source.poll_interval_s)
                session.add(source)
                await session.commit()
                log.warning("feed fetch failed", extra={"source_id": source.id, "err": str(e)})
                continue
            new = await record_entries(session, source, entries)
            source.last_polled_at = utcnow()
            source.next_poll_at = source.last_polled_at + timedelta(seconds=source.poll_interval_s)
            source.last_error = None
            session.add(source)
            await session.commit()
            ctx.youtube_backoff_s = 0
            if new:
                log.info("new shorts", extra={"source_id": source.id, "count": new})
