import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete
from sqlmodel import col, select

from app import crypto, settings_store
from app.api.deps import SessionDep, SettingsDep, require_admin
from app.db import utcnow
from app.models import Mapping, Target, TargetStatus, Token
from app.schemas import TargetOut, TargetUpdate
from app.services.tiktok import TikTokClient, TikTokError
from app.worker.quota import quota_state
from app.worker.upload_step import recent_uploads

log = logging.getLogger(__name__)

router = APIRouter(prefix="/targets", tags=["targets"], dependencies=[Depends(require_admin)])


async def _out(session: SessionDep, target: Target) -> TargetOut:
    assert target.id is not None
    cap = await settings_store.daily_upload_cap(session)
    quota = quota_state(await recent_uploads(session, target.id), utcnow(), cap)
    token = await session.get(Token, target.id)
    return TargetOut.model_validate(target).model_copy(
        update={
            "quota_used": quota.used,
            "quota_cap": quota.cap,
            "next_slot_at": quota.next_slot_at,
            "access_expires_at": token.access_expires_at if token else None,
            "refresh_expires_at": token.refresh_expires_at if token else None,
        }
    )


async def _get(session: SessionDep, target_id: int) -> Target:
    target = await session.get(Target, target_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Target not found")
    return target


@router.get("", response_model=list[TargetOut])
async def list_targets(session: SessionDep, include_disconnected: bool = False) -> list[TargetOut]:
    stmt = select(Target).order_by(col(Target.display_name))
    if not include_disconnected:
        stmt = stmt.where(Target.status != TargetStatus.DISCONNECTED)
    return [await _out(session, t) for t in await session.exec(stmt)]


@router.patch("/{target_id}", response_model=TargetOut)
async def update_target(target_id: int, body: TargetUpdate, session: SessionDep) -> TargetOut:
    target = await _get(session, target_id)
    if body.status is not None:
        if body.status not in (TargetStatus.ACTIVE, TargetStatus.PAUSED):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Status must be ACTIVE or PAUSED")
        if target.status in (TargetStatus.NEEDS_RECONNECT, TargetStatus.DISCONNECTED):
            raise HTTPException(status.HTTP_409_CONFLICT, "Reconnect this account first")
        target.status = body.status
    if body.clear_pause:
        target.paused_until = None
        target.pause_reason = None
    session.add(target)
    await session.commit()
    await session.refresh(target)
    return await _out(session, target)


@router.delete("/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_target(target_id: int, session: SessionDep, settings: SettingsDep) -> None:
    """Revokes the TikTok token and removes mappings; job history stays (FR-20)."""
    target = await _get(session, target_id)
    token = await session.get(Token, target_id)
    if token is not None:
        client = TikTokClient(settings.tiktok_client_key, settings.tiktok_client_secret)
        try:
            await client.revoke(crypto.decrypt(token.access_token_enc))
        except (TikTokError, crypto.CryptoError, ValueError) as e:
            log.warning("token revoke failed", extra={"target_id": target_id, "err": str(e)})
        finally:
            await client.aclose()
        await session.delete(token)
    await session.exec(delete(Mapping).where(col(Mapping.target_id) == target_id))  # type: ignore[call-overload]
    target.status = TargetStatus.DISCONNECTED
    session.add(target)
    await session.commit()
