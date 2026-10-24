"""Pure-function tests: chunking, quota, crypto, YouTube parsing, media checks, error mapping."""

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest

from app import crypto
from app.services import media
from app.services.chunking import MB, plan_chunks
from app.services.downloader import BotCheck, DownloadError, SkipVideo, classify
from app.services.youtube import (
    YouTubeError,
    normalize_channel_url,
    parse_channel_page,
    parse_feed,
    shorts_playlist_id,
)
from app.worker.quota import quota_state

CHANNEL = "UC" + "a" * 22


# --- chunking -------------------------------------------------------------------


@pytest.mark.parametrize("size", [1, 4 * MB, 5 * MB, 64 * MB])
def test_small_files_are_one_chunk(size):
    plan = plan_chunks(size)
    assert (plan.chunk_size, plan.total_chunks) == (size, 1)
    assert plan.byte_range(0) == (0, size - 1)


def test_large_file_last_chunk_takes_remainder():
    size = 150 * MB + 123
    plan = plan_chunks(size)
    assert plan.chunk_size == 10 * MB
    assert plan.total_chunks == 15
    assert plan.byte_range(0) == (0, 10 * MB - 1)
    start, end = plan.byte_range(14)
    assert start == 140 * MB and end == size - 1
    covered = sum(e - s + 1 for s, e in map(plan.byte_range, range(plan.total_chunks)))
    assert covered == size


def test_chunking_rejects_bad_sizes():
    with pytest.raises(ValueError):
        plan_chunks(0)
    with pytest.raises(ValueError):
        plan_chunks(5 * 1024 * MB)


# --- quota ----------------------------------------------------------------------


def test_quota_free_under_cap():
    now = datetime(2026, 10, 24, 12, tzinfo=UTC)
    q = quota_state([now - timedelta(hours=h) for h in (1, 2, 3, 4)], now)
    assert q.available and q.used == 4 and q.next_slot_at is None


def test_quota_full_reports_next_slot():
    now = datetime(2026, 10, 24, 12, tzinfo=UTC)
    uploads = [now - timedelta(hours=h) for h in (1, 2, 3, 4, 20)]
    q = quota_state(uploads, now)
    assert not q.available
    assert q.next_slot_at == now - timedelta(hours=20) + timedelta(hours=24)


def test_quota_ignores_old_uploads():
    now = datetime(2026, 10, 24, 12, tzinfo=UTC)
    q = quota_state([now - timedelta(hours=25)] * 10, now)
    assert q.available and q.used == 0


# --- crypto ---------------------------------------------------------------------


def test_crypto_round_trip_and_nonce():
    a, b = crypto.encrypt("secret-token"), crypto.encrypt("secret-token")
    assert a != b
    assert crypto.decrypt(a) == "secret-token"


def test_crypto_rejects_bad_key():
    with pytest.raises(crypto.CryptoError):
        crypto.encrypt("x", key=base64.b64encode(b"short").decode())


# --- YouTube --------------------------------------------------------------------


def test_uush_playlist_id():
    assert shorts_playlist_id(CHANNEL) == "UUSH" + "a" * 22
    with pytest.raises(ValueError):
        shorts_playlist_id("UUxyz")


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.youtube.com/@MyChan", ("https://www.youtube.com/@MyChan", None, "@MyChan")),
        ("youtube.com/@MyChan/shorts", ("https://www.youtube.com/@MyChan", None, "@MyChan")),
        (
            f"https://m.youtube.com/channel/{CHANNEL}",
            (f"https://www.youtube.com/channel/{CHANNEL}", CHANNEL, None),
        ),
        ("https://www.youtube.com/c/Name", ("https://www.youtube.com/c/Name", None, None)),
        (
            "https://www.youtube.com/user/Name/videos",
            ("https://www.youtube.com/user/Name", None, None),
        ),
    ],
)
def test_normalize_channel_url(url, expected):
    assert normalize_channel_url(url) == expected


