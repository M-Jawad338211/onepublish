"""Worker pipeline against the docker-compose Postgres, with TikTok mocked by respx."""

import asyncio
import os
from datetime import timedelta

import httpx
import pytest
import respx
from sqlmodel import select

from app import crypto
from app.db import session_factory, utcnow
from app.models import (
    Alert,
    AlertKind,
    DownloadStatus,
    Job,
    JobState,
    Mapping,
    Source,
    Target,
    Token,
    Video,
)
from app.services.tiktok import API_BASE, TikTokClient
from app.services.youtube import FeedEntry
from app.worker.cleanup import cleanup_step
from app.worker.context import WorkerContext
from app.worker.download_step import _claim as claim_download
from app.worker.poller import record_entries
from app.worker.status_step import status_step
from app.worker.upload_step import upload_step

pytestmark = pytest.mark.db

INIT_URL = f"{API_BASE}/v2/post/publish/inbox/video/init/"
STATUS_URL = f"{API_BASE}/v2/post/publish/status/fetch/"
UPLOAD_URL = "https://upload.tiktokapis.test/video/?upload_id=1"
OK = {"code": "ok", "message": "", "log_id": "log-1"}


@pytest.fixture
async def world(db, staging_dir):
    """One source → one target with a valid token."""
    source = Source(
        channel_id="UC" + "a" * 22,
        url="https://www.youtube.com/@a",
        title="Chan",
        shorts_playlist_id="UUSH" + "a" * 22,
    )
    target = Target(open_id="open-1", display_name="tt_one")
    db.add_all([source, target])
    await db.flush()
    mapping = Mapping(source_id=source.id, target_id=target.id, caption_suffix="bye")
    token = Token(
        target_id=target.id,
        access_token_enc=crypto.encrypt("access-1"),
        access_expires_at=utcnow() + timedelta(hours=20),
        refresh_token_enc=crypto.encrypt("refresh-1"),
        refresh_expires_at=utcnow() + timedelta(days=300),
    )
    db.add_all([mapping, token])
    await db.commit()
    return source, target, mapping


@pytest.fixture
async def ctx(settings):
    c = WorkerContext(
        settings=settings, tiktok=TikTokClient("ck", "cs"), feed_http=httpx.AsyncClient()
    )
    yield c
    await c.tiktok.aclose()
    await c.feed_http.aclose()


def entry(vid: str, minutes_ago: int = 1, title: str = "A short") -> FeedEntry:
    return FeedEntry(vid, title, "desc #shorts", utcnow() - timedelta(minutes=minutes_ago), None)


async def ready_video(db, staging_dir, world, vid="vid00000001", size=2048) -> tuple[Video, Job]:
    source, target, mapping = world
    folder = staging_dir / vid
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{vid}.mp4"
    path.write_bytes(os.urandom(size))
    video = Video(
        source_id=source.id,
        yt_video_id=vid,
        title="Title",
        description="Body",
        tags=["fun"],
        file_path=str(path),
        file_size=size,
        download_status=DownloadStatus.READY,
        downloaded_at=utcnow(),
    )
    db.add(video)
    await db.flush()
    job = Job(video_id=video.id, target_id=target.id, mapping_id=mapping.id)
    db.add(job)
    await db.commit()
    return video, job


async def reload(model, pk):
    async with session_factory()() as s:
        return await s.get(model, pk)


# --- detection ---------------------------------------------------------------------


async def test_record_entries_is_idempotent_and_respects_cutoff(db, world):
    source, target, _ = world
    source.created_at = utcnow() - timedelta(minutes=30)
    entries = [entry("new00000001"), entry("new00000002"), entry("old00000001", minutes_ago=120)]
    assert await record_entries(db, source, entries) == 2
    await db.commit()
    assert await record_entries(db, source, entries) == 0
    await db.commit()

    videos = list(await db.exec(select(Video)))
    jobs = list(await db.exec(select(Job)))
    assert sorted(v.yt_video_id for v in videos) == ["new00000001", "new00000002"]
    assert len(jobs) == 2 and all(j.state == JobState.QUEUED for j in jobs)


async def test_paused_mapping_records_video_without_jobs(db, world):
    source, _, mapping = world
    mapping.enabled = False
    db.add(mapping)
    await db.commit()
    source.created_at = utcnow() - timedelta(hours=1)
    await record_entries(db, source, [entry("skip0000001")])
    await db.commit()
    video = (await db.exec(select(Video))).one()
    assert video.download_status == DownloadStatus.SKIPPED
    assert list(await db.exec(select(Job))) == []


