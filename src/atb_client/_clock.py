"""Time, behind one seam so tests can run a fake clock.

The sync driver sleeps with :func:`time.sleep` (looked up at call time, so patching
``time.sleep`` works); the async driver awaits :func:`async_sleep`. Deadlines are
measured with :func:`monotonic`.
"""

from __future__ import annotations

import asyncio
import time


def monotonic() -> float:
    """Return a monotonic clock reading, in seconds."""
    return time.monotonic()


def sleep(seconds: float) -> None:
    """Block the calling thread for `seconds`."""
    time.sleep(seconds)


async def async_sleep(seconds: float) -> None:
    """Suspend the calling coroutine for `seconds`."""
    await asyncio.sleep(seconds)
