"""Gemini API 向けスライディングウィンドウ方式のレート制限管理.

Gemini 無料枠の制約（10 RPM / 250 RPD）を遵守するため、
分単位・日単位のリクエストタイムスタンプを追跡し、
上限到達時に自動待機または例外送出を行う。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field


@dataclass
class RateLimiter:
    """スライディングウィンドウ方式のレート制限.

    分単位のウィンドウでは上限到達時に自動的に ``asyncio.sleep`` で待機し、
    日単位のウィンドウでは上限到達時に ``RuntimeError`` を送出する。

    Attributes:
        max_requests_per_minute: 1 分あたりの最大リクエスト数。
        max_requests_per_day: 1 日あたりの最大リクエスト数。
    """

    max_requests_per_minute: int = 10
    max_requests_per_day: int = 250
    _minute_timestamps: list[float] = field(default_factory=list)
    _day_timestamps: list[float] = field(default_factory=list)

    def _cleanup(self) -> None:
        """ウィンドウ外の古いタイムスタンプを除去する。"""
        now = time.monotonic()
        self._minute_timestamps = [t for t in self._minute_timestamps if now - t < 60.0]
        self._day_timestamps = [t for t in self._day_timestamps if now - t < 86400.0]

    @property
    def remaining_per_minute(self) -> int:
        """現在のウィンドウ内で残りの分単位リクエスト枠数。"""
        self._cleanup()
        return max(0, self.max_requests_per_minute - len(self._minute_timestamps))

    @property
    def remaining_per_day(self) -> int:
        """現在のウィンドウ内で残りの日単位リクエスト枠数。"""
        self._cleanup()
        return max(0, self.max_requests_per_day - len(self._day_timestamps))

    async def acquire(self) -> None:
        """リクエスト枠を 1 つ確保する.

        分単位の制限に達している場合はウィンドウが回復するまで待機する。
        日単位の制限に達している場合は ``RuntimeError`` を送出する。

        Raises:
            RuntimeError: 日単位のレート制限を超過した場合。
        """
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
