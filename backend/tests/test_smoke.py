"""Real-network check that the pinned yt-dlp still reads YouTube Shorts.

Runs in CI on every PR (and gates Dependabot auto-merge): `pytest -m smoke`.
SMOKE_CHANNEL_ID can point it at another channel that posts Shorts.
"""

import os

import pytest
import yt_dlp

from app.services import youtube
from app.services.downloader import FORMAT

pytestmark = pytest.mark.smoke

# YouTube's own channel; it posts Shorts regularly.
CHANNEL_ID = os.environ.get("SMOKE_CHANNEL_ID", "UCBR8-60-B28hp2BmDPdntcQ")


async def test_shorts_feed_and_metadata_extraction():
    async with youtube.feed_client() as http:
        entries = await youtube.fetch_shorts_feed(youtube.shorts_playlist_id(CHANNEL_ID), http)
    assert entries, "Shorts feed returned no entries"

    opts = {"quiet": True, "no_warnings": True, "format": FORMAT, "noplaylist": True}
    if os.environ.get("YTDLP_COOKIES_FILE"):
        opts["cookiefile"] = os.environ["YTDLP_COOKIES_FILE"]
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(
            f"https://www.youtube.com/shorts/{entries[0].video_id}", download=False
        )
    assert info["id"] == entries[0].video_id
    assert info.get("title")
    assert info.get("requested_formats") or info.get("url"), "no downloadable format selected"
