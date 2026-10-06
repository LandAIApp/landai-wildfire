from fastapi import APIRouter, Request
from ..core.rate_limit import limiter

from ..schemas.wildfire import AnalyzeResponse, PreflightResponse, WildfireRequest
from ..services.analysis import run_analysis
from ..services.preflight import run_preflight

router = APIRouter(prefix='/api/v1/wildfire', tags=['wildfire'])


@router.post('/preflight', response_model=PreflightResponse)
def preflight(request: WildfireRequest) -> PreflightResponse:
    return run_preflight(request)


@router.post('/analyze', response_model=AnalyzeResponse)
@limiter.limit("5/hour")
@limiter.limit("20/day")
def analyze(request: Request, payload: WildfireRequest) -> AnalyzeResponse:
    return run_analysis(payload)
