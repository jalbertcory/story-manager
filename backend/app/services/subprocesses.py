"""Bounded execution for external media tools (ffmpeg, ffprobe)."""

from __future__ import annotations

import asyncio
import os
from asyncio.subprocess import Process

# Media work here is stream copies, short clips, or probes, so even multi-GB
# audiobooks finish well within this; a hung ffmpeg would otherwise block its
# worker lane forever.
MEDIA_TOOL_TIMEOUT_SECONDS = float(os.getenv("STORY_MANAGER_MEDIA_TOOL_TIMEOUT_SECONDS", "3600"))


class MediaToolTimeout(TimeoutError):
    """An external tool exceeded its time limit and was killed."""


async def communicate_bounded(
    process: Process,
    *,
    description: str,
    timeout: float | None = None,
) -> tuple[bytes, bytes]:
    """Wait for a subprocess with a timeout, killing it on timeout or cancellation.

    Without this, a canceled job (pause, shutdown, lost lease) leaves the child
    running and still writing its output file.
    """
    limit = MEDIA_TOOL_TIMEOUT_SECONDS if timeout is None else timeout
    try:
        return await asyncio.wait_for(process.communicate(), timeout=limit)
    except BaseException as exc:
        if process.returncode is None:
            process.kill()
            await asyncio.shield(process.wait())
        if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
            raise MediaToolTimeout(f"{description} did not finish within {limit:.0f} seconds.") from exc
        raise