async def test_download_claim_skips_locked_rows(db, world):
    source, _, _ = world
    source.created_at = utcnow() - timedelta(hours=1)
    await record_entries(db, source, [entry("only0000001")])
    await db.commit()

    async with session_factory()() as s1, session_factory()() as s2:
        a, b = await asyncio.gather(claim_download(s1), claim_download(s2))
    claimed = [v for v in (a, b) if v is not None]
    assert len(claimed) == 1
    assert (await reload(Video, claimed[0].id)).download_status == DownloadStatus.DOWNLOADING


# --- upload → status → cleanup ----------------------------------------------------------


@respx.mock
async def test_full_upload_flow(db, world, ctx, staging_dir):
    video, job = await ready_video(db, staging_dir, world)
    init = respx.post(INIT_URL).respond(
        json={"data": {"publish_id": "p-1", "upload_url": UPLOAD_URL}, "error": OK}
    )
    put = respx.put(UPLOAD_URL).respond(201)

    await upload_step(ctx)
    j = await reload(Job, job.id)
    assert j.state == JobState.PROCESSING
    assert j.publish_id == "p-1" and j.uploaded_at is not None and j.chunks_done == 1
    assert j.caption == "Title\n\nBody\n\n#fun\n\nbye"
    assert init.call_count == 1 and put.call_count == 1
    assert put.calls[0].request.headers["Content-Range"] == "bytes 0-2047/2048"

    respx.post(STATUS_URL).respond(json={"data": {"status": "SEND_TO_USER_INBOX"}, "error": OK})
    await status_step(ctx)
    assert (await reload(Job, job.id)).state == JobState.SEND_TO_USER_INBOX
    alert = (await db.exec(select(Alert))).one()
    assert alert.kind == AlertKind.DRAFT_READY
    assert alert.payload["caption"] == j.caption

    await cleanup_step(ctx)
    v = await reload(Video, video.id)
    assert v.download_status == DownloadStatus.DELETED and v.file_path is None
    assert not (staging_dir / video.yt_video_id).exists()


@respx.mock
async def test_resume_after_crash_never_reinits(db, world, ctx, staging_dir):
    """Crash after the last chunk landed but before PROCESSING was saved."""
    _, job = await ready_video(db, staging_dir, world)
    job.state = JobState.UPLOADING
    job.publish_id = "p-crash"
    job.upload_url = UPLOAD_URL
    job.upload_url_expires_at = utcnow() + timedelta(minutes=30)
    job.chunk_size, job.total_chunks, job.chunks_done = 2048, 1, 0
    db.add(job)
    await db.commit()

    init = respx.post(INIT_URL).respond(json={"data": {}, "error": OK})
    put = respx.put(UPLOAD_URL).respond(201)
    respx.post(STATUS_URL).respond(json={"data": {"status": "PROCESSING_DOWNLOAD"}, "error": OK})

    await upload_step(ctx)
    j = await reload(Job, job.id)
    assert j.state == JobState.PROCESSING and j.publish_id == "p-crash"
    assert init.call_count == 0 and put.call_count == 0


@respx.mock
async def test_resume_mid_upload_continues_from_saved_chunk(db, world, ctx, staging_dir):
    size = 70 * 1024 * 1024  # > 64 MB: seven 10 MiB chunks
    _, job = await ready_video(db, staging_dir, world, size=size)
    job.state = JobState.UPLOADING
    job.publish_id = "p-mid"
    job.upload_url = UPLOAD_URL
    job.upload_url_expires_at = utcnow() + timedelta(minutes=30)
    job.chunk_size, job.total_chunks, job.chunks_done = 10 * 1024 * 1024, 7, 5
    db.add(job)
    await db.commit()

    init = respx.post(INIT_URL).respond(json={"data": {}, "error": OK})
    respx.post(STATUS_URL).respond(json={"data": {"status": "PROCESSING_UPLOAD"}, "error": OK})
    put = respx.put(UPLOAD_URL).mock(side_effect=[httpx.Response(206), httpx.Response(201)])

    await upload_step(ctx)
    assert init.call_count == 0 and put.call_count == 2
    ranges = [c.request.headers["Content-Range"] for c in put.calls]
    assert ranges[0].startswith("bytes 52428800-") and ranges[1].endswith(f"-{size - 1}/{size}")
    assert (await reload(Job, job.id)).state == JobState.PROCESSING


