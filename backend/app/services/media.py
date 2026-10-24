"""ffprobe validation against TikTok's limits and the cheapest fix (FR-13).

Limits: MP4/MOV/WebM; H.264/H.265/VP8/VP9; 23–60 fps; 360–4096 px per side; ≤ 4 GB;
≤ 10 min. Remux (-c copy) is the default; re-encode only for codec or fps problems.
"""

import asyncio
import json
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from app.services.chunking import MAX_FILE

ALLOWED_VCODECS = {"h264", "hevc", "vp8", "vp9"}
MIN_FPS, MAX_FPS = 23.0, 60.0
MIN_SIDE, MAX_SIDE = 360, 4096
MAX_DURATION_S = 600.0


class MediaInvalid(Exception):
    """Out of spec and not cheaply fixable: the video is skipped with this reason."""


@dataclass
class Probe:
    vcodec: str
    width: int
    height: int
    fps: float
    duration_s: float
    size: int
    format_name: str


async def _run(*args: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"{args[0]} failed: {err.decode(errors='replace')[-500:]}")
    return out.decode()


def _fps(rate: str | None) -> float:
    if not rate or rate == "0/0":
        return 0.0
    return float(Fraction(rate))


def parse_probe(raw: str, size: int) -> Probe:
    data = json.loads(raw)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if video is None:
        raise MediaInvalid("no video stream")
    fmt = data.get("format", {})
    return Probe(
        vcodec=video.get("codec_name", ""),
        width=int(video.get("width", 0)),
        height=int(video.get("height", 0)),
        fps=_fps(video.get("avg_frame_rate")) or _fps(video.get("r_frame_rate")),
        duration_s=float(fmt.get("duration") or video.get("duration") or 0),
        size=size,
        format_name=fmt.get("format_name", ""),
    )


async def probe(path: Path) -> Probe:
    raw = await _run(
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(path),
    )
    return parse_probe(raw, path.stat().st_size)


def check(p: Probe) -> tuple[bool, float | None]:
    """Raises MediaInvalid for unfixable files. Returns (needs_reencode, target_fps)."""
    if p.size > MAX_FILE:
        raise MediaInvalid("file larger than 4 GB")
    if p.duration_s > MAX_DURATION_S:
        raise MediaInvalid(f"longer than {int(MAX_DURATION_S // 60)} min")
    if not (MIN_SIDE <= p.width <= MAX_SIDE and MIN_SIDE <= p.height <= MAX_SIDE):
        raise MediaInvalid(f"resolution {p.width}x{p.height} outside 360–4096 px")
    target_fps = None
    if p.fps and p.fps > MAX_FPS:
        target_fps = MAX_FPS
    elif p.fps and p.fps < MIN_FPS:
        target_fps = 30.0
    return (p.vcodec not in ALLOWED_VCODECS or target_fps is not None), target_fps


async def ensure_tiktok_compatible(path: Path) -> tuple[Path, Probe]:
    """Returns the (possibly new) MP4 path and its probe. Deletes the original if replaced."""
    p = await probe(path)
    reencode, target_fps = check(p)
    is_mp4 = path.suffix.lower() == ".mp4" and "mp4" in p.format_name
    if not reencode and is_mp4:
        return path, p

    out = path.with_name(path.stem + ".tt.mp4")
    if reencode:
        args = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
        if target_fps:
            args += ["-r", str(target_fps)]
        args += ["-c:a", "aac", "-b:a", "128k"]
    else:
        args = ["-c", "copy"]
    await _run(
        "ffmpeg", "-y", "-v", "error", "-i", str(path), *args, "-movflags", "+faststart", str(out)
    )
    path.unlink(missing_ok=True)
    return out, await probe(out)
