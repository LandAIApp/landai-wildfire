"""Bounded, ephemeral result cache with single-flight (no external store, nothing is persisted).

* ``get_or_compute`` returns a cached value, or runs ``compute`` ONCE even if several identical requests arrive at the
  same time (the others wait for the leader and share its result or its error).
* The cache holds at most ``max_items`` entries for ``ttl`` seconds and is lost whenever the Cloud Run instance
  restarts or scales to zero. Keys must contain EVERYTHING that influences the value (see ``fingerprint``).
"""
from __future__ import annotations

import hashlib
import json
import threading
from typing import Any, Callable

from .cache import TTLCache
from .errors import ServerBusyError


def fingerprint(*parts: Any) -> str:
    """Stable hash of the JSON-serialisable parts that define a computation (AOI, dates, parameters, versions...)."""
    raw = json.dumps(parts, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


class _Flight:
    def __init__(self) -> None:
        self.done = threading.Event()
        self.value: Any = None
        self.error: BaseException | None = None


class Memo:
    def __init__(self, max_items: int) -> None:
        self._cache = TTLCache(max_items=max(1, max_items))
        self._flights: dict[str, _Flight] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        return self._cache.get(key)

    def put(self, key: str, value: Any, ttl: float) -> None:
        self._cache.set(key, value, ttl)

    def clear(self) -> None:
        self._cache.clear()
        with self._lock:
            self._flights.clear()

    def get_or_compute(self, key: str, compute: Callable[[], Any], *, ttl: float = 0,
                       cacheable: Callable[[Any], bool] = lambda _v: True,
                       wait_seconds: float = 1500) -> tuple[Any, str]:
        """Return ``(value, how)`` with ``how`` in ``'hit' | 'shared' | 'computed'``."""
        hit = self._cache.get(key)
        if hit is not None:
            return hit, 'hit'
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None:
                return hit, 'hit'
            flight = self._flights.get(key)
            leader = flight is None
            if leader:
                flight = self._flights[key] = _Flight()
        if not leader:
            if not flight.done.wait(wait_seconds):
                raise ServerBusyError('An identical analysis is still running. Please retry in a minute.')
            if flight.error is not None:
                raise flight.error
            return flight.value, 'shared'
        try:
            value = compute()
            flight.value = value
            if ttl > 0 and cacheable(value):
                self._cache.set(key, value, ttl)
            return value, 'computed'
        except BaseException as exc:  # noqa: BLE001 - re-raised; followers get the same error
            flight.error = exc
            raise
        finally:
            with self._lock:
                self._flights.pop(key, None)
            flight.done.set()
