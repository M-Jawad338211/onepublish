"""In-app alerts (FR-42). A dedupe_key keeps one unread alert per condition."""

from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Alert, AlertKind, Event


async def raise_alert(
    session: AsyncSession,
    kind: AlertKind,
    message: str,
    *,
    target_id: int | None = None,
    job_id: int | None = None,
    payload: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
) -> None:
    stmt = insert(Alert).values(
        kind=kind,
        message=message,
        target_id=target_id,
        job_id=job_id,
        payload=payload or {},
        dedupe_key=dedupe_key,
    )
    if dedupe_key:
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["dedupe_key"],
            index_where=Alert.__table__.c.read_at.is_(None)
            & Alert.__table__.c.dedupe_key.is_not(None),
        )
    await session.exec(stmt)  # type: ignore[call-overload]


def log_event(
    session: AsyncSession,
    message: str,
    *,
    job_id: int | None = None,
    video_id: int | None = None,
    level: str = "INFO",
    payload: dict[str, Any] | None = None,
) -> None:
    session.add(
        Event(job_id=job_id, video_id=video_id, level=level, message=message, payload=payload or {})
    )
