from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://onepublish:onepublish@localhost:5432/onepublish"

    # 32 random bytes, base64. Encrypts TikTok tokens at rest (NFR-4).
    token_enc_key: str = ""
    session_secret: str = ""
    # argon2 hash of the single admin password; see scripts/gen_secrets.py --password
    admin_password_hash: str = ""
    session_max_age_s: int = 14 * 24 * 3600
    cookie_secure: bool = True

    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""
    tiktok_redirect_uri: str = ""
    # TikTok documents PKCE (hex SHA-256 challenge) for Login Kit; turn off if web rejects it.
    tiktok_use_pkce: bool = True
    public_web_url: str = "http://localhost:3000"

    staging_dir: Path = Path("/data/staging")
    staging_cap_gb: float = 5.0

    pot_provider_url: str = "http://localhost:4416"
    ytdlp_cookies_b64: str = ""
    ytdlp_cookies_path: Path = Path("/data/cookies.txt")
    ytdlp_proxy: str = ""
    # Full yt-dlp debug output in the worker logs (cookies, PO tokens, JS runtime).
    ytdlp_verbose: bool = False

    worker_heartbeat_s: int = 30
    log_level: str = "INFO"
    port: int = Field(default=8000)

    @field_validator("database_url")
    @classmethod
    def _asyncpg_driver(cls, v: str) -> str:
        # Railway hands out postgres:// / postgresql:// URLs; the app needs asyncpg.
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+asyncpg://" + v[len(prefix) :]
        return v

    @property
    def staging_cap_bytes(self) -> int:
        return int(self.staging_cap_gb * 1024**3)


@lru_cache
def get_settings() -> Settings:
    return Settings()
