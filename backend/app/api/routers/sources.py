from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import col, select

from app import settings_store
from app.api.deps import SessionDep, require_admin
from app.db import utcnow
from app.models import Source
from app.schemas import SourceCreate, SourceOut, SourceUpdate
from app.services import youtube

router = APIRouter(prefix="/sources", tags=["sources"], dependencies=[Depends(require_admin)])


async def _get(session: SessionDep, source_id: int) -> Source:
    source = await session.get(Source, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
    return source


@router.get("", response_model=list[SourceOut])
async def list_sources(session: SessionDep) -> list[Source]:
    return list(await session.exec(select(Source).order_by(col(Source.title))))


@router.post("", response_model=SourceOut, status_code=status.HTTP_201_CREATED)
async def create_source(body: SourceCreate, session: SessionDep) -> Source:
    try:
        info = await youtube.resolve_channel(body.url)
    except youtube.YouTubeRateLimited as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    except youtube.YouTubeError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

    existing = (
        await session.exec(select(Source).where(Source.channel_id == info.channel_id))
    ).first()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{existing.title} is already a source")

    interval = (
        body.poll_interval_s or (await settings_store.load(session))["default_poll_interval_s"]
    )
    source = Source(
        channel_id=info.channel_id,
        handle=info.handle,
        url=info.url,
        title=info.title,
        thumbnail_url=info.thumbnail_url,
        shorts_playlist_id=youtube.shorts_playlist_id(info.channel_id),
        poll_interval_s=int(interval),
        start_from=body.start_from,
        next_poll_at=utcnow(),
    )
    session.add(source)
    await session.commit()
    await session.refresh(source)
    return source


@router.get("/{source_id}", response_model=SourceOut)
async def get_source(source_id: int, session: SessionDep) -> Source:
    return await _get(session, source_id)


@router.patch("/{source_id}", response_model=SourceOut)
async def update_source(source_id: int, body: SourceUpdate, session: SessionDep) -> Source:
    source = await _get(session, source_id)
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(source, key, value)
    if "poll_interval_s" in changes or changes.get("status") == "ACTIVE":
        source.next_poll_at = utcnow()
    session.add(source)
    await session.commit()
    await session.refresh(source)
    return source


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(source_id: int, session: SessionDep) -> None:
    """Removes the source and its mappings; videos and jobs stay as history (FR-3)."""
    await session.delete(await _get(session, source_id))
    await session.commit()


@router.post("/{source_id}/check-now", response_model=SourceOut)
async def check_now(source_id: int, session: SessionDep) -> Source:
    """The worker polls any source whose next_poll_at has passed, within ~30 s."""
    source = await _get(session, source_id)
    source.next_poll_at = utcnow()
    session.add(source)
    await session.commit()
    await session.refresh(source)
    return source
