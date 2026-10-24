"""Cleanup (SRS §3.8): delete media as soon as it is no longer needed, and after 24 h always."""

import logging
from datetime import timedelta

from sqlalchemy import exists, or_, update
from sqlmodel import col, select

from app import settings_store
from app.db import session_factory, utcnow
from app.models import (
    FINAL_JOB_STATES,
    AlertKind,
    DownloadStatus,
    Job,
    JobState,
    Video,
    WorkerStatus,
)
from app.services import staging
from app.services.alerts import log_event, raise_alert
from app.worker.context import WorkerContext

log = logging.getLogger(__name__)

MAX_STAGE_AGE = timedelta(hours=24)
# Jobs that still need the file; PROCESSING jobs have already handed it to TikTok.
NEEDS_FILE = (JobState.QUEUED, JobState.INIT, JobState.UPLOADING)


async def cleanup_step(ctx: WorkerContext) -> None:
    staging_dir = ctx.settings.staging_dir
    now = utcnow()
    async with session_factory()() as session:
        open_job = exists().where(Job.video_id == Video.id, col(Job.state).not_in(FINAL_JOB_STATES))
        done = list(
            await session.exec(
                select(Video).where(Video.download_status == DownloadStatus.READY, ~open_job)
            )
        )
        for v in done:
            staging.delete_video_files(staging_dir, v.yt_video_id, v.file_path)
            v.download_status = DownloadStatus.DELETED
            v.file_path = None
            session.add(v)
            log_event(session, "Staged file deleted", video_id=v.id)

        # Sweeper (FR-37): nothing stays staged for more than 24 h, whatever its state.
        stale = list(
            await session.exec(
                select(Video).where(
                    or_(
                        (Video.download_status == DownloadStatus.READY)
                        & (col(Video.downloaded_at) < now - MAX_STAGE_AGE),
                        (col(Video.download_status).in_([DownloadStatus.NEW]))
                        & (col(Video.queued_at) < now - MAX_STAGE_AGE),
                    )
                )
            )
        )
        for v in stale:
            staging.delete_video_files(staging_dir, v.yt_video_id, v.file_path)
            await session.exec(  # type: ignore[call-overload]
                update(Job)
                .where(col(Job.video_id) == v.id, col(Job.state).in_(NEEDS_FILE))
                .values(
                    state=JobState.FAILED_EXPIRED,
                    last_error="not uploaded within 24 h of detection/download",
                    finished_at=now,
                )
            )
            v.download_status = (
                DownloadStatus.DELETED
                if v.download_status == DownloadStatus.READY
                else DownloadStatus.FAILED
            )
            v.file_path = None
            session.add(v)
            log_event(session, "Expired by the 24 h sweeper", video_id=v.id, level="WARNING")
        await session.commit()

        live = set(
            await session.exec(
                select(Video.yt_video_id).where(
                    col(Video.download_status).in_(
                        [DownloadStatus.READY, DownloadStatus.DOWNLOADING]
                    )
                )
            )
        )
        staging.remove_orphans(staging_dir, live)

        used = staging.usage_bytes(staging_dir)
        cap = await settings_store.staging_cap_bytes(session)
        ws = await session.get(WorkerStatus, 1) or WorkerStatus(id=1)
        ws.staging_bytes = used
        session.add(ws)
        if used >= cap * staging.PAUSE_DOWNLOADS_AT:
            await raise_alert(
                session,
                AlertKind.DISK_HIGH,
                f"Staging uses {used / 1024**3:.1f} GB of {cap / 1024**3:.1f} GB.",
                dedupe_key="disk-high",
            )
        await session.commit()


async def recover_on_start() -> None:
    """A crash mid-download leaves DOWNLOADING rows; put them back in the queue."""
    async with session_factory()() as session:
        await session.exec(  # type: ignore[call-overload]
            update(Video)
            .where(col(Video.download_status) == DownloadStatus.DOWNLOADING)
            .values(download_status=DownloadStatus.NEW)
        )
        await session.commit()
