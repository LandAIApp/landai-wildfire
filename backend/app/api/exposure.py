from fastapi import APIRouter, Request

from ..core.rate_limit import exposure_limit, limiter
from ..schemas.exposure import ExposureRequest, ExposureResponse
from ..services.exposure import analyze as run_exposure

router = APIRouter(prefix='/api/v1/exposure', tags=['exposure'])


@router.post('/analyze', response_model=ExposureResponse)
@limiter.limit(exposure_limit)
def analyze_exposure(request: Request, payload: ExposureRequest) -> ExposureResponse:
    """Exposure & Impact analysis for a wildfire footprint (explicit user action)."""
    return run_exposure(payload)
