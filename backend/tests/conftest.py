import base64
import os
import tempfile
from pathlib import Path

# Settings are cached on first use, so the test environment must be set before any app import.
_STAGING = Path(tempfile.mkdtemp(prefix="op-staging-"))
os.environ.update(
    {
        "DATABASE_URL": os.environ.get(
            "TEST_DATABASE_URL",
            "postgresql://onepublish:onepublish@localhost:5432/onepublish_test",
        ),
        "TOKEN_ENC_KEY": base64.b64encode(b"k" * 32).decode(),
        "SESSION_SECRET": "test-session-secret",
        "COOKIE_SECURE": "false",
        "TIKTOK_CLIENT_KEY": "ck",
        "TIKTOK_CLIENT_SECRET": "cs",
        "TIKTOK_REDIRECT_URI": "http://testserver/api/tiktok/callback",
        "PUBLIC_WEB_URL": "http://testserver",
        "STAGING_DIR": str(_STAGING),
        "YTDLP_COOKIES_PATH": str(_STAGING / "cookies.txt"),
    }
)

from argon2 import PasswordHasher  # noqa: E402

os.environ["ADMIN_PASSWORD_HASH"] = PasswordHasher().hash("hunter2")

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

import app.models  # noqa: E402, F401
from app.config import get_settings  # noqa: E402
from app.db import get_engine, session_factory  # noqa: E402

TABLES = ", ".join(SQLModel.metadata.tables)


@pytest.fixture
def staging_dir() -> Path:
    for f in sorted(_STAGING.rglob("*"), reverse=True):
        f.unlink() if f.is_file() else f.rmdir()
    return _STAGING


@pytest.fixture
async def db():
    """Empty tables (the schema comes from `alembic upgrade head` on the test DB)."""
    async with get_engine().begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    async with session_factory()() as session:
        yield session


@pytest.fixture
async def client(db):
    from app.api.main import create_app

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.fixture
async def authed(client):
    r = await client.post("/api/auth/login", json={"password": "hunter2"})
    assert r.status_code == 200
    return client


@pytest.fixture
def settings():
    return get_settings()
