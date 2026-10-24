"""TikTok Login Kit + Content Posting API (inbox upload only), SRS §4.2.

Endpoints used:
  authorize            https://www.tiktok.com/v2/auth/authorize/
  token / refresh      POST /v2/oauth/token/
  revoke               POST /v2/oauth/revoke/
  user info            GET  /v2/user/info/
  inbox upload init    POST /v2/post/publish/inbox/video/init/
  chunk upload         PUT  <upload_url>
  status               POST /v2/post/publish/status/fetch/
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from app.db import utcnow
from app.services.chunking import ChunkPlan

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
API_BASE = "https://open.tiktokapis.com"
SCOPES = ("user.info.basic", "video.upload")

# Status values from /v2/post/publish/status/fetch/
STATUS_PROCESSING = {"PROCESSING_UPLOAD", "PROCESSING_DOWNLOAD"}
STATUS_INBOX = "SEND_TO_USER_INBOX"
STATUS_PUBLISHED = "PUBLISH_COMPLETE"
STATUS_FAILED = "FAILED"

# Error codes / fail reasons worth retrying (FR-30). Everything else fails the job.
RETRYABLE = {
    "internal_error",
    "internal",
    "rate_limit_exceeded",
    "video_pull_failed",
    "upload_url_expired",
    "network_error",
    "http_5xx",
    "bad_response",
}
# The account (not the video) is the problem: pause the target instead of failing for good.
PAUSE_TARGET = {"spam_risk_too_many_pending_share", "spam_risk_too_many_posts"}
RECONNECT = {"access_token_invalid", "auth_removed", "scope_not_authorized", "invalid_grant"}


def _json(resp: httpx.Response) -> dict[str, Any]:
    if not resp.content:
        return {}
    try:
        body = resp.json()
    except ValueError as e:
        raise TikTokError("bad_response", resp.text[:200], status=resp.status_code) from e
    return body if isinstance(body, dict) else {}


class TikTokError(Exception):
    def __init__(self, code: str, message: str = "", log_id: str | None = None, status: int = 0):
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code
        self.message = message
        self.log_id = log_id
        self.status = status

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE

    @property
    def pauses_target(self) -> bool:
        return self.code in PAUSE_TARGET

    @property
    def needs_reconnect(self) -> bool:
        return self.code in RECONNECT


@dataclass
class TokenSet:
    open_id: str
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime
    scopes: str


@dataclass
class UserInfo:
    open_id: str
    display_name: str
    avatar_url: str | None


@dataclass
class InitResult:
    publish_id: str
    upload_url: str
    log_id: str | None


@dataclass
class PublishStatus:
    status: str
    fail_reason: str | None
    log_id: str | None


def new_pkce_pair() -> tuple[str, str]:
    """TikTok expects the challenge as the hex SHA-256 of the verifier (not base64url)."""
    verifier = secrets.token_urlsafe(48)[:64]
    return verifier, hashlib.sha256(verifier.encode()).hexdigest()


def authorize_url(
    client_key: str, redirect_uri: str, state: str, code_challenge: str | None
) -> str:
    params = {
        "client_key": client_key,
        "scope": ",".join(SCOPES),
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
    }
    if code_challenge:
        params |= {"code_challenge": code_challenge, "code_challenge_method": "S256"}
    return f"{AUTH_URL}?{urlencode(params)}"


def _token_set(body: dict[str, Any]) -> TokenSet:
    now = utcnow()
    return TokenSet(
        open_id=body["open_id"],
        access_token=body["access_token"],
        access_expires_at=now + timedelta(seconds=int(body["expires_in"])),
        refresh_token=body["refresh_token"],
        refresh_expires_at=now + timedelta(seconds=int(body["refresh_expires_in"])),
        scopes=body.get("scope", ""),
    )


class TikTokClient:
    def __init__(
        self,
        client_key: str,
        client_secret: str,
        http: httpx.AsyncClient | None = None,
    ):
        self.client_key = client_key
        self.client_secret = client_secret
        self.http = http or httpx.AsyncClient(timeout=httpx.Timeout(30, write=300))

    async def aclose(self) -> None:
        await self.http.aclose()

    # --- OAuth ---------------------------------------------------------------

    async def _oauth(self, path: str, data: dict[str, str]) -> dict[str, Any]:
        payload = {"client_key": self.client_key, "client_secret": self.client_secret} | data
        try:
            resp = await self.http.post(
                f"{API_BASE}{path}",
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.TransportError as e:
            raise TikTokError("network_error", str(e)) from e
        if resp.status_code >= 500:
            raise TikTokError("http_5xx", resp.text[:200], status=resp.status_code)
        body = _json(resp)
        if "error" in body and body.get("error") not in ("", None) and "access_token" not in body:
            err = body["error"]
            code = err if isinstance(err, str) else err.get("code", "unknown")
            raise TikTokError(
                code, body.get("error_description", ""), body.get("log_id"), resp.status_code
            )
        return body

    async def exchange_code(
        self, code: str, redirect_uri: str, code_verifier: str | None
    ) -> TokenSet:
        data = {"code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri}
        if code_verifier:
            data["code_verifier"] = code_verifier
        return _token_set(await self._oauth("/v2/oauth/token/", data))

    async def refresh(self, refresh_token: str) -> TokenSet:
        data = {"grant_type": "refresh_token", "refresh_token": refresh_token}
        return _token_set(await self._oauth("/v2/oauth/token/", data))

    async def revoke(self, access_token: str) -> None:
        await self._oauth("/v2/oauth/revoke/", {"token": access_token})

    # --- API -----------------------------------------------------------------

    async def _api(
        self, method: str, path: str, token: str, **kwargs: Any
    ) -> tuple[dict[str, Any], str | None]:
        headers = {"Authorization": f"Bearer {token}"}
        if "json" in kwargs:
            headers["Content-Type"] = "application/json; charset=UTF-8"
        try:
            resp = await self.http.request(method, f"{API_BASE}{path}", headers=headers, **kwargs)
        except httpx.TransportError as e:
            raise TikTokError("network_error", str(e)) from e
        if resp.status_code >= 500:
            raise TikTokError("http_5xx", resp.text[:200], status=resp.status_code)
        body = _json(resp)
        err = body.get("error") or {}
        log_id = err.get("log_id")
        if err.get("code", "ok") != "ok":
            raise TikTokError(err["code"], err.get("message", ""), log_id, resp.status_code)
        if resp.status_code >= 400:
            raise TikTokError(f"http_{resp.status_code}", resp.text[:200], log_id, resp.status_code)
        return body.get("data") or {}, log_id

    async def user_info(self, token: str) -> UserInfo:
        data, _ = await self._api(
            "GET",
            "/v2/user/info/",
            token,
            params={"fields": "open_id,avatar_url,display_name"},
        )
        user = data.get("user", {})
        return UserInfo(
            open_id=user.get("open_id", ""),
            display_name=user.get("display_name") or "TikTok account",
            avatar_url=user.get("avatar_url"),
        )

    async def init_inbox_upload(self, token: str, plan: ChunkPlan) -> InitResult:
        data, log_id = await self._api(
            "POST",
            "/v2/post/publish/inbox/video/init/",
            token,
            json={
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": plan.video_size,
                    "chunk_size": plan.chunk_size,
                    "total_chunk_count": plan.total_chunks,
                }
            },
        )
        return InitResult(data["publish_id"], data["upload_url"], log_id)

    async def put_chunk(self, upload_url: str, plan: ChunkPlan, index: int, chunk: bytes) -> bool:
        """Uploads one chunk. Returns True when TikTok reports the whole file received."""
        start, end = plan.byte_range(index)
        if len(chunk) != end - start + 1:
            raise ValueError("chunk length does not match the plan")
        try:
            resp = await self.http.put(
                upload_url,
                content=chunk,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {start}-{end}/{plan.video_size}",
                },
            )
        except httpx.TransportError as e:
            raise TikTokError("network_error", str(e)) from e
        if resp.status_code == 201:
            return True
        if resp.status_code == 206:
            return False
        if resp.status_code in (403, 404, 410):
            raise TikTokError("upload_url_expired", resp.text[:200], status=resp.status_code)
        if resp.status_code >= 500:
            raise TikTokError("http_5xx", resp.text[:200], status=resp.status_code)
        raise TikTokError(f"upload_http_{resp.status_code}", resp.text[:200])

    async def fetch_status(self, token: str, publish_id: str) -> PublishStatus:
        data, log_id = await self._api(
            "POST", "/v2/post/publish/status/fetch/", token, json={"publish_id": publish_id}
        )
        return PublishStatus(data.get("status", ""), data.get("fail_reason") or None, log_id)
