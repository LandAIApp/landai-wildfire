"""Live processing stages of a running analysis (see core/progress.py)."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..core import progress
from ..core.rate_limit import limiter, progress_limit

router = APIRouter(prefix='/api/v1', tags=['progress'])


@router.get('/progress/{progress_id}')
@limiter.limit(progress_limit)
def get_progress(request: Request, progress_id: str):
    """Stage names, states and durations only. 404 when this instance knows nothing about the id."""
    snap = progress.snapshot(progress_id)
    if snap is None:
        return JSONResponse(status_code=404, content={
            'status': 'error', 'code': 'progress_unknown',
            'message': 'No progress is known for this id on this server instance.', 'details': None})
    return {'status': 'ok', **snap}
