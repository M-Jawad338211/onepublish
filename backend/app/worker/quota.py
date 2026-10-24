"""Inbox-draft cap: at most 5 uploads per target in any rolling 24 h window.

A slot frees up 24 h after the upload that used it.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

DAILY_UPLOAD_CAP = 5
WINDOW = timedelta(hours=24)


@dataclass(frozen=True)
class QuotaState:
    used: int
    cap: int
    next_slot_at: datetime | None  # None when a slot is free now

    @property
    def available(self) -> bool:
        return self.used < self.cap


def quota_state(
    uploaded_at: Iterable[datetime], now: datetime, cap: int = DAILY_UPLOAD_CAP
) -> QuotaState:
    recent = sorted(t for t in uploaded_at if t > now - WINDOW)
    if len(recent) < cap:
        return QuotaState(len(recent), cap, None)
    # The (used - cap + 1)th oldest upload must age out before a slot opens.
    return QuotaState(len(recent), cap, recent[len(recent) - cap] + WINDOW)
