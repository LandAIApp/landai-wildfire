"""Concurrency gates: bound heavy work per kind ('exposure', 'overpass') to protect free-tier resources."""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

from .errors import ServerBusyError

_lock = threading.Lock()
_semaphores: dict[str, threading.BoundedSemaphore] = {}


def reset_gates() -> None:
    """Tests only."""
    with _lock:
        _semaphores.clear()


@contextmanager
def slot(name: str, limit: int, *, wait_seconds: float = 0, busy_message: str | None = None) -> Iterator[None]:
    """Acquire a named slot (non-blocking by default). Raises ServerBusyError when none is free."""
    with _lock:
        semaphore = _semaphores.setdefault(name, threading.BoundedSemaphore(max(1, limit)))
    acquired = semaphore.acquire(timeout=wait_seconds) if wait_seconds else semaphore.acquire(blocking=False)
    if not acquired:
        raise ServerBusyError(busy_message or 'The service is busy. Please retry in a minute.')
    try:
        yield
    finally:
        semaphore.release()
