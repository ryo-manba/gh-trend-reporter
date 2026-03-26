"""レート制限管理"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field


@dataclass
class RateLimiter:
    """トークンバケット方式のレート制限"""

    max_requests_per_minute: int = 10
    max_requests_per_day: int = 250
    _minute_timestamps: list[float] = field(default_factory=list)
    _day_timestamps: list[float] = field(default_factory=list)

    def _cleanup(self) -> None:
        now = time.monotonic()
        self._minute_timestamps = [
            t for t in self._minute_timestamps if now - t < 60.0
        ]
        self._day_timestamps = [
            t for t in self._day_timestamps if now - t < 86400.0
        ]

    @property
    def remaining_per_minute(self) -> int:
        self._cleanup()
        return max(0, self.max_requests_per_minute - len(self._minute_timestamps))

    @property
    def remaining_per_day(self) -> int:
        self._cleanup()
        return max(0, self.max_requests_per_day - len(self._day_timestamps))

    async def acquire(self) -> None:
        """リクエスト枠を取得する。制限に達していたら待機する。"""
        while True:
            self._cleanup()

            if len(self._day_timestamps) >= self.max_requests_per_day:
                oldest = self._day_timestamps[0]
                wait = 86400.0 - (time.monotonic() - oldest)
                raise RuntimeError(
                    f"Daily rate limit ({self.max_requests_per_day}) exhausted. "
                    f"Resets in {wait:.0f}s"
                )

            if len(self._minute_timestamps) >= self.max_requests_per_minute:
                oldest = self._minute_timestamps[0]
                wait = 60.0 - (time.monotonic() - oldest) + 0.1
                await asyncio.sleep(wait)
                continue

            now = time.monotonic()
            self._minute_timestamps.append(now)
            self._day_timestamps.append(now)
            return
