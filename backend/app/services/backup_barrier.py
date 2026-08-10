"""Coordinate consistent backups with API writes and processing workers."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager


class BackupInProgressError(RuntimeError):
    """Raised when a new mutation arrives while a snapshot is being made."""


class BackupBarrier:
    """A process-local write barrier for the supported single-worker deployment."""

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._backup_active = False
        self._active_mutations = 0

    @property
    def backup_active(self) -> bool:
        return self._backup_active

    @asynccontextmanager
    async def mutation(self):
        async with self._condition:
            if self._backup_active:
                raise BackupInProgressError("A library backup is being created. Try again shortly.")
            self._active_mutations += 1
        try:
            yield
        finally:
            async with self._condition:
                self._active_mutations -= 1
                self._condition.notify_all()

    @asynccontextmanager
    async def backup(self):
        async with self._condition:
            if self._backup_active:
                raise BackupInProgressError("A library backup is already being created.")
            self._backup_active = True
            await self._condition.wait_for(lambda: self._active_mutations == 0)
        try:
            yield
        finally:
            async with self._condition:
                self._backup_active = False
                self._condition.notify_all()

    async def wait_until_writes_allowed(self) -> None:
        async with self._condition:
            await self._condition.wait_for(lambda: not self._backup_active)


backup_barrier = BackupBarrier()
