from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import col, select

from app.api.deps import SessionDep, require_admin
from app.db import utcnow
from app.models import (
    FINAL_JOB_STATES,
    DownloadStatus,
    Event,
    Job,
    JobState,
    Source,
    Target,
    TargetStatus,
    Video,
)
from app.schemas import EventOut, JobDetail, JobOut, JobPage, ResendIn, VideoRef
from app.services.alerts import log_event
from app.services.youtube import thumbnail_for
from app.worker.upload_step import reset_upload

router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[Depends(require_admin)])

RETRYABLE_BY_HAND = {JobState.FAILED, JobState.FAILED_EXPIRED, JobState.SKIPPED}


def _to_out(job: Job, video: Video, target: Target, source: Source | None) -> JobOut:
    assert job.id is not None and video.id is not None
    return JobOut(
        id=job.id,
        state=job.state,
        video=VideoRef(
            id=video.id,
            yt_video_id=video.yt_video_id,
            title=video.title,
            url=f"https://www.youtube.com/shorts/{video.yt_video_id}",
            thumbnail_url=thumbnail_for(video.yt_video_id),
            download_status=video.download_status,
            skip_reason=video.skip_reason,
        ),
        source_id=source.id if source else None,
        source_title=source.title if source else None,
        target_id=job.target_id,
        target_name=target.display_name,
        publish_id=job.publish_id,
        tiktok_log_id=job.tiktok_log_id,
        attempts=job.attempts,
        chunks_done=job.chunks_done,
        total_chunks=job.total_chunks,
        last_error=job.last_error,
        caption=job.caption,
        created_at=job.created_at,
        uploaded_at=job.uploaded_at,
        finished_at=job.finished_at,
        next_attempt_at=job.next_attempt_at,
    )


def _base_query():  # noqa: ANN202
    return (
        select(Job, Video, Target, Source)
        .join(Video, Video.id == Job.video_id)  # type: ignore[arg-type]
        .join(Target, Target.id == Job.target_id)  # type: ignore[arg-type]
        .outerjoin(Source, Source.id == Video.source_id)  # type: ignore[arg-type]
    )


async def _load(session: SessionDep, job_id: int) -> tuple[Job, Video, Target, Source | None]:
    row = (await session.exec(_base_query().where(Job.id == job_id))).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return row  # type: ignore[return-value]


@router.get("", response_model=JobPage)
async def list_jobs(
    session: SessionDep,
    state: list[JobState] | None = Query(default=None),
    source_id: int | None = None,
    target_id: int | None = None,
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    cursor: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> JobPage:
    stmt = _base_query()
    if state:
        stmt = stmt.where(col(Job.state).in_(state))
    if source_id is not None:
        stmt = stmt.where(Video.source_id == source_id)
    if target_id is not None:
        stmt = stmt.where(Job.target_id == target_id)
    if date_from is not None:
        stmt = stmt.where(Job.created_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(Job.created_at < date_to)
    if cursor is not None:
        stmt = stmt.where(col(Job.id) < cursor)
    rows = list(await session.exec(stmt.order_by(col(Job.id).desc()).limit(limit + 1)))
    items = [_to_out(*r) for r in rows[:limit]]
    return JobPage(items=items, next_cursor=items[-1].id if len(rows) > limit else None)


@router.get("/{job_id}", response_model=JobDetail)
async def get_job(job_id: int, session: SessionDep) -> JobDetail:
    job, video, target, source = await _load(session, job_id)
    events = list(
        await session.exec(
            select(Event)
            .where((Event.job_id == job_id) | (Event.video_id == video.id))
            .order_by(col(Event.ts))
        )
    )
    return JobDetail(
        **_to_out(job, video, target, source).model_dump(),
        events=[EventOut.model_validate(e) for e in events],
    )


def _requeue_video(video: Video) -> None:
    """Brings a video whose file is gone (or never came) back into the download queue."""
    if video.download_status in (DownloadStatus.READY, DownloadStatus.DOWNLOADING):
        return
    video.download_status = DownloadStatus.NEW
    video.download_attempts = 0
    video.next_attempt_at = None
    video.skip_reason = None
    video.file_path = None
    video.queued_at = utcnow()


@router.post("/{job_id}/retry", response_model=JobOut)
async def retry_job(job_id: int, session: SessionDep) -> JobOut:
    job, video, target, source = await _load(session, job_id)
    if job.state not in RETRYABLE_BY_HAND:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Job is {job.state}; nothing to retry")
    reset_upload(job)
    job.state = JobState.QUEUED
    job.attempts = 0
    job.last_error = None
    job.finished_at = None
    job.next_attempt_at = None
    job.uploaded_at = None
    _requeue_video(video)
    log_event(session, "Retry requested", job_id=job.id)
    session.add_all([job, video])
    await session.commit()
    return _to_out(job, video, target, source)


@router.post("/{job_id}/skip", response_model=JobOut)
async def skip_job(job_id: int, session: SessionDep) -> JobOut:
    job, video, target, source = await _load(session, job_id)
    if job.state in FINAL_JOB_STATES:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Job is already {job.state}")
    if job.state in (JobState.INIT, JobState.UPLOADING, JobState.PROCESSING):
        raise HTTPException(status.HTTP_409_CONFLICT, "Upload in progress; wait for it to finish")
    job.state = JobState.SKIPPED
    job.last_error = "skipped by operator"
    job.finished_at = utcnow()
    log_event(session, "Skipped by operator", job_id=job.id)
    session.add(job)
    await session.commit()
    return _to_out(job, video, target, source)


@router.post("/{job_id}/resend", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def resend_job(job_id: int, body: ResendIn, session: SessionDep) -> JobOut:
    """Sends the same Short to another target (FR-41)."""
    _, video, _, source = await _load(session, job_id)
    target = await session.get(Target, body.target_id)
    if target is None or target.status == TargetStatus.DISCONNECTED:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown or disconnected target")
    existing = (
        await session.exec(
            select(Job).where(Job.video_id == video.id, Job.target_id == body.target_id)
        )
    ).first()
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"That target already has job #{existing.id} for this Short; retry it instead",
        )
    assert video.id is not None
    job = Job(video_id=video.id, target_id=body.target_id)
    _requeue_video(video)
    session.add_all([job, video])
    await session.flush()
    log_event(session, f"Re-sent to {target.display_name}", job_id=job.id)
    await session.commit()
    await session.refresh(job)
    return _to_out(job, video, target, source)
