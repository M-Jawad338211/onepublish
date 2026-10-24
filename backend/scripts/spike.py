"""Phase-1 spike: one Short → one TikTok inbox draft, outside the worker loop.

Connect the sandbox account first (web UI → Targets → Connect TikTok), then:

    uv run python scripts/spike.py --target-id 1 --video <youtube id>
    uv run python scripts/spike.py --target-id 1 --channel https://www.youtube.com/@you

It downloads the Short, uploads it to the target's inbox, polls until TikTok reports a
final state, prints the caption to paste, and deletes the file. Nothing is written to the
job tables, so it never interferes with the worker.
"""

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.db import dispose_engine, session_factory  # noqa: E402
from app.services import media, youtube  # noqa: E402
from app.services.caption import build_caption  # noqa: E402
from app.services.chunking import plan_chunks  # noqa: E402
from app.services.downloader import download_short, write_cookies  # noqa: E402
from app.services.tiktok import STATUS_PROCESSING, TikTokClient  # noqa: E402
from app.worker.tokens import access_token_for  # noqa: E402


async def latest_short(channel_url: str) -> str:
    info = await youtube.resolve_channel(channel_url)
    async with youtube.feed_client() as http:
        entries = await youtube.fetch_shorts_feed(youtube.shorts_playlist_id(info.channel_id), http)
    if not entries:
        sys.exit(f"{info.title} has no Shorts in its feed")
    print(f"Channel {info.title} ({info.channel_id}); newest Short: {entries[0].title}")
    return entries[0].video_id


async def main(args: argparse.Namespace) -> None:
    settings = get_settings()
    write_cookies(settings)
    video_id = args.video or await latest_short(args.channel)

    with tempfile.TemporaryDirectory() as tmp:
        print(f"Downloading {video_id} …")
        result = await asyncio.to_thread(download_short, video_id, settings, Path(tmp))
        path, probe = await media.ensure_tiktok_compatible(result.path)
        print(
            f"  {probe.width}x{probe.height} {probe.vcodec} {probe.fps:.0f} fps "
            f"{probe.duration_s:.0f}s {probe.size / 1e6:.1f} MB"
        )
        caption = build_caption(result.title, result.description, result.tags)

        tiktok = TikTokClient(settings.tiktok_client_key, settings.tiktok_client_secret)
        try:
            async with session_factory()() as session:
                token = await access_token_for(session, tiktok, args.target_id)
            plan = plan_chunks(probe.size)
            init = await tiktok.init_inbox_upload(token, plan)
            print(
                f"Init ok: publish_id={init.publish_id} chunks={plan.total_chunks} "
                f"log_id={init.log_id}"
            )
            with path.open("rb") as f:
                for i in range(plan.total_chunks):
                    start, end = plan.byte_range(i)
                    f.seek(start)
                    done = await tiktok.put_chunk(init.upload_url, plan, i, f.read(end - start + 1))
                    print(f"  chunk {i + 1}/{plan.total_chunks} → {'201' if done else '206'}")
            for _ in range(60):
                status = await tiktok.fetch_status(token, init.publish_id)
                print(f"  status: {status.status} {status.fail_reason or ''}")
                if status.status not in STATUS_PROCESSING:
                    break
                await asyncio.sleep(10)
        finally:
            await tiktok.aclose()
            await dispose_engine()

    print("\n--- caption to paste ---\n" + caption + "\n------------------------")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--target-id", type=int, required=True)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--video", help="YouTube video ID of a Short")
    g.add_argument("--channel", help="channel URL; uses its newest Short")
    asyncio.run(main(p.parse_args()))
