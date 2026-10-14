"""Live processing stages of a long request (in memory, per instance, bounded and short-lived).

The client sends a random ``progress_id`` with the heavy request and polls ``GET /api/v1/progress/{id}`` while it runs.
Only stage names, states, durations and counters are stored (never data, credentials or geometries). Nothing here
estimates a percentage: a stage is pending, running, done, cached, skipped or failed. With several Cloud Run instances
a poll can reach another instance and find nothing; the client must treat "unknown" as "no detail available".
"""
from __future__ import annotations

import re
import threading
import time
from typing import Any

from .cache import TTLCache
from .config import get_settings

ID_RE = re.compile(r'^[A-Za-z0-9_-]{16,64}$')
_registry = TTLCache(max_items=64)
_STATES = ('pending', 'running', 'done', 'cached', 'skipped', 'failed')


class Progress:
    def __init__(self, stages: list[str]) -> None:
        self._lock = threading.Lock()
        self._started = time.monotonic()
        self._finished: float | None = None
        self._order = list(stages)
        self._stages: dict[str, dict[str, Any]] = {
            k: {'state': 'pending', 'started': None, 'seconds': None, 'detail': {}} for k in stages}

    def start(self, key: str, **detail: Any) -> None:
        with self._lock:
            st = self._stages.get(key)
            if st is None:
                return
            st.update(state='running', started=time.monotonic())
            st['detail'].update(detail)

    def update(self, key: str, **detail: Any) -> None:
        with self._lock:
            if key in self._stages:
                self._stages[key]['detail'].update(detail)

    def finish(self, key: str, state: str = 'done', **detail: Any) -> None:
        if state not in _STATES:
            state = 'done'
        with self._lock:
            st = self._stages.get(key)
            if st is None:
                return
            if st['started'] is not None:
                st['seconds'] = round(time.monotonic() - st['started'], 1)
            st['state'] = state
            st['detail'].update(detail)

    def close(self) -> None:
        with self._lock:
            self._finished = time.monotonic()
            for st in self._stages.values():       # a stage left running is reported as failed, never as done
                if st['state'] == 'running':
                    st['state'] = 'failed'
                    if st['started'] is not None:
                        st['seconds'] = round(self._finished - st['started'], 1)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            now = self._finished if self._finished is not None else time.monotonic()
            stages = []
            for key in self._order:
                st = self._stages[key]
                seconds = st['seconds']
                if st['state'] == 'running' and st['started'] is not None:
                    seconds = round(now - st['started'], 1)
                stages.append({'key': key, 'state': st['state'], 'seconds': seconds, 'detail': dict(st['detail'])})
            return {'elapsed_s': round(now - self._started, 1), 'finished': self._finished is not None,
                    'stages': stages}


class NullProgress(Progress):
    """No-op reporter used when the client did not ask for progress."""

    def __init__(self) -> None:
        super().__init__([])


def begin(progress_id: str | None, stages: list[str]) -> Progress:
    if not progress_id or not ID_RE.match(progress_id):
        return NullProgress()
    tracker = Progress(stages)
    _registry.set(progress_id, tracker, get_settings().progress_ttl_seconds)
    return tracker


def snapshot(progress_id: str) -> dict[str, Any] | None:
    if not ID_RE.match(progress_id):
        return None
    tracker = _registry.get(progress_id)
    return tracker.snapshot() if tracker is not None else None


def clear() -> None:
    _registry.clear()
