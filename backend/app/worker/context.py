import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field

import httpx

from app.config import Settings
from app.services.tiktok import TikTokClient


class RateLimiter:
    """At most `limit` events per `per` seconds, per key (TikTok: 6 inits/min per token)."""

    def __init__(self, limit: int, per: float):
        self.limit = limit
        self.per = per
        self._events: dict[int, deque[float]] = defaultdict(deque)

    def allow(self, key: int) -> bool:
        now = time.monotonic()
        q = self._events[key]
        while q and now - q[0] > self.per:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True


@dataclass
class WorkerContext:
    settings: Settings
    tiktok: TikTokClient
    feed_http: httpx.AsyncClient
    stopping: asyncio.Event = field(default_factory=asyncio.Event)
    init_limiter: RateLimiter = field(default_factory=lambda: RateLimiter(6, 60))
    # Doubles on each consecutive YouTube 429/403, resets on a clean poll (FR-9).
    youtube_backoff_s: int = 0
