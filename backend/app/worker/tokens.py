"""Access-token upkeep (FR-18): refresh before expiry, warn before the refresh token lapses."""

import logging
from datetime import timedelta

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app import crypto
from app.db import session_factory, utcnow
from app.models import AlertKind, Target, TargetStatus, Token
from app.services.alerts import raise_alert
from app.services.tiktok import TikTokClient, TikTokError
from app.worker.context import WorkerContext

log = logging.getLogger(__name__)

REFRESH_AHEAD = timedelta(hours=2)
USE_AHEAD = timedelta(minutes=5)
WARN_AHEAD = timedelta(days=14)


class NoValidToken(Exception):
    pass


async def mark_needs_reconnect(session: AsyncSession, target: Target, reason: str) -> None:
    target.status = TargetStatus.NEEDS_RECONNECT
    target.pause_reason = reason
    session.add(target)
    await raise_alert(
        session,
        AlertKind.TARGET_NEEDS_RECONNECT,
        f"{target.display_name}: TikTok access was lost ({reason}). Reconnect the account.",
        target_id=target.id,
        dedupe_key=f"reconnect:{target.id}",
    )


async def _decrypt(session: AsyncSession, token: Token, value: str) -> str:
    """A token we can't decrypt (e.g. TOKEN_ENC_KEY changed) means the account must reconnect."""
    try:
        return crypto.decrypt(value)
    except Exception as e:  # noqa: BLE001 - InvalidTag, bad base64, bad key
        target = await session.get(Target, token.target_id)
        assert target is not None
        await mark_needs_reconnect(session, target, "stored token unreadable")
        await session.commit()
        raise NoValidToken("stored token unreadable") from e


async def refresh(session: AsyncSession, tiktok: TikTokClient, token: Token) -> str:
    target = await session.get(Target, token.target_id)
    assert target is not None
    refresh_token = await _decrypt(session, token, token.refresh_token_enc)
    try:
        ts = await tiktok.refresh(refresh_token)
    except TikTokError as e:
        if e.retryable:
            raise
        await mark_needs_reconnect(session, target, e.code)
        await session.commit()
        raise NoValidToken(e.code) from e
    # TikTok may rotate the refresh token; always keep the newest one.
    token.access_token_enc = crypto.encrypt(ts.access_token)
    token.access_expires_at = ts.access_expires_at
    token.refresh_token_enc = crypto.encrypt(ts.refresh_token)
    token.refresh_expires_at = ts.refresh_expires_at
    token.scopes = ts.scopes or token.scopes
    token.updated_at = utcnow()
    session.add(token)
    await session.commit()
    log.info("refreshed token", extra={"target_id": token.target_id})
    return ts.access_token


async def access_token_for(session: AsyncSession, tiktok: TikTokClient, target_id: int) -> str:
    token = await session.get(Token, target_id)
    if token is None:
        raise NoValidToken("no token stored")
    if token.access_expires_at - USE_AHEAD > utcnow():
        return await _decrypt(session, token, token.access_token_enc)
    return await refresh(session, tiktok, token)


async def tokens_step(ctx: WorkerContext) -> None:
    now = utcnow()
    async with session_factory()() as session:
        rows = await session.exec(
            select(Token, Target)
            .join(Target, Target.id == Token.target_id)  # type: ignore[arg-type]
            .where(Target.status != TargetStatus.DISCONNECTED)
        )
        pairs = list(rows)
        for token, target in pairs:
            if target.status != TargetStatus.NEEDS_RECONNECT and (
                token.access_expires_at - REFRESH_AHEAD <= now
            ):
                try:
                    await refresh(session, ctx.tiktok, token)
                except (TikTokError, NoValidToken) as e:
                    log.warning(
                        "token refresh failed", extra={"target_id": target.id, "err": str(e)}
                    )
            if token.refresh_expires_at - WARN_AHEAD <= now:
                days = max(0, (token.refresh_expires_at - now).days)
                await raise_alert(
                    session,
                    AlertKind.TOKEN_EXPIRING,
                    f"{target.display_name}: TikTok login expires in {days} days. Reconnect it.",
                    target_id=target.id,
                    dedupe_key=f"token-expiring:{target.id}",
                )
        await session.commit()
