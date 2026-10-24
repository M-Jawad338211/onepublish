"""Read-only YouTube access without OAuth (SRS §4.1).

- channel URL → canonical UC… ID, title and avatar, by reading the channel page once
  (yt-dlp is the fallback when the page markup doesn't yield an ID);
- the Shorts-only playlist is the channel ID with UC swapped for UUSH;
- new Shorts come from that playlist's public Atom feed.
"""

import asyncio
import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

import httpx

FEED_URL = "https://www.youtube.com/feeds/videos.xml"
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}
_CHANNEL_ID_RE = re.compile(r"^UC[\w-]{22}$")
# Skips the EU consent interstitial so the real channel page comes back.
_COOKIES = {"SOCS": "CAI", "CONSENT": "YES+1"}
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


class YouTubeError(Exception):
    pass


class YouTubeRateLimited(YouTubeError):
    """429/403 from YouTube: the poller backs off globally (FR-9)."""


@dataclass
class ChannelInfo:
    channel_id: str
    title: str
    handle: str | None
    url: str
    thumbnail_url: str | None


@dataclass
class FeedEntry:
    video_id: str
    title: str
    description: str
    published_at: datetime
    thumbnail_url: str | None


def shorts_playlist_id(channel_id: str) -> str:
    if not _CHANNEL_ID_RE.match(channel_id):
        raise ValueError(f"not a channel ID: {channel_id}")
    return "UUSH" + channel_id[2:]


def normalize_channel_url(url: str) -> tuple[str, str | None, str | None]:
    """Returns (canonical url, channel_id if present in the URL, @handle if present)."""
    url = url.strip()
    if not re.match(r"^https?://", url):
        url = "https://" + url.lstrip("/")
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.").removeprefix("m.")
    if host not in {"youtube.com", "music.youtube.com"}:
        raise YouTubeError("Not a youtube.com channel URL")
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        raise YouTubeError("URL has no channel path")
    first = parts[0]
    if first.startswith("@"):
        return f"https://www.youtube.com/{first}", None, first
    if first == "channel" and len(parts) > 1 and _CHANNEL_ID_RE.match(parts[1]):
        return f"https://www.youtube.com/channel/{parts[1]}", parts[1], None
    if first in {"c", "user"} and len(parts) > 1:
        return f"https://www.youtube.com/{first}/{parts[1]}", None, None
    raise YouTubeError("Use a /@handle, /channel/UC…, /c/name or /user/name URL")


def _meta(page: str, prop: str) -> str | None:
    m = re.search(rf'<meta\s+(?:property|name|itemprop)="{prop}"\s+content="([^"]*)"', page)
    return html.unescape(m.group(1)) if m else None


def parse_channel_page(page: str) -> tuple[str | None, str | None, str | None]:
    """(channel_id, title, thumbnail) from a channel page's HTML."""
    channel_id = None
    for pattern in (
        r'<meta\s+itemprop="(?:identifier|channelId)"\s+content="(UC[\w-]{22})"',
        r'<link\s+rel="canonical"\s+href="https://www\.youtube\.com/channel/(UC[\w-]{22})"',
        r'"externalId":"(UC[\w-]{22})"',
        r'"channelId":"(UC[\w-]{22})"',
    ):
        m = re.search(pattern, page)
        if m:
            channel_id = m.group(1)
            break
    return channel_id, _meta(page, "og:title"), _meta(page, "og:image")


async def resolve_channel(url: str, client: httpx.AsyncClient | None = None) -> ChannelInfo:
    canonical, channel_id, handle = normalize_channel_url(url)
    title = thumb = None
    own = client is None
    client = client or httpx.AsyncClient(timeout=20, headers=_HEADERS, cookies=_COOKIES)
    try:
        resp = await client.get(canonical, follow_redirects=True)
        if resp.status_code in (403, 429):
            raise YouTubeRateLimited(f"YouTube returned {resp.status_code}")
        if resp.status_code == 404:
            raise YouTubeError("Channel not found")
        if resp.is_success:
            page_id, title, thumb = parse_channel_page(resp.text)
            channel_id = channel_id or page_id
    finally:
        if own:
            await client.aclose()

    if not channel_id:
        channel_id, title = await asyncio.to_thread(_resolve_with_ytdlp, canonical)
    return ChannelInfo(
        channel_id=channel_id,
        title=title or handle or channel_id,
        handle=handle,
        url=canonical,
        thumbnail_url=thumb,
    )


def _resolve_with_ytdlp(url: str) -> tuple[str, str | None]:
    import yt_dlp

    opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "playlist_items": "0"}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False) or {}
    except yt_dlp.utils.DownloadError as e:
        raise YouTubeError(f"Could not resolve channel: {e}") from e
    channel_id = info.get("channel_id") or info.get("id")
    if not channel_id or not _CHANNEL_ID_RE.match(channel_id):
        raise YouTubeError("Could not find the channel ID for this URL")
    return channel_id, info.get("channel") or info.get("title")


def parse_feed(xml_text: str) -> list[FeedEntry]:
    root = ET.fromstring(xml_text)
    entries: list[FeedEntry] = []
    for e in root.findall("atom:entry", _NS):
        vid = e.findtext("yt:videoId", default="", namespaces=_NS)
        if not vid:
            continue
        group = e.find("media:group", _NS)
        description = ""
        thumb = None
        if group is not None:
            description = group.findtext("media:description", default="", namespaces=_NS)
            t = group.find("media:thumbnail", _NS)
            thumb = t.get("url") if t is not None else None
        published = e.findtext("atom:published", default="", namespaces=_NS)
        entries.append(
            FeedEntry(
                video_id=vid,
                title=e.findtext("atom:title", default="", namespaces=_NS),
                description=description,
                published_at=datetime.fromisoformat(published),
                thumbnail_url=thumb,
            )
        )
    return entries


async def fetch_shorts_feed(playlist_id: str, client: httpx.AsyncClient) -> list[FeedEntry]:
    resp = await client.get(FEED_URL, params={"playlist_id": playlist_id})
    if resp.status_code in (403, 429):
        raise YouTubeRateLimited(f"YouTube feed returned {resp.status_code}")
    if resp.status_code == 404:
        # A channel that has never posted a Short has no UUSH playlist yet.
        return []
    if not resp.is_success:
        raise YouTubeError(f"YouTube feed returned {resp.status_code}")
    return parse_feed(resp.text)


def feed_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=20, headers=_HEADERS, cookies=_COOKIES)


def thumbnail_for(video_id: str) -> str:
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
