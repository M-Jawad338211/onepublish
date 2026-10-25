"""Inbox upload (SRS §3.6), one job at a time per target.

Idempotency (NFR-2): publish_id and upload_url are committed before the first chunk.
A job that crashed mid-upload asks TikTok for the status of its publish_id first; if
the file already arrived it moves straight to PROCESSING and init is never repeated.
An upload that never finished produced no draft, so re-initialising it is safe.
"""

import logging
from datetime import timedelta
from pathlib import Path

from sqlalchemy import case, or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app import settings_store
from app.db import session_factory, utcnow
from app.models import (
    AlertKind,
    DownloadStatus,
    Job,
    JobState,
    Mapping,
    Target,
    TargetStatus,
    Video,
)
from app.services import tiktok as tt
from app.services.alerts import log_event, raise_alert
from app.services.caption import CaptionOptions, build_caption
from app.services.chunking import plan_chunks
from app.worker.context import WorkerContext
from app.worker.quota import quota_state
from app.worker.tokens import NoValidToken, access_token_for, mark_needs_reconnect

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
UPLOAD_URL_TTL = timedelta(minutes=55)  # TikTok says 1 h; keep a margin
PAUSE_FOR = timedelta(hours=24)
IN_FLIGHT = (JobState.QUEUED, JobState.INIT, JobState.UPLOADING)


def caption_options(mapping: Mapping | None) -> CaptionOptions:
    if mapping is None:
        return CaptionOptions()
    return CaptionOptions(
        include_title=mapping.include_title,
        include_description=mapping.include_description,
        include_tags=mapping.include_tags,
        prefix=mapping.caption_prefix,
        suffix=mapping.caption_suffix,
        extra_tags=list(mapping.extra_tags),
        strip_tags=list(mapping.strip_tags),
        max_len=mapping.max_len,
    )


def backoff(attempts: int) -> timedelta:
    return timedelta(minutes=min(60, 2**attempts))


def reset_upload(job: Job) -> None:
    job.publish_id = None
    job.upload_url = None
    job.upload_url_expires_at = None
    job.chunk_size = None
    job.total_chunks = None
    job.chunks_done = 0


async def recent_uploads(session: AsyncSession, target_id: int) -> list:
    since = utcnow() - timedelta(hours=24)
    rows = await session.exec(
        select(Job.uploaded_at).where(
            Job.target_id == target_id, col(Job.uploaded_at).is_not(None), Job.uploaded_at > since
        )
    )
    return [r for r in rows if r is not None]


async def _eligible_targets(session: AsyncSession) -> list[Target]:
    now = utcnow()
    return list(
        await session.exec(
            select(Target)
            .where(Target.status == TargetStatus.ACTIVE)
            .where(or_(col(Target.paused_until).is_(None), col(Target.paused_until) <= now))
            .order_by(col(Target.id))
        )
    )


async def _claim(session: AsyncSession, target_id: int) -> Job | None:
    now = utcnow()
    resume_first = case(
        (Job.state == JobState.UPLOADING, 0), (Job.state == JobState.INIT, 1), else_=2
    )
    return (
        await session.exec(
            select(Job)
            .join(Video, Video.id == Job.video_id)  # type: ignore[arg-type]
            .where(Job.target_id == target_id, col(Job.state).in_(IN_FLIGHT))
            .where(Video.download_status == DownloadStatus.READY)
            .where(or_(col(Job.next_attempt_at).is_(None), col(Job.next_attempt_at) <= now))
            .order_by(resume_first, col(Job.id))
            .limit(1)
            .with_for_update(of=Job, skip_locked=True)  # type: ignore[arg-type]
        )
    ).first()


async def upload_step(ctx: WorkerContext) -> None:
    async with session_factory()() as session:
        targets = await _eligible_targets(session)
    for target in targets:
        if ctx.stopping.is_set():
            return
        async with session_factory()() as session:
            assert target.id is not None
            cap = await settings_store.daily_upload_cap(session)
            quota = quota_state(await recent_uploads(session, target.id), utcnow(), cap)
            job = await _claim(session, target.id)
            if job is None:
                await session.rollback()
                continue
            fresh_init = job.state != JobState.UPLOADING or not job.publish_id
            if fresh_init and not quota.available:
                await session.rollback()
                continue
            if fresh_init and not ctx.init_limiter.allow(target.id):
                await session.rollback()
                continue
            try:
                await run_upload(ctx, session, job)
            except Exception:
                # One broken target or file must not stall uploads to the others.
                log.exception("upload failed", extra={"job_id": job.id, "target_id": target.id})
                await session.rollback()


# A dropped connection or TikTok 5xx mid-upload: the upload URL is still valid, so the
# next attempt continues from chunks_done instead of starting a new upload. Every new
# init is another pending share at TikTok, so avoid them when the old one can finish.
RESUMABLE = {"network_error", "http_5xx"}


def _can_resume(job: Job, err: tt.TikTokError) -> bool:
    return (
        err.code in RESUMABLE
        and job.state == JobState.UPLOADING
        and bool(job.publish_id and job.upload_url)
        and job.upload_url_expires_at is not None
        and job.upload_url_expires_at > utcnow() + timedelta(minutes=5)
    )


