from fastapi import APIRouter

from ..schemas.wildfire import AnalyzeResponse, PreflightResponse, WildfireRequest
from ..services.analysis import run_analysis
from ..services.preflight import run_preflight

router = APIRouter(prefix='/api/v1/wildfire', tags=['wildfire'])


@router.post('/preflight', response_model=PreflightResponse)
def preflight(request: WildfireRequest) -> PreflightResponse:
    return run_preflight(request)


@router.post('/analyze', response_model=AnalyzeResponse)
def analyze(request: WildfireRequest) -> AnalyzeResponse:
    return run_analysis(request)
