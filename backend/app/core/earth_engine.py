"""Earth Engine initialization and the single server->client evaluation helper."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import ee

from .config import BACKEND_DIR, REPO_ROOT, get_settings
from .errors import (
    EarthEngineAuthError, EarthEngineLimitError, EarthEngineQuotaError,
    EarthEngineServiceError, EarthEngineTimeoutError, WildfireError,
)

_lock = threading.Lock()
_state = {'initialized': False, 'error': None}


def _resolve_key_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    for base in (Path.cwd(), BACKEND_DIR, REPO_ROOT):
        candidate = base / path
        if candidate.exists():
            return candidate
    return path


def ensure_initialized() -> None:
    """Initialize Earth Engine once (service account if configured, else local login)."""
    if _state['initialized']:
        return
    with _lock:
        if _state['initialized']:
            return
        s = get_settings()
        try:
            if s.ee_private_key_path:
                key_path = _resolve_key_path(s.ee_private_key_path)
                if not key_path.exists():
                    raise FileNotFoundError(f'EE_PRIVATE_KEY_PATH not found: {s.ee_private_key_path}')
                key_data = json.loads(key_path.read_text(encoding='utf-8'))
                email = s.ee_service_account or key_data.get('client_email', '')
                project = s.ee_project or key_data.get('project_id') or None
                credentials = ee.ServiceAccountCredentials(email, str(key_path))
                ee.Initialize(credentials, project=project)
            else:
                ee.Initialize(project=s.ee_project or None)
        except Exception as exc:  # noqa: BLE001 - any init failure is an availability problem
            _state['error'] = f'{type(exc).__name__}: {exc}'
            raise EarthEngineAuthError(
                'Earth Engine could not be initialized. Check EE_PROJECT and credentials '
                '(EE_SERVICE_ACCOUNT / EE_PRIVATE_KEY_PATH, or run `earthengine authenticate`).',
                details=_state['error'][:500]) from exc
        _state['initialized'] = True
        _state['error'] = None


def status() -> dict[str, Any]:
    return {'initialized': _state['initialized'], 'last_error': _state['error']}


def map_ee_error(exc: Exception, what: str) -> WildfireError:
    text = str(exc)
    low = text.lower()
    short = text[:400]
    if 'timed out' in low or 'deadline' in low:
        return EarthEngineTimeoutError(
            f'Earth Engine timed out while {what}. Try a smaller municipality or a shorter period.',
            details=short)
    if any(k in low for k in ('memory limit', 'too many concurrent', 'too large', 'too many pixels')):
        return EarthEngineLimitError(
            f'Earth Engine computation limit reached while {what}. '
            'Try a smaller municipality or a shorter analysis period.', details=short)
    if 'quota' in low or 'too many requests' in low or 'rate limit' in low:
        return EarthEngineQuotaError(
            f'Earth Engine quota exceeded while {what}. Wait a moment and retry.', details=short)
    if 'permission' in low or 'not found' in low or 'does not exist' in low:
        return EarthEngineServiceError(
            f'Earth Engine could not access a required dataset/asset while {what}. '
            'Make sure the municipal asset is shared with the service account.', details=short)
    return EarthEngineServiceError(f'Earth Engine error while {what}.', details=short)


def evaluate(obj: Any, what: str = 'evaluating a request') -> Any:
    """Evaluate a small server-side object at the API boundary (getInfo)."""
    ensure_initialized()
    try:
        return obj.getInfo()
    except WildfireError:
        raise
    except ee.EEException as exc:
        raise map_ee_error(exc, what) from exc
    except Exception as exc:  # noqa: BLE001 - network/transport failures
        raise EarthEngineServiceError(
            f'Unexpected error while {what}.', details=f'{type(exc).__name__}: {str(exc)[:300]}') from exc