async def _fail(session: AsyncSession, job: Job, target: Target, err: tt.TikTokError) -> None:
    job.last_error = str(err)[:1000]
    job.tiktok_log_id = err.log_id or job.tiktok_log_id
    if err.pauses_target:
        target.paused_until = utcnow() + PAUSE_FOR
        target.pause_reason = err.code
        session.add(target)
        reset_upload(job)
        job.state = JobState.QUEUED
        await raise_alert(
            session,
            AlertKind.TARGET_PAUSED,
            f"{target.display_name} paused for 24 h: TikTok says {err.code}. "
            "Publish or delete pending drafts in the TikTok app.",
            target_id=target.id,
            dedupe_key=f"paused:{target.id}",
        )
    elif err.needs_reconnect:
        reset_upload(job)
        job.state = JobState.QUEUED
        await mark_needs_reconnect(session, target, err.code)
    elif err.retryable and job.attempts + 1 < MAX_ATTEMPTS:
        job.attempts += 1
        if not _can_resume(job, err):
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
            f"Upload to {target.display_name} failed: {err.code}",
            target_id=target.id,
            job_id=job.id,
        )
    log_event(
        session,
        f"Upload error: {err}",
        job_id=job.id,
        level="WARNING",
        payload={
            "code": err.code,
            "message": err.message,
            "http_status": err.status,
            "log_id": err.log_id,
        },
    )
    session.add(job)
    await session.commit()


async def run_upload(ctx: WorkerContext, session: AsyncSession, job: Job) -> None:
    video = await session.get(Video, job.video_id)
    target = await session.get(Target, job.target_id)
    assert video is not None and target is not None and video.file_path and video.file_size
    mapping = await session.get(Mapping, job.mapping_id) if job.mapping_id else None
    path = Path(video.file_path)

    try:
        token = await access_token_for(session, ctx.tiktok, target.id)  # type: ignore[arg-type]
    except NoValidToken:
        await session.rollback()
        return
    except tt.TikTokError as e:
        await _fail(session, job, target, e)
        return

    if job.caption is None:
        job.caption = build_caption(
            video.title, video.description, list(video.tags or []), caption_options(mapping)
        )

    plan = plan_chunks(video.file_size)
    try:
        if job.state == JobState.UPLOADING and job.publish_id:
            status = await ctx.tiktok.fetch_status(token, job.publish_id)
            if status.status and status.status not in ("PROCESSING_UPLOAD", tt.STATUS_FAILED):
                # The last chunk landed before the crash: never upload this job again.
                await _mark_uploaded(session, job, "Upload already complete at TikTok")
                return
            expired = job.upload_url_expires_at is None or job.upload_url_expires_at <= utcnow()
            if expired or status.status == tt.STATUS_FAILED or job.chunk_size != plan.chunk_size:
                reset_upload(job)

        if not job.publish_id:
            job.state = JobState.INIT
            session.add(job)
            await session.commit()
            init = await ctx.tiktok.init_inbox_upload(token, plan)
            job.publish_id = init.publish_id
            job.upload_url = init.upload_url
            job.upload_url_expires_at = utcnow() + UPLOAD_URL_TTL
            job.chunk_size = plan.chunk_size
            job.total_chunks = plan.total_chunks
            job.chunks_done = 0
            job.tiktok_log_id = init.log_id
            job.state = JobState.UPLOADING
            log_event(
                session,
                "Inbox upload initialised",
                job_id=job.id,
                payload={"publish_id": init.publish_id, "chunks": plan.total_chunks},
            )
            session.add(job)
            await session.commit()

        assert job.upload_url is not None
        complete = False
        first = job.chunks_done
        with path.open("rb") as f:
            for index in range(first, plan.total_chunks):
                if ctx.stopping.is_set() and index > first:
                    return  # resumable: the next run continues from chunks_done
                start, end = plan.byte_range(index)
                f.seek(start)
                complete = await ctx.tiktok.put_chunk(
                    job.upload_url, plan, index, f.read(end - start + 1)
                )
                job.chunks_done = index + 1
                session.add(job)
                await session.commit()
        if not complete:
            raise tt.TikTokError("upload_incomplete", "TikTok never confirmed the last chunk")
        await _mark_uploaded(session, job, "Uploaded; waiting for TikTok")
    except tt.TikTokError as e:
        if e.code == "upload_incomplete":
            e = tt.TikTokError("internal_error", str(e))
        await _fail(session, job, target, e)
    except FileNotFoundError:
        job.state = JobState.FAILED
        job.last_error = "staged file is missing"
        job.finished_at = utcnow()
        session.add(job)
        await session.commit()


async def _mark_uploaded(session: AsyncSession, job: Job, message: str) -> None:
    job.state = JobState.PROCESSING
    job.uploaded_at = utcnow()
    job.next_attempt_at = None
    log_event(session, message, job_id=job.id, payload={"publish_id": job.publish_id})
    session.add(job)
    await session.commit()
