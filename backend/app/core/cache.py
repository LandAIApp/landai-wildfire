"""Tiny thread-safe in-memory TTL cache (no external store: keeps the prototype free to run)."""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Callable


class TTLCache:
    def __init__(self, max_items: int = 64, clock: Callable[[], float] = time.monotonic):
        self._items: OrderedDict[Any, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self._max = max_items
        self._clock = clock

    def get(self, key: Any) -> Any | None:
        with self._lock:
            hit = self._items.get(key)
            if hit is None:
                return None
            expires, value = hit
            if expires < self._clock():
                del self._items[key]
                return None
            self._items.move_to_end(key)
            return value

    def set(self, key: Any, value: Any, ttl_seconds: float) -> None:
        if ttl_seconds <= 0:
            return
        with self._lock:
            self._items[key] = (self._clock() + ttl_seconds, value)
            self._items.move_to_end(key)
            while len(self._items) > self._max:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
