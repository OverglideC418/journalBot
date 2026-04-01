from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo


class DailyScheduler:
    def __init__(self, callback, interval_seconds: int = 30) -> None:
        self.callback = callback
        self.interval_seconds = interval_seconds
        self.task: asyncio.Task | None = None

    def start(self) -> None:
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._run(), name="journalbot-daily-scheduler")

    async def _run(self) -> None:
        while True:
            await self.callback()
            await asyncio.sleep(self.interval_seconds)


def user_local_now(timezone_name: str) -> datetime:
    return datetime.now(ZoneInfo(timezone_name))


def parse_schedule_time(value: str) -> tuple[int, int]:
    hour_text, minute_text = value.split(":", maxsplit=1)
    hour = int(hour_text)
    minute = int(minute_text)
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("Time must be in HH:MM 24-hour format.")
    return hour, minute