@pytest.mark.parametrize(
    "url", ["https://vimeo.com/@x", "https://www.youtube.com/", "https://www.youtube.com/watch?v=1"]
)
def test_normalize_rejects(url):
    with pytest.raises(YouTubeError):
        normalize_channel_url(url)


def test_parse_channel_page():
    page = (
        f'<meta property="og:title" content="Cooking &amp; Co">'
        f'<meta property="og:image" content="https://yt3.example/a.jpg">'
        f'<link rel="canonical" href="https://www.youtube.com/channel/{CHANNEL}">'
    )
    assert parse_channel_page(page) == (CHANNEL, "Cooking & Co", "https://yt3.example/a.jpg")


FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">
 <title>Shorts</title>
 <entry>
  <id>yt:video:abc123DEF45</id>
  <yt:videoId>abc123DEF45</yt:videoId>
  <title>First short</title>
  <published>2026-10-24T10:00:00+00:00</published>
  <media:group>
   <media:title>First short</media:title>
   <media:thumbnail url="https://i.ytimg.com/vi/abc123DEF45/hqdefault.jpg" width="480" height="360"/>
   <media:description>Hello #shorts</media:description>
  </media:group>
 </entry>
 <entry>
  <yt:videoId>zzz999yyy88</yt:videoId>
  <title>Second</title>
  <published>2026-10-23T09:00:00+00:00</published>
 </entry>
</feed>"""


def test_parse_feed():
    entries = parse_feed(FEED)
    assert [e.video_id for e in entries] == ["abc123DEF45", "zzz999yyy88"]
    first = entries[0]
    assert first.title == "First short"
    assert first.description == "Hello #shorts"
    assert first.published_at == datetime(2026, 10, 24, 10, tzinfo=UTC)
    assert first.thumbnail_url.endswith("hqdefault.jpg")
    assert entries[1].description == ""


# --- downloader error classes ------------------------------------------------------


@pytest.mark.parametrize(
    ("msg", "cls", "reason"),
    [
        ("ERROR: [youtube] x: Sign in to confirm you’re not a bot.", BotCheck, None),
        ("ERROR: Private video. Sign in if you've been granted access", SkipVideo, "private"),
        (
            "ERROR: Join this channel to get access to members-only content",
            SkipVideo,
            "members-only",
        ),
        ("ERROR: Sign in to confirm your age", SkipVideo, "age-restricted"),
        ("ERROR: Premieres in 3 hours", SkipVideo, "premiere not live yet"),
        ("ERROR: HTTP Error 500", DownloadError, None),
    ],
)
def test_classify_download_errors(msg, cls, reason):
    err = classify(msg)
    assert type(err) is cls
    if reason:
        assert str(err) == reason


# --- media checks ------------------------------------------------------------------


def _probe_json(codec="h264", w=1080, h=1920, fps="30/1", dur="45.0"):
    return json.dumps(
        {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": codec,
                    "width": w,
                    "height": h,
                    "avg_frame_rate": fps,
                },
                {"codec_type": "audio", "codec_name": "aac"},
            ],
            "format": {"duration": dur, "format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
        }
    )


def test_media_ok_needs_nothing():
    p = media.parse_probe(_probe_json(), 10 * MB)
    assert media.check(p) == (False, None)


def test_media_av1_needs_reencode():
    assert media.check(media.parse_probe(_probe_json(codec="av1"), MB)) == (True, None)


def test_media_high_fps_clamped():
    assert media.check(media.parse_probe(_probe_json(fps="120/1"), MB)) == (True, 60.0)


@pytest.mark.parametrize("kwargs", [{"w": 200}, {"h": 5000}, {"dur": "700"}])
def test_media_unfixable(kwargs):
    with pytest.raises(media.MediaInvalid):
        media.check(media.parse_probe(_probe_json(**kwargs), MB))
