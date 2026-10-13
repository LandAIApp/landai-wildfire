"""Backend-issued, signed reference to a wildfire analysis.

The Exposure module never trusts a client-supplied burned-area polygon: it receives this opaque token,
verifies its HMAC and re-derives the footprint by re-running the validated wildfire graph with the
parameters that the BACKEND recorded when it issued the token. The token is stateless (Cloud Run may
scale to zero) and expires.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from ..core.config import get_settings
from ..core.errors import InvalidAnalysisRefError

_PROCESS_SECRET = secrets.token_bytes(32)
VERSION = 1


def _key() -> bytes:
    configured = get_settings().analysis_ref_secret
    return configured.encode('utf-8') if configured else _PROCESS_SECRET


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode('ascii').rstrip('=')


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def issue(payload: dict[str, Any], *, now: float | None = None) -> str:
    body = {'v': VERSION, 'iat': int(now if now is not None else time.time()), **payload}
    raw = json.dumps(body, separators=(',', ':'), sort_keys=True).encode('utf-8')
    signature = hmac.new(_key(), raw, hashlib.sha256).digest()
    return f'{_b64(raw)}.{_b64(signature)}'


def verify(token: str, *, now: float | None = None) -> dict[str, Any]:
    """Return the payload or raise InvalidAnalysisRefError (bad format, bad signature, expired)."""
    try:
        raw_part, sig_part = token.split('.', 1)
        raw, signature = _unb64(raw_part), _unb64(sig_part)
    except Exception as exc:  # noqa: BLE001
        raise InvalidAnalysisRefError('The analysis reference is malformed.') from exc
    expected = hmac.new(_key(), raw, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        raise InvalidAnalysisRefError(
            'The analysis reference is not valid for this server (signature mismatch). '
            'Run the wildfire analysis again.')
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise InvalidAnalysisRefError('The analysis reference is malformed.') from exc
    age = (now if now is not None else time.time()) - float(payload.get('iat', 0))
    if payload.get('v') != VERSION or age > get_settings().analysis_ref_ttl_seconds or age < -60:
        raise InvalidAnalysisRefError('The analysis reference has expired. Run the wildfire analysis again.')
    return payload
