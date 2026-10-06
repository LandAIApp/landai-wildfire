from fastapi import APIRouter

from ..core import earth_engine

router = APIRouter()


@router.get('/health')
def health(check_ee: bool = False) -> dict:
    """Liveness. Use ?check_ee=true to also initialize/verify Earth Engine."""
    ee_info = earth_engine.status()
    if check_ee:
        try:
            earth_engine.ensure_initialized()
        except Exception as exc:  # noqa: BLE001
            return {'status': 'degraded', 'earth_engine': {'initialized': False,
                                                           'error': getattr(exc, 'message', str(exc))}}
        ee_info = earth_engine.status()
    return {'status': 'ok', 'earth_engine': ee_info}
