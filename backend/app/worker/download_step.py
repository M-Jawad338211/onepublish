"""Download (SRS §3.3): one file per video, shared by every target (FR-14)."""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import exists, or_, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app import settings_store
from app.db import session_factory, utcnow
from app.models import FINAL_JOB_STATES, AlertKind, DownloadStatus, Job, JobState, Video
from app.services import media, staging
from app.services.alerts import log_event, raise_alert
from app.services.downloader import BotCheck, SkipVideo, download_short
from app.worker.context import WorkerContext

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
BOT_CHECK_RETRY = timedelta(hours=1)


async def _claim(session: AsyncSession) -> Video | None:
    now = utcnow()
    has_queued_job = exists().where(Job.video_id == Video.id, Job.state == JobState.QUEUED)
    video = (
        await session.exec(
            select(Video)
            .where(Video.download_status == DownloadStatus.NEW)
            .where(or_(col(Video.next_attempt_at).is_(None), col(Video.next_attempt_at) <= now))
            .where(has_queued_job)
            .order_by(col(Video.id))
            .limit(1)
            .with_for_update(skip_locked=True)
        )
    ).first()
    if video is None:
        return None
    video.download_status = DownloadStatus.DOWNLOADING
    video.download_attempts += 1
    session.add(video)
    await session.commit()
    return video


async def _end_open_jobs(
    session: AsyncSession, video_id: int, state: JobState, reason: str
) -> None:
    await session.exec(  # type: ignore[call-overload]
        update(Job)
        .where(col(Job.video_id) == video_id, col(Job.state).not_in(FINAL_JOB_STATES))
        .values(state=state, last_error=reason, finished_at=utcnow())
    )


async def download_step(ctx: WorkerContext) -> None:
    settings = ctx.settings
    async with session_factory()() as session:
        cap = await settings_store.staging_cap_bytes(session)
        if staging.downloads_paused(settings.staging_dir, cap):
            await raise_alert(
                session,
                AlertKind.DISK_HIGH,
                "Staging folder is above 80% of its cap; downloads are paused.",
                dedupe_key="disk-high",
            )
            await session.commit()
            return
        video = await _claim(session)
        if video is None:
            return
        assert video.id is not None
        out_dir = staging.video_dir(staging.ensure(settings.staging_dir), video.yt_video_id)

        try:
            result = await asyncio.to_thread(download_short, video.yt_video_id, settings, out_dir)
            path, probe = await media.ensure_tiktok_compatible(result.path)
        except (SkipVideo, media.MediaInvalid) as e:
            reason = str(e)
            staging.delete_video_files(settings.staging_dir, video.yt_video_id, None)
            video.download_status = DownloadStatus.SKIPPED
            video.skip_reason = reason
            await _end_open_jobs(session, video.id, JobState.SKIPPED, f"skipped: {reason}")
            log_event(session, f"Skipped: {reason}", video_id=video.id)
            session.add(video)
            await session.commit()
            return
        except BotCheck as e:
            staging.delete_video_files(settings.staging_dir, video.yt_video_id, None)
            video.download_status = DownloadStatus.NEW
            video.next_attempt_at = utcnow() + BOT_CHECK_RETRY
            video.last_error = str(e)[:1000]
            await raise_alert(
                session,
                AlertKind.BOT_CHECK,
                "YouTube is asking the server to sign in to confirm it's not a bot. "
                "Refresh YTDLP_COOKIES_B64 or set YTDLP_PROXY.",
                dedupe_key="bot-check",
            )
            log_event(session, "YouTube bot check", video_id=video.id, level="WARNING")
            session.add(video)
            await session.commit()
            return
        except Exception as e:  # noqa: BLE001
            staging.delete_video_files(settings.staging_dir, video.yt_video_id, None)
            video.last_error = str(e)[:1000]
            log.warning("download failed", extra={"video": video.yt_video_id, "err": str(e)})
            if video.download_attempts >= MAX_ATTEMPTS:
                video.download_status = DownloadStatus.FAILED
                await _end_open_jobs(session, video.id, JobState.FAILED, f"download: {e}"[:1000])
                await raise_alert(
                    session,
                    AlertKind.DOWNLOAD_FAILING,
                    f"Download failed {MAX_ATTEMPTS} times for {video.yt_video_id}: {e}"[:500],
                    dedupe_key=f"download-failed:{video.id}",
                )
            else:
                video.download_status = DownloadStatus.NEW
                video.next_attempt_at = utcnow() + timedelta(minutes=2**video.download_attempts)
            log_event(session, f"Download error: {e}"[:500], video_id=video.id, level="WARNING")
            session.add(video)
            await session.commit()
            return

        video.title = result.title or video.title
        video.description = result.description or video.description
        video.tags = result.tags
        video.duration_s = probe.duration_s or result.duration_s
        video.width = probe.width
        video.height = probe.height
        video.fps = probe.fps
        video.published_at = result.published_at or video.published_at
        video.file_path = str(path)
        video.file_size = probe.size
        video.download_status = DownloadStatus.READY
        video.downloaded_at = utcnow()
        video.last_error = None
        log_event(
            session,
            "Downloaded",
            video_id=video.id,
            payload={"bytes": probe.size, "codec": probe.vcodec, "fps": probe.fps},
        )
        session.add(video)
        await session.commit()
