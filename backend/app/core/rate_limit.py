"""SlowAPI limiter (in memory). Limits come from settings so ops can tune them without code changes.

Behind Cloud Run the direct peer is Google's proxy: with TRUST_FORWARDED_FOR=true the client IP is
read from X-Forwarded-For (entries to the left of the trusted hops are client-supplied and ignored).
"""
from __future__ import annotations

import time

from limits import parse_many
from slowapi import Limiter
from starlette.requests import Request

from .config import get_settings


def client_key(request: Request) -> str:
    settings = get_settings()
    if settings.trust_forwarded_for:
        parts = [p.strip() for p in request.headers.get('x-forwarded-for', '').split(',') if p.strip()]
        if parts:
            hops = max(1, settings.trusted_proxy_hops)
            return parts[-hops] if len(parts) >= hops else parts[0]
    return request.client.host if request.client else 'unknown'


limiter = Limiter(key_func=client_key, enabled=get_settings().rate_limit_enabled)


def analyze_limit() -> str:
    return get_settings().rate_limit_analyze


def exposure_limit() -> str:
    return get_settings().rate_limit_exposure


def describe_limits(spec: str) -> list[dict]:
    return [{'count': i.amount, 'per': i.GRANULARITY.name} for i in parse_many(spec)]


def retry_after_seconds(request: Request) -> int | None:
    view = getattr(request.state, 'view_rate_limit', None)
    if not view:
        return None
    try:
        reset_at, _ = limiter.limiter.get_window_stats(*view)
        return max(1, int(reset_at - time.time()) + 1)
    except Exception:  # noqa: BLE001 - best effort
        return None
