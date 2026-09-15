"""Single-instance guard for the polling bot.

architecture.md: "Satu instance bot memakai file lock atau mekanisme host
setara; dua instance polling bersamaan tidak didukung." A non-blocking OS file
lock is used so a second process fails fast instead of silently double-polling.
"""
from __future__ import annotations

import os
from pathlib import Path
from types import TracebackType
from typing import Self

LOCK_BYTES = 1


class InstanceLockError(RuntimeError):
    """Raised when another bot instance already holds the lock."""


class SingleInstanceLock:
    """Non-blocking exclusive lock over a small file."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle: object | None = None

    @property
    def path(self) -> Path:
        """Return the lock file path."""
        return self._path

    def acquire(self) -> None:
        """Take the lock, or raise :class:`InstanceLockError` if already held."""
        if self._handle is not None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(  # noqa: SIM115 - the handle IS the lock and must outlive this method
            self._path, "a+", encoding="utf-8"
        )
        try:
            self._lock_handle(handle)
        except OSError as exc:
            handle.close()
            raise InstanceLockError(
                "another bot instance is already running"
            ) from exc
        self._handle = handle

    def release(self) -> None:
        """Release the lock if this instance holds it."""
        handle = self._handle
        if handle is None:
            return
        try:
            self._unlock_handle(handle)
        finally:
            handle.close()
            self._handle = None

    def __enter__(self) -> Self:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()

    def _lock_handle(self, handle) -> None:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, LOCK_BYTES)
            return
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock_handle(self, handle) -> None:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, LOCK_BYTES)
            return
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