@respx.mock
async def test_daily_cap_holds_uploads(db, world, ctx, staging_dir):
    _, target, _ = world
    video, job = await ready_video(db, staging_dir, world)
    for i in range(5):
        v = Video(yt_video_id=f"done000000{i}", download_status=DownloadStatus.DELETED)
        db.add(v)
        await db.flush()
        db.add(
            Job(
                video_id=v.id,
                target_id=target.id,
                state=JobState.SEND_TO_USER_INBOX,
                uploaded_at=utcnow() - timedelta(hours=i + 1),
            )
        )
    await db.commit()
    init = respx.post(INIT_URL)

    await upload_step(ctx)
    assert init.call_count == 0
    assert (await reload(Job, job.id)).state == JobState.QUEUED


@respx.mock
async def test_pending_share_limit_pauses_target(db, world, ctx, staging_dir):
    _, target, _ = world
    _, job = await ready_video(db, staging_dir, world)
    respx.post(INIT_URL).respond(
        403,
        json={
            "data": {},
            "error": {
                "code": "spam_risk_too_many_pending_share",
                "message": "too many",
                "log_id": "l",
            },
        },
    )
    await upload_step(ctx)
    j = await reload(Job, job.id)
    t = await reload(Target, target.id)
    assert j.state == JobState.QUEUED and j.publish_id is None and j.attempts == 0
    assert t.paused_until is not None and t.paused_until > utcnow() + timedelta(hours=23)
    alert = (await db.exec(select(Alert))).one()
    assert alert.kind == AlertKind.TARGET_PAUSED


@respx.mock
async def test_non_retryable_status_fails_job(db, world, ctx, staging_dir):
    _, job = await ready_video(db, staging_dir, world)
    job.state, job.publish_id, job.uploaded_at = JobState.PROCESSING, "p-x", utcnow()
    db.add(job)
    await db.commit()
    respx.post(STATUS_URL).respond(
        json={"data": {"status": "FAILED", "fail_reason": "file_format_check_failed"}, "error": OK}
    )
    await status_step(ctx)
    j = await reload(Job, job.id)
    assert j.state == JobState.FAILED and "file_format_check_failed" in j.last_error


async def test_sweeper_requeues_stale_files(db, world, ctx, staging_dir):
    video, job = await ready_video(db, staging_dir, world)
    video.downloaded_at = utcnow() - timedelta(hours=25)
    db.add(video)
    await db.commit()

    await cleanup_step(ctx)
    assert (await reload(Job, job.id)).state == JobState.QUEUED
    v = await reload(Video, video.id)
    assert v.download_status == DownloadStatus.NEW and v.file_path is None
    assert not (staging_dir / video.yt_video_id).exists()


async def test_unmapped_source_records_nothing(db, world):
    source, _, mapping = world
    await db.delete(mapping)
    await db.commit()
    source.created_at = utcnow() - timedelta(hours=1)
    assert await record_entries(db, source, [entry("later000001")]) == 0
    await db.commit()
    assert list(await db.exec(select(Video))) == []


async def test_download_waits_for_a_free_slot(db, world):
    source, target, _ = world
    for i in range(5):
        v = Video(yt_video_id=f"used000000{i}", download_status=DownloadStatus.DELETED)
        db.add(v)
        await db.flush()
        db.add(
            Job(
                video_id=v.id,
                target_id=target.id,
                state=JobState.SEND_TO_USER_INBOX,
                uploaded_at=utcnow() - timedelta(hours=1),
            )
        )
    await db.commit()
    source.created_at = utcnow() - timedelta(hours=1)
    await record_entries(db, source, [entry("wait0000001")])
    await db.commit()
    async with session_factory()() as s:
        assert await claim_download(s) is None


async def test_unreadable_token_needs_reconnect(db, world, ctx, staging_dir):
    _, target, _ = world
    _, job = await ready_video(db, staging_dir, world)
    token = await db.get(Token, target.id)
    token.access_token_enc = "not-ciphertext"
    db.add(token)
    await db.commit()

    await upload_step(ctx)
    assert (await reload(Target, target.id)).status == "NEEDS_RECONNECT"
    assert (await reload(Job, job.id)).state == JobState.QUEUED
    alert = (await db.exec(select(Alert))).one()
    assert alert.kind == AlertKind.TARGET_NEEDS_RECONNECT
