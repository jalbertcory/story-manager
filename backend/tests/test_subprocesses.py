"""Tests for bounded external tool execution."""

import asyncio
import sys

import pytest

from backend.app.services.subprocesses import MediaToolTimeout, communicate_bounded


async def _sleeper() -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import time; time.sleep(60)",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


@pytest.mark.asyncio
async def test_timeout_kills_the_process():
    process = await _sleeper()

    with pytest.raises(MediaToolTimeout, match="sleeper did not finish"):
        await communicate_bounded(process, description="sleeper", timeout=0.2)

    assert process.returncode is not None


@pytest.mark.asyncio
async def test_cancellation_kills_the_process():
    process = await _sleeper()
    task = asyncio.create_task(communicate_bounded(process, description="sleeper", timeout=60))
    await asyncio.sleep(0.2)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert process.returncode is not None


@pytest.mark.asyncio
async def test_completed_process_output_is_returned():
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "print('ok')",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, _stderr = await communicate_bounded(process, description="printer", timeout=30)

    assert stdout.strip() == b"ok"
