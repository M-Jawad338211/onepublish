"""Status checker: poll /status/fetch/ until the draft reaches the inbox (SRS §3.6)."""

import logging

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db import session_factory, utcnow
from app.models import AlertKind, Job, JobState, Source, Target, TargetStatus, Video
from app.services import tiktok as tt
from app.services.alerts import log_event, raise_alert
from app.worker.context import WorkerContext
from app.worker.tokens import NoValidToken, access_token_for, mark_needs_reconnect
from app.worker.upload_step import MAX_ATTEMPTS, PAUSE_FOR, backoff, reset_upload

log = logging.getLogger(__name__)


async def status_step(ctx: WorkerContext) -> None:
    async with session_factory()() as session:
        jobs = list(
            await session.exec(
                select(Job)
                .join(Target, Target.id == Job.target_id)  # type: ignore[arg-type]
                .where(Job.state == JobState.PROCESSING)
                .where(Target.status == TargetStatus.ACTIVE)
                .order_by(col(Job.id))
                .limit(50)
            )
        )
        for job in jobs:
            if ctx.stopping.is_set():
                return
            target = await session.get(Target, job.target_id)
            assert target is not None and job.publish_id
            try:
                token = await access_token_for(session, ctx.tiktok, job.target_id)
                status = await ctx.tiktok.fetch_status(token, job.publish_id)
            except NoValidToken:
                continue
            except tt.TikTokError as e:
                if e.needs_reconnect:
                    await mark_needs_reconnect(session, target, e.code)
                    await session.commit()
                log.warning("status fetch failed", extra={"job_id": job.id, "err": str(e)})
                continue

            if status.status in (tt.STATUS_INBOX, tt.STATUS_PUBLISHED):
                await _finish(session, job, target, status.status)
            elif status.status == tt.STATUS_FAILED:
                await _failed(session, job, target, status.fail_reason or "unknown")
            await session.commit()


async def _finish(session: AsyncSession, job: Job, target: Target, status: str) -> None:
    job.state = JobState(status)
    job.finished_at = utcnow()
    session.add(job)
    log_event(session, f"TikTok: {status}", job_id=job.id)
    if status != tt.STATUS_INBOX:
        return
    video = await session.get(Video, job.video_id)
    source = await session.get(Source, video.source_id) if video and video.source_id else None
    await raise_alert(
        session,
        AlertKind.DRAFT_READY,
        f"Draft ready in {target.display_name}'s TikTok inbox: {video.title if video else ''}",
        target_id=target.id,
        job_id=job.id,
        payload={
            "caption": job.caption or "",
            "video_title": video.title if video else "",
            "yt_video_id": video.yt_video_id if video else None,
            "source": source.title if source else None,
            "target": target.display_name,
        },
    )


async def _failed(session: AsyncSession, job: Job, target: Target, reason: str) -> None:
    job.last_error = f"TikTok: {reason}"
    if reason in tt.PAUSE_TARGET:
        target.paused_until = utcnow() + PAUSE_FOR
        target.pause_reason = reason
        session.add(target)
        reset_upload(job)
        job.state = JobState.QUEUED
        await raise_alert(
            session,
            AlertKind.TARGET_PAUSED,
            f"{target.display_name} paused for 24 h: TikTok says {reason}.",
            target_id=target.id,
            dedupe_key=f"paused:{target.id}",
        )
    elif reason in tt.RETRYABLE and job.attempts + 1 < MAX_ATTEMPTS:
        job.attempts += 1
        reset_upload(job)
        job.state = JobState.QUEUED
        job.next_attempt_at = utcnow() + backoff(job.attempts)
    else:
        job.attempts += 1
        job.state = JobState.FAILED
        job.finished_at = utcnow()
        await raise_alert(
            session,
            AlertKind.JOB_FAILED,
            f"TikTok rejected the upload to {target.display_name}: {reason}",
            target_id=target.id,
            job_id=job.id,
        )
    log_event(session, f"TikTok FAILED: {reason}", job_id=job.id, level="WARNING")
    session.add(job)
