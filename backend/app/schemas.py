"""Request/response models. These shape the OpenAPI spec the web client is generated from."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models import AlertKind, JobState, SourceStatus, TargetStatus


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- auth ----------------------------------------------------------------------


class LoginIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class Me(BaseModel):
    authenticated: bool


# --- sources -------------------------------------------------------------------


class SourceCreate(BaseModel):
    url: str = Field(min_length=3, max_length=500)
    poll_interval_s: int | None = Field(default=None, ge=120, le=86400)
    start_from: datetime | None = None


class SourceUpdate(BaseModel):
    status: SourceStatus | None = None
    poll_interval_s: int | None = Field(default=None, ge=120, le=86400)
    start_from: datetime | None = None


class SourceOut(Out):
    id: int
    channel_id: str
    handle: str | None
    url: str
    title: str
    thumbnail_url: str | None
    shorts_playlist_id: str
    poll_interval_s: int
    start_from: datetime | None
    status: SourceStatus
    last_polled_at: datetime | None
    next_poll_at: datetime | None
    last_error: str | None
    created_at: datetime


# --- targets -------------------------------------------------------------------


class TargetUpdate(BaseModel):
    status: TargetStatus | None = Field(
        default=None, description="ACTIVE or PAUSED; other values are set by the system"
    )
    clear_pause: bool = Field(default=False, description="Lift an automatic 24 h pause now")


class TargetOut(Out):
    id: int
    open_id: str
    display_name: str
    avatar_url: str | None
    status: TargetStatus
    paused_until: datetime | None
    pause_reason: str | None
    created_at: datetime
    quota_used: int = 0
    quota_cap: int = 5
    next_slot_at: datetime | None = None
    access_expires_at: datetime | None = None
    refresh_expires_at: datetime | None = None


# --- mappings ------------------------------------------------------------------


class MappingFields(BaseModel):
    enabled: bool = True
    include_title: bool = True
    include_description: bool = True
    include_tags: bool = True
    caption_prefix: str = Field(default="", max_length=500)
    caption_suffix: str = Field(default="", max_length=500)
    extra_tags: list[str] = Field(default_factory=list, max_length=30)
    strip_tags: list[str] = Field(default_factory=lambda: ["shorts"], max_length=30)
    max_len: int | None = Field(default=None, ge=50, le=2200)


class MappingCreate(MappingFields):
    source_id: int
    target_id: int


class MappingUpdate(BaseModel):
    enabled: bool | None = None
    include_title: bool | None = None
    include_description: bool | None = None
    include_tags: bool | None = None
    caption_prefix: str | None = Field(default=None, max_length=500)
    caption_suffix: str | None = Field(default=None, max_length=500)
    extra_tags: list[str] | None = Field(default=None, max_length=30)
    strip_tags: list[str] | None = Field(default=None, max_length=30)
    max_len: int | None = Field(default=None, ge=50, le=2200)


class MappingOut(MappingFields, Out):
    id: int
    source_id: int
    target_id: int
    created_at: datetime


class CaptionPreviewIn(MappingFields):
    title: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)


class CaptionPreviewOut(BaseModel):
    caption: str
    length: int


# --- jobs ----------------------------------------------------------------------


class VideoRef(BaseModel):
    id: int
    yt_video_id: str
    title: str
    url: str
    thumbnail_url: str
    download_status: str
    skip_reason: str | None


class JobOut(BaseModel):
    id: int
    state: JobState
    video: VideoRef
    source_id: int | None
    source_title: str | None
    target_id: int
    target_name: str
    publish_id: str | None
    tiktok_log_id: str | None
    attempts: int
    chunks_done: int
    total_chunks: int | None
    last_error: str | None
    caption: str | None
    created_at: datetime
    uploaded_at: datetime | None
    finished_at: datetime | None
    next_attempt_at: datetime | None


class JobPage(BaseModel):
    items: list[JobOut]
    next_cursor: int | None


class EventOut(Out):
    id: int
    ts: datetime
    level: str
    message: str
    payload: dict[str, Any]


class JobDetail(JobOut):
    events: list[EventOut]


class ResendIn(BaseModel):
    target_id: int


# --- alerts --------------------------------------------------------------------


class AlertOut(Out):
    id: int
    kind: AlertKind
    target_id: int | None
    job_id: int | None
    message: str
    payload: dict[str, Any]
    read_at: datetime | None
    created_at: datetime


class UnreadCount(BaseModel):
    unread: int


# --- settings / status -----------------------------------------------------------


class SettingsOut(BaseModel):
    staging_cap_gb: float
    default_poll_interval_s: int
    tiktok_redirect_uri: str
    tiktok_client_configured: bool
    cookies_configured: bool
    proxy_configured: bool
    pot_provider_url: str


class SettingsUpdate(BaseModel):
    staging_cap_gb: float | None = Field(default=None, ge=0.5, le=500)
    default_poll_interval_s: int | None = Field(default=None, ge=120, le=86400)


class StatusOut(BaseModel):
    worker_heartbeat_at: datetime | None
    worker_alive: bool
    worker_started_at: datetime | None
    ytdlp_version: str | None
    staging_bytes: int
    staging_cap_bytes: int
    youtube_backoff_until: datetime | None
    downloads_paused_reason: str | None
    downloads_paused_at: datetime | None
    jobs_last_24h: dict[str, int]
    queued_jobs: int


class Health(BaseModel):
    ok: bool
    db: bool
