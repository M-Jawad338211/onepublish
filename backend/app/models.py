from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlmodel import Field, SQLModel

from app.db import utcnow


def _ts(nullable: bool = True, index: bool = False, default: bool = False) -> Any:
    return Field(
        default_factory=utcnow if default else lambda: None,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=nullable,
            index=index,
            server_default=text("now()") if default else None,
        ),
    )


def _fk(target: str, ondelete: str, nullable: bool = False, index: bool = True) -> Any:
    return Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey(target, ondelete=ondelete), nullable=nullable, index=index
        ),
    )


def _enum(default: Any, index: bool = False) -> Any:
    # Stored as VARCHAR rather than a native Postgres enum so adding a state is a no-op migration.
    server_default = text(f"'{default}'") if default is not None else None
    return Field(
        default=default,
        sa_column=Column(
            String(32), nullable=False, index=index, default=default, server_default=server_default
        ),
    )


def _jsonb(default: Any) -> Any:
    return Field(
        default_factory=lambda: default.copy(),
        sa_column=Column(JSONB, nullable=False, server_default=text(f"'{_json_literal(default)}'")),
    )


def _json_literal(v: Any) -> str:
    return "[]" if isinstance(v, list) else "{}"


def _text_array(default: list[str]) -> Any:
    literal = "{" + ",".join(default) + "}"
    return Field(
        default_factory=lambda: list(default),
        sa_column=Column(ARRAY(Text), nullable=False, server_default=text(f"'{literal}'")),
    )


class SourceStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


class TargetStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    NEEDS_RECONNECT = "NEEDS_RECONNECT"
    DISCONNECTED = "DISCONNECTED"


class DownloadStatus(StrEnum):
    NEW = "NEW"
    DOWNLOADING = "DOWNLOADING"
    READY = "READY"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    DELETED = "DELETED"


class JobState(StrEnum):
    QUEUED = "QUEUED"
    INIT = "INIT"
    UPLOADING = "UPLOADING"
    PROCESSING = "PROCESSING"
    SEND_TO_USER_INBOX = "SEND_TO_USER_INBOX"
    # Reported if the draft was already posted from the TikTok app when we polled.
    PUBLISH_COMPLETE = "PUBLISH_COMPLETE"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    FAILED_EXPIRED = "FAILED_EXPIRED"


FINAL_JOB_STATES = frozenset(
    {
        JobState.SEND_TO_USER_INBOX,
        JobState.PUBLISH_COMPLETE,
        JobState.FAILED,
        JobState.SKIPPED,
        JobState.FAILED_EXPIRED,
    }
)


class AlertKind(StrEnum):
    DRAFT_READY = "DRAFT_READY"
    TOKEN_EXPIRING = "TOKEN_EXPIRING"
    TARGET_NEEDS_RECONNECT = "TARGET_NEEDS_RECONNECT"
    DOWNLOAD_FAILING = "DOWNLOAD_FAILING"
    BOT_CHECK = "BOT_CHECK"
    TARGET_PAUSED = "TARGET_PAUSED"
    DISK_HIGH = "DISK_HIGH"
    JOB_FAILED = "JOB_FAILED"


