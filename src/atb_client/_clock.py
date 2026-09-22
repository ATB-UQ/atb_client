"""Time, behind one seam so tests can run a fake clock.

The sync driver sleeps with :func:`time.sleep` (looked up at call time, so patching
``time.sleep`` works); the async driver awaits :func:`async_sleep`. Deadlines are
measured with :func:`monotonic`.
"""

from __future__ import annotations

import asyncio
import time


def monotonic() -> float:
    return time.monotonic()


def sleep(seconds: float) -> None:
    time.sleep(seconds)


async def async_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)
