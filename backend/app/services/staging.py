"""The staging folder is the only place media ever lives (SRS §3.8, NFR-3)."""

import logging
from pathlib import Path

log = logging.getLogger(__name__)

PAUSE_DOWNLOADS_AT = 0.8


def ensure(staging_dir: Path) -> Path:
    staging_dir.mkdir(parents=True, exist_ok=True)
    return staging_dir


def usage_bytes(staging_dir: Path) -> int:
    if not staging_dir.exists():
        return 0
    return sum(f.stat().st_size for f in staging_dir.rglob("*") if f.is_file())


def downloads_paused(staging_dir: Path, cap_bytes: int) -> bool:
    return usage_bytes(staging_dir) >= cap_bytes * PAUSE_DOWNLOADS_AT


def video_dir(staging_dir: Path, yt_video_id: str) -> Path:
    return staging_dir / yt_video_id


def delete_video_files(staging_dir: Path, yt_video_id: str, file_path: str | None) -> None:
    """Removes the file and its per-video folder (yt-dlp may leave .part/.ytdl leftovers)."""
    if file_path:
        Path(file_path).unlink(missing_ok=True)
    folder = video_dir(staging_dir, yt_video_id)
    if folder.exists():
        for f in folder.iterdir():
            f.unlink(missing_ok=True)
        folder.rmdir()


def remove_orphans(staging_dir: Path, known_ids: set[str]) -> int:
    """Deletes staging folders with no READY/DOWNLOADING video behind them."""
    removed = 0
    if not staging_dir.exists():
        return 0
    for folder in staging_dir.iterdir():
        if folder.is_dir() and folder.name not in known_ids:
            delete_video_files(staging_dir, folder.name, None)
            removed += 1
    return removed
