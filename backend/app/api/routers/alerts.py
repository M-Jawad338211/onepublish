from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, update
from sqlmodel import col, select

from app.api.deps import SessionDep, require_admin
from app.db import utcnow
from app.models import Alert
from app.schemas import AlertOut, UnreadCount

router = APIRouter(prefix="/alerts", tags=["alerts"], dependencies=[Depends(require_admin)])


@router.get("", response_model=list[AlertOut])
async def list_alerts(
    session: SessionDep,
    unread: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[Alert]:
    stmt = select(Alert).order_by(col(Alert.id).desc()).limit(limit)
    if unread:
        stmt = stmt.where(col(Alert.read_at).is_(None))
    return list(await session.exec(stmt))


@router.get("/unread-count", response_model=UnreadCount)
async def unread_count(session: SessionDep) -> UnreadCount:
    n = (
        await session.exec(
            select(func.count()).select_from(Alert).where(col(Alert.read_at).is_(None))
        )
    ).one()
    return UnreadCount(unread=n)


@router.post("/{alert_id}/read", response_model=AlertOut)
async def mark_read(alert_id: int, session: SessionDep) -> Alert:
    alert = await session.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    alert.read_at = alert.read_at or utcnow()
    session.add(alert)
    await session.commit()
    await session.refresh(alert)
    return alert


@router.post("/read-all", response_model=UnreadCount)
async def mark_all_read(session: SessionDep) -> UnreadCount:
    await session.exec(  # type: ignore[call-overload]
        update(Alert).where(col(Alert.read_at).is_(None)).values(read_at=utcnow())
    )
    await session.commit()
    return UnreadCount(unread=0)
