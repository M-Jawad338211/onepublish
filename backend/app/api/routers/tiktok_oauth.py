"""TikTok Login Kit connect flow (FR-17). The redirect URI points at the web domain,
whose /api/* rewrite forwards the callback here."""

import logging
import secrets
from datetime import timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import delete
from sqlmodel import col, select

from app import crypto
from app.api.deps import SessionDep, SettingsDep, is_authenticated, require_admin
from app.db import utcnow
from app.models import OAuthState, Target, TargetStatus, Token
from app.services import tiktok as tt

log = logging.getLogger(__name__)

router = APIRouter(prefix="/tiktok", tags=["tiktok"])

STATE_TTL = timedelta(minutes=10)


def _back_to_targets(settings: SettingsDep, **params: str) -> RedirectResponse:
    query = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(f"{settings.public_web_url}/targets{query}", status_code=302)


@router.get("/connect", dependencies=[Depends(require_admin)])
async def connect(session: SessionDep, settings: SettingsDep) -> RedirectResponse:
    await session.exec(  # type: ignore[call-overload]
        delete(OAuthState).where(col(OAuthState.created_at) < utcnow() - STATE_TTL)
    )
    state = secrets.token_urlsafe(24)
    verifier, challenge = tt.new_pkce_pair() if settings.tiktok_use_pkce else ("", None)
    session.add(OAuthState(state=state, code_verifier=verifier))
    await session.commit()
    url = tt.authorize_url(
        settings.tiktok_client_key, settings.tiktok_redirect_uri, state, challenge
    )
    return RedirectResponse(url, status_code=302)


@router.get("/callback")
async def callback(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> RedirectResponse:
    if not is_authenticated(request, settings):
        return RedirectResponse(f"{settings.public_web_url}/login", status_code=302)
    if error:
        return _back_to_targets(settings, error=error_description or error)
    if not code or not state:
        return _back_to_targets(settings, error="TikTok did not return a code")

    saved = await session.get(OAuthState, state)
    if saved is None or saved.created_at < utcnow() - STATE_TTL:
        return _back_to_targets(settings, error="Login expired or state mismatch; try again")
    verifier = saved.code_verifier or None
    await session.delete(saved)
    await session.commit()

    client = tt.TikTokClient(settings.tiktok_client_key, settings.tiktok_client_secret)
    try:
        tokens = await client.exchange_code(code, settings.tiktok_redirect_uri, verifier)
        user = await client.user_info(tokens.access_token)
    except tt.TikTokError as e:
        log.warning("tiktok connect failed", extra={"code": e.code, "log_id": e.log_id})
        return _back_to_targets(settings, error=f"TikTok: {e.code}")
    finally:
        await client.aclose()

    missing = {"video.upload"} - set(tokens.scopes.split(","))
    if tokens.scopes and missing:
        return _back_to_targets(settings, error="Allow video uploads when connecting")

    target = (await session.exec(select(Target).where(Target.open_id == tokens.open_id))).first()
    if target is None:
        target = Target(open_id=tokens.open_id, display_name=user.display_name)
    target.display_name = user.display_name
    target.avatar_url = user.avatar_url
    target.status = TargetStatus.ACTIVE
    target.paused_until = None
    target.pause_reason = None
    session.add(target)
    await session.flush()
    assert target.id is not None

    token = await session.get(Token, target.id) or Token(
        target_id=target.id,
        access_token_enc="",
        access_expires_at=tokens.access_expires_at,
        refresh_token_enc="",
        refresh_expires_at=tokens.refresh_expires_at,
    )
    token.access_token_enc = crypto.encrypt(tokens.access_token)
    token.access_expires_at = tokens.access_expires_at
    token.refresh_token_enc = crypto.encrypt(tokens.refresh_token)
    token.refresh_expires_at = tokens.refresh_expires_at
    token.scopes = tokens.scopes
    token.updated_at = utcnow()
    session.add(token)
    await session.commit()
    return _back_to_targets(settings, connected=user.display_name)