class Source(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    channel_id: str = Field(unique=True)
    handle: str | None = None
    url: str
    title: str
    thumbnail_url: str | None = None
    shorts_playlist_id: str
    poll_interval_s: int = 600
    start_from: datetime | None = _ts()
    status: SourceStatus = _enum(SourceStatus.ACTIVE)
    last_polled_at: datetime | None = _ts()
    next_poll_at: datetime | None = _ts(index=True)
    last_error: str | None = None
    created_at: datetime = _ts(nullable=False, default=True)


class Target(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    open_id: str = Field(unique=True)
    display_name: str
    avatar_url: str | None = None
    status: TargetStatus = _enum(TargetStatus.ACTIVE)
    paused_until: datetime | None = _ts()
    pause_reason: str | None = None
    created_at: datetime = _ts(nullable=False, default=True)


class Token(SQLModel, table=True):
    target_id: int = Field(
        sa_column=Column(Integer, ForeignKey("target.id", ondelete="CASCADE"), primary_key=True)
    )
    access_token_enc: str
    access_expires_at: datetime = _ts(nullable=False)
    refresh_token_enc: str
    refresh_expires_at: datetime = _ts(nullable=False)
    scopes: str = ""
    updated_at: datetime = _ts(nullable=False, default=True)


class OAuthState(SQLModel, table=True):
    __tablename__ = "oauth_state"
    state: str = Field(primary_key=True)
    code_verifier: str
    created_at: datetime = _ts(nullable=False, default=True)


class Mapping(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("source_id", "target_id"),)
    id: int | None = Field(default=None, primary_key=True)
    source_id: int = _fk("source.id", "CASCADE")
    target_id: int = _fk("target.id", "CASCADE")
    enabled: bool = True
    include_title: bool = True
    include_description: bool = True
    include_tags: bool = True
    caption_prefix: str = ""
    caption_suffix: str = ""
    extra_tags: list[str] = _text_array([])
    strip_tags: list[str] = _text_array(["shorts"])
    max_len: int | None = None
    created_at: datetime = _ts(nullable=False, default=True)


class Video(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    # SET NULL keeps the history when a source is deleted (FR-3).
    source_id: int | None = _fk("source.id", "SET NULL", nullable=True)
    yt_video_id: str = Field(unique=True)
    title: str = ""
    description: str = ""
    tags: list[str] = _jsonb([])
    duration_s: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    published_at: datetime | None = _ts()
    file_path: str | None = None
    file_size: int | None = Field(default=None, sa_column=Column(BigInteger))
    download_status: DownloadStatus = _enum(DownloadStatus.NEW, index=True)
    download_attempts: int = 0
    next_attempt_at: datetime | None = _ts()
    skip_reason: str | None = None
    last_error: str | None = None
    downloaded_at: datetime | None = _ts()
    # Start of the current 24 h window for the sweeper; reset when a job is retried/resent.
    queued_at: datetime = _ts(nullable=False, default=True)
    created_at: datetime = _ts(nullable=False, default=True)


class Job(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("video_id", "target_id"),
        Index("ix_job_target_uploaded", "target_id", "uploaded_at"),
    )
    id: int | None = Field(default=None, primary_key=True)
    video_id: int = _fk("video.id", "CASCADE")
    target_id: int = _fk("target.id", "CASCADE")
    mapping_id: int | None = _fk("mapping.id", "SET NULL", nullable=True, index=False)
    state: JobState = _enum(JobState.QUEUED, index=True)
    publish_id: str | None = None
    upload_url: str | None = None
    upload_url_expires_at: datetime | None = _ts()
    chunk_size: int | None = Field(default=None, sa_column=Column(BigInteger))
    total_chunks: int | None = None
    chunks_done: int = 0
    caption: str | None = None
    attempts: int = 0
    next_attempt_at: datetime | None = _ts()
    last_error: str | None = None
    tiktok_log_id: str | None = None
    uploaded_at: datetime | None = _ts()
    created_at: datetime = _ts(nullable=False, default=True)
    finished_at: datetime | None = _ts()


class Alert(SQLModel, table=True):
    __table_args__ = (
        Index(
            "ux_alert_dedupe_unread",
            "dedupe_key",
            unique=True,
            postgresql_where=text("read_at IS NULL AND dedupe_key IS NOT NULL"),
        ),
    )
    id: int | None = Field(default=None, primary_key=True)
    kind: AlertKind = _enum(None)
    target_id: int | None = _fk("target.id", "SET NULL", nullable=True, index=False)
    job_id: int | None = _fk("job.id", "SET NULL", nullable=True, index=False)
    message: str
    payload: dict[str, Any] = _jsonb({})
    dedupe_key: str | None = None
    read_at: datetime | None = _ts(index=True)
    created_at: datetime = _ts(nullable=False, default=True)


class Event(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    job_id: int | None = _fk("job.id", "CASCADE", nullable=True)
    video_id: int | None = _fk("video.id", "CASCADE", nullable=True)
    ts: datetime = _ts(nullable=False, default=True)
    level: str = "INFO"
    message: str
    payload: dict[str, Any] = _jsonb({})


class AppSetting(SQLModel, table=True):
    __tablename__ = "app_setting"
    key: str = Field(primary_key=True)
    value: Any = Field(sa_column=Column(JSONB, nullable=False))


class WorkerStatus(SQLModel, table=True):
    """Single row (id=1) written by the worker; read by /api/health."""

    __tablename__ = "worker_status"
    id: int = Field(default=1, primary_key=True)
    heartbeat_at: datetime | None = _ts()
    ytdlp_version: str | None = None
    staging_bytes: int = Field(
        default=0, sa_column=Column(BigInteger, nullable=False, default=0, server_default="0")
    )
    youtube_backoff_until: datetime | None = _ts()
    started_at: datetime | None = _ts()
    # Circuit breaker for YouTube's "confirm you're not a bot": every download stops at the
    # first one so the account behind the cookies isn't hammered. Cleared by the operator,
    # or automatically when the worker starts with different cookies/proxy.
    downloads_paused_reason: str | None = None
    downloads_paused_at: datetime | None = _ts()
    paused_config_fp: str | None = None
