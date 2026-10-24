from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from app.api.deps import SessionDep, require_admin
from app.models import Mapping, Source, Target, TargetStatus
from app.schemas import (
    CaptionPreviewIn,
    CaptionPreviewOut,
    MappingCreate,
    MappingOut,
    MappingUpdate,
)
from app.services.caption import CaptionOptions, build_caption, utf16_len

router = APIRouter(prefix="/mappings", tags=["mappings"], dependencies=[Depends(require_admin)])


def _clean_tags(tags: list[str]) -> list[str]:
    return [t.strip().lstrip("#") for t in tags if t.strip().lstrip("#")]


async def _get(session: SessionDep, mapping_id: int) -> Mapping:
    mapping = await session.get(Mapping, mapping_id)
    if mapping is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mapping not found")
    return mapping


@router.get("", response_model=list[MappingOut])
async def list_mappings(session: SessionDep) -> list[Mapping]:
    return list(await session.exec(select(Mapping).order_by(col(Mapping.id))))


@router.post("", response_model=MappingOut, status_code=status.HTTP_201_CREATED)
async def create_mapping(body: MappingCreate, session: SessionDep) -> Mapping:
    if await session.get(Source, body.source_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown source")
    target = await session.get(Target, body.target_id)
    if target is None or target.status == TargetStatus.DISCONNECTED:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown or disconnected target")
    data = body.model_dump()
    data["extra_tags"] = _clean_tags(body.extra_tags)
    data["strip_tags"] = _clean_tags(body.strip_tags)
    mapping = Mapping(**data)
    session.add(mapping)
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This source already feeds that target"
        ) from e
    await session.refresh(mapping)
    return mapping


@router.patch("/{mapping_id}", response_model=MappingOut)
async def update_mapping(mapping_id: int, body: MappingUpdate, session: SessionDep) -> Mapping:
    mapping = await _get(session, mapping_id)
    changes = body.model_dump(exclude_unset=True)
    for key in ("extra_tags", "strip_tags"):
        if changes.get(key) is not None:
            changes[key] = _clean_tags(changes[key])
    for key, value in changes.items():
        if value is None and key != "max_len":
            continue
        setattr(mapping, key, value)
    session.add(mapping)
    await session.commit()
    await session.refresh(mapping)
    return mapping


@router.delete("/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mapping(mapping_id: int, session: SessionDep) -> None:
    await session.delete(await _get(session, mapping_id))
    await session.commit()


@router.post("/caption-preview", response_model=CaptionPreviewOut)
async def caption_preview(body: CaptionPreviewIn) -> CaptionPreviewOut:
    caption = build_caption(
        body.title,
        body.description,
        body.tags,
        CaptionOptions(
            include_title=body.include_title,
            include_description=body.include_description,
            include_tags=body.include_tags,
            prefix=body.caption_prefix,
            suffix=body.caption_suffix,
            extra_tags=_clean_tags(body.extra_tags),
            strip_tags=_clean_tags(body.strip_tags),
            max_len=body.max_len,
        ),
    )
    return CaptionPreviewOut(caption=caption, length=utf16_len(caption))
