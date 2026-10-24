"""yt-dlp used as a library (SRS §3.3). Runs in a worker thread; never shells out."""

import base64
import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yt_dlp

from app.config import Settings

log = logging.getLogger(__name__)

# Prefer H.264 in MP4 (TikTok rejects AV1); fall back to any MP4 and let media.py fix it.
FORMAT = (
    "bv*[ext=mp4][vcodec^=avc1][height<=1080]+ba[ext=m4a]"
    "/bv*[ext=mp4][height<=1080]+ba[ext=m4a]"
    "/b[ext=mp4][height<=1080]/b[ext=mp4]"
)

_SKIP_MARKERS = {
    "private video": "private",
    "members-only": "members-only",
    "join this channel": "members-only",
    "sign in to confirm your age": "age-restricted",
    "age-restricted": "age-restricted",
    "not available in your country": "geo-blocked",
    "blocked it in your country": "geo-blocked",
    "premieres in": "premiere not live yet",
    "this live event will begin": "premiere not live yet",
    "video unavailable": "unavailable",
    "this video has been removed": "removed",
}
_BOT_MARKERS = ("confirm you're not a bot", "confirm you’re not a bot")


class DownloadError(Exception):
    pass


class SkipVideo(DownloadError):
    """Not downloadable by design (FR-8): record SKIPPED with this reason, never retry."""


class BotCheck(DownloadError):
    """YouTube's "Sign in to confirm you're not a bot" (FR-15): alert, don't loop."""


@dataclass
class DownloadResult:
    path: Path
    title: str
    description: str
    tags: list[str]
    duration_s: float | None
    width: int | None
    height: int | None
    fps: float | None
    published_at: datetime | None


def write_cookies(settings: Settings) -> Path | None:
    """Writes YTDLP_COOKIES_B64 to disk. Called before every download: yt-dlp saves the
    jar back when it finishes, and once YouTube rejects the cookies that saved copy has
    lost its login cookies, so it must never be reused."""
    if not settings.ytdlp_cookies_b64:
        return None
    path = settings.ytdlp_cookies_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(settings.ytdlp_cookies_b64))
    path.chmod(0o600)
    return path


def config_fingerprint(settings: Settings) -> str:
    """Changes whenever the cookies or proxy change; used to lift a bot-check pause."""
    raw = f"{settings.ytdlp_cookies_b64}|{settings.ytdlp_proxy}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def ydl_options(settings: Settings, out_dir: Path) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "format": FORMAT,
        "merge_output_format": "mp4",
        "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "retries": 3,
        "socket_timeout": 30,
        "overwrites": True,
        "extractor_args": {"youtubepot-bgutilhttp": {"base_url": [settings.pot_provider_url]}},
    }
    if settings.ytdlp_cookies_path.exists():
        opts["cookiefile"] = str(settings.ytdlp_cookies_path)
    if settings.ytdlp_proxy:
        opts["proxy"] = settings.ytdlp_proxy
    if settings.ytdlp_verbose:
        opts |= {"quiet": False, "no_warnings": False, "verbose": True}
    return opts


def classify(message: str) -> DownloadError:
    low = message.lower()
    if any(m in low for m in _BOT_MARKERS):
        return BotCheck(message)
    for marker, reason in _SKIP_MARKERS.items():
        if marker in low:
            return SkipVideo(reason)
    return DownloadError(message)


def _check_availability(info: dict[str, Any]) -> None:
    availability = info.get("availability")
    if availability and availability != "public":
        raise SkipVideo(availability.replace("_", "-"))
    if info.get("live_status") in ("is_upcoming", "is_live"):
        raise SkipVideo("premiere not live yet")


def download_short(video_id: str, settings: Settings, out_dir: Path) -> DownloadResult:
    """Blocking. Call through asyncio.to_thread."""
    out_dir.mkdir(parents=True, exist_ok=True)
    write_cookies(settings)
    url = f"https://www.youtube.com/shorts/{video_id}"
    try:
        with yt_dlp.YoutubeDL(ydl_options(settings, out_dir)) as ydl:
            info = ydl.extract_info(url, download=False)
            if info is None:
                raise DownloadError("yt-dlp returned no info")
            _check_availability(info)
            info = ydl.process_ie_result(info, download=True)
    except yt_dlp.utils.DownloadError as e:
        raise classify(str(e)) from e

    downloads = info.get("requested_downloads") or []
    path = Path(downloads[0]["filepath"]) if downloads else out_dir / f"{video_id}.mp4"
    if not path.exists():
        raise DownloadError(f"download finished but {path.name} is missing")

    ts = info.get("timestamp")
    published = datetime.fromtimestamp(ts, UTC) if ts else None
    return DownloadResult(
        path=path,
        title=info.get("title") or "",
        description=info.get("description") or "",
        tags=list(info.get("tags") or []),
        duration_s=info.get("duration"),
        width=info.get("width"),
        height=info.get("height"),
        fps=info.get("fps"),
        published_at=published,
    )


def ytdlp_version() -> str:
    return yt_dlp.version.__version__
