"""Settings page data, an authenticated status view, and the public health check."""

from datetime import timedelta

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func, text
from sqlmodel import col, select

from app import settings_store
from app.api.deps import SessionDep, SettingsDep, require_admin
from app.db import utcnow
from app.models import Job, JobState, WorkerStatus
from app.schemas import Health, SettingsOut, SettingsUpdate, StatusOut

router = APIRouter(tags=["system"])

WORKER_STALE = timedelta(minutes=2)


async def _settings_out(session: SessionDep, settings: SettingsDep) -> SettingsOut:
    values = await settings_store.load(session)
    return SettingsOut(
        staging_cap_gb=float(values["staging_cap_gb"]),
        default_poll_interval_s=int(values["default_poll_interval_s"]),
        tiktok_redirect_uri=settings.tiktok_redirect_uri,
        tiktok_client_configured=bool(settings.tiktok_client_key and settings.tiktok_client_secret),
        cookies_configured=bool(settings.ytdlp_cookies_b64),
        proxy_configured=bool(settings.ytdlp_proxy),
        pot_provider_url=settings.pot_provider_url,
    )


@router.get("/settings", response_model=SettingsOut, dependencies=[Depends(require_admin)])
async def get_settings_view(session: SessionDep, settings: SettingsDep) -> SettingsOut:
    return await _settings_out(session, settings)


@router.patch("/settings", response_model=SettingsOut, dependencies=[Depends(require_admin)])
async def update_settings(
    body: SettingsUpdate, session: SessionDep, settings: SettingsDep
) -> SettingsOut:
    await settings_store.save(session, body.model_dump(exclude_unset=True))
    await session.commit()
    return await _settings_out(session, settings)


@router.get("/status", response_model=StatusOut, dependencies=[Depends(require_admin)])
async def get_status(session: SessionDep) -> StatusOut:
    now = utcnow()
    ws = await session.get(WorkerStatus, 1)
    counts = dict(
        (
            await session.exec(
                select(Job.state, func.count())
                .where(Job.created_at > now - timedelta(hours=24))
                .group_by(col(Job.state))
            )
        ).all()
    )
    queued = (
        await session.exec(
            select(func.count()).select_from(Job).where(Job.state == JobState.QUEUED)
        )
    ).one()
    heartbeat = ws.heartbeat_at if ws else None
    return StatusOut(
        worker_heartbeat_at=heartbeat,
        worker_alive=bool(heartbeat and now - heartbeat < WORKER_STALE),
        worker_started_at=ws.started_at if ws else None,
        ytdlp_version=ws.ytdlp_version if ws else None,
        staging_bytes=ws.staging_bytes if ws else 0,
        staging_cap_bytes=await settings_store.staging_cap_bytes(session),
        youtube_backoff_until=ws.youtube_backoff_until if ws else None,
        downloads_paused_reason=ws.downloads_paused_reason if ws else None,
        downloads_paused_at=ws.downloads_paused_at if ws else None,
        jobs_last_24h={str(k): int(v) for k, v in counts.items()},
        queued_jobs=int(queued),
    )


@router.post(
    "/status/resume-downloads", response_model=StatusOut, dependencies=[Depends(require_admin)]
)
async def resume_downloads(session: SessionDep) -> StatusOut:
    """Lifts the bot-check pause. Use after fixing the cause; a restart with new cookies or
    a new proxy lifts it automatically."""
    ws = await session.get(WorkerStatus, 1)
    if ws and ws.downloads_paused_reason:
        ws.downloads_paused_reason = None
        ws.downloads_paused_at = None
        ws.paused_config_fp = None
        session.add(ws)
        await session.commit()
    return await get_status(session)


@router.get("/health", response_model=Health)
async def health(session: SessionDep, response: Response) -> Health:
    try:
        await session.exec(text("SELECT 1"))  # type: ignore[call-overload]
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return Health(ok=db_ok, db=db_ok)
