"""Operator-editable settings kept in the app_setting table (env values are the defaults)."""

from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import get_settings
from app.models import AppSetting

EDITABLE = {"staging_cap_gb", "default_poll_interval_s"}


def defaults() -> dict[str, Any]:
    return {"staging_cap_gb": get_settings().staging_cap_gb, "default_poll_interval_s": 600}


async def load(session: AsyncSession) -> dict[str, Any]:
    values = defaults()
    rows = await session.exec(select(AppSetting))
    for row in rows:
        if row.key in EDITABLE:
            values[row.key] = row.value
    return values


async def save(session: AsyncSession, changes: dict[str, Any]) -> None:
    for key, value in changes.items():
        if key not in EDITABLE or value is None:
            continue
        stmt = insert(AppSetting).values(key=key, value=value)
        stmt = stmt.on_conflict_do_update(index_elements=["key"], set_={"value": value})
        await session.exec(stmt)  # type: ignore[call-overload]


async def staging_cap_bytes(session: AsyncSession) -> int:
    return int(float((await load(session))["staging_cap_gb"]) * 1024**3)
