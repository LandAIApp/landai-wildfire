"""End-to-end wildfire analysis service (API boundary around run_burn_model)."""
from __future__ import annotations

from datetime import datetime, timezone

import logging
import time

import ee

from ..core import progress as progress_mod
from ..core.config import get_settings
from ..core.earth_engine import evaluate
from ..core.errors import (
    MunicipalityNotFoundError, NoTrainingSamplesError, PreflightFailedError, ServicePausedError,
)
from ..core.gate import slot
from ..core.memo import Memo, fingerprint
from ..core.progress import NullProgress, Progress
from ..schemas.wildfire import (
    AnalyzeResponse, AreaEntry, Issue, TrainingInfo, WildfireRequest,
)
from ..wildfire.config import THRESHOLD_SPECS
from ..wildfire.model import run_burn_model
from . import administrative, analysis_ref
from . import aoi as aoi_service
from .preflight import run_preflight
from .tiles import build_layers

logger = logging.getLogger('landai.analysis')

MODEL_VERSION = 'FIRE FOREST COLOMBIA V7.6 (Python port)'
LOW_SAMPLE_WARNING = 50  # application heuristic only, not part of V7.6
THRESHOLD_LABELS = {
    'wf035': 'Possible', 'wf050': 'Probable', 'wf060': 'Moderate-high',
    'wf072': 'High confidence', 'wf085': 'Very high confidence',
}


ANALYSIS_STAGES = ['preflight', 'model', 'training', 'area', 'layers']
# Identical analyses that arrive together are computed once (single-flight). The result is NOT cached afterwards:
# it carries Earth Engine map-tile links that expire.
_flights = Memo(max_items=1)


def reset_flights() -> None:
    _flights.clear()


def run_analysis(req: WildfireRequest) -> AnalyzeResponse:
    """Guarded entry point: kill switch, bounded concurrency, duplicate-request sharing and live stages."""
    settings = get_settings()
    if not settings.analysis_enabled:
        raise ServicePausedError('The wildfire analysis is temporarily paused by the operator.')
    progress = progress_mod.begin(req.progress_id, ANALYSIS_STAGES)
    key = fingerprint('analysis', req.model_dump(mode='json', exclude={'progress_id'}))

    def compute() -> AnalyzeResponse:
        with slot('analysis', settings.analysis_max_concurrent,
                  busy_message='The server is running other analyses. Please retry in a minute.'):
            return _run_analysis(req, progress)

    try:
        result, how = _flights.get_or_compute(key, compute, ttl=0)
        if how != 'computed':
            logger.info('wildfire_analysis_shared with an identical request already running')
        return result
    finally:
        progress.close()


def _run_analysis(req: WildfireRequest, progress: Progress | None = None) -> AnalyzeResponse:
    progress = progress or NullProgress()
    started_at = time.perf_counter()
    logger.info(
        'wildfire_analysis_started department=%s municipality=%s fire_date=%s analysis_end=%s',
        req.department or '(drawn)',
        req.municipality or '(drawn)',
        req.fire_date,
        req.analysis_end,
    )
    progress.start('preflight')
    pre = run_preflight(req)
    progress.finish('preflight')
    if not pre.valid:
        if any(i.code == 'municipality_not_found' for i in pre.blocking_errors):
            raise MunicipalityNotFoundError(pre.blocking_errors[0].message)
        raise PreflightFailedError(
            'The analysis cannot run: ' + ' '.join(i.message for i in pre.blocking_errors),
            details=[i.model_dump() for i in pre.blocking_errors])

    drawn = None
    if req.geometry is not None:
        # Only the spatial input changes: the drawn polygon takes the place of the municipal geometry.
        ring, hectares, _blocking, _warn = aoi_service.check_drawn(req, get_settings())
        drawn = aoi_service.build_drawn(ring, hectares)  # type: ignore[arg-type]
        collection = None
        aoi = drawn.geometry
    else:
        collection = administrative.select_municipality(req.department, req.municipality)
        aoi = collection.geometry()
    progress.start('model')
    result = run_burn_model(aoi, ee.Date(req.fire_date.isoformat()),
                            ee.Date(req.analysis_end.isoformat()))
    progress.finish('model')

    warnings: list[Issue] = list(pre.warnings)

    progress.start('training')
    counts = evaluate(result['trainingCounts'], 'sampling training pixels')
    progress.finish('training')
    n_pos, n_neg = int(counts.get('positive', 0)), int(counts.get('negative', 0))
    if n_pos == 0:
        raise NoTrainingSamplesError(
            'No positive training samples were found: the model found no area with enough '
            'burn evidence in this period. Try a different date range.',
            details={'positive': n_pos, 'negative': n_neg})
    if n_neg == 0:
        raise NoTrainingSamplesError(
            'No negative training samples were found, so the model cannot be trained.',
            details={'positive': n_pos, 'negative': n_neg})
    if n_pos < LOW_SAMPLE_WARNING:
        warnings.append(Issue(code='few_positive_samples',
                              message=f'Only {n_pos} positive training samples were found; '
                                      'the estimate may be unstable.'))

    progress.start('area')
    raw = evaluate(result['areaStatistics'], 'calculating affected area') or {}
    progress.finish('area')
    stats = {key: float(raw.get(key) or 0.0) for _t, _k, key, _b in THRESHOLD_SPECS}
    if not any(stats.values()):
        warnings.append(Issue(code='no_area_detected',
                              message='No area reached any likelihood threshold.'))
    area_hectares = [AreaEntry(threshold=t, key=key, label=THRESHOLD_LABELS[key], hectares=stats[key])
                     for t, _k, key, _b in THRESHOLD_SPECS]

    progress.start('layers')
    layers, layer_warnings = build_layers(result)
    progress.finish('layers')
    warnings.extend(layer_warnings)
    boundary = drawn.boundary if drawn is not None else administrative.boundary_geojson(collection)
    bounds = drawn.bounds if drawn is not None else administrative.geometry_bounds(boundary['geometry'])

    elapsed = time.perf_counter() - started_at
    logger.info(
        'wildfire_analysis_completed department=%s municipality=%s '
        'positive_samples=%s negative_samples=%s '
        'wf035=%.2f wf050=%.2f wf060=%.2f wf072=%.2f wf085=%.2f '
        'duration_seconds=%.2f',
        req.department or '(drawn)',
        req.municipality or '(drawn)',
        n_pos,
        n_neg,
        stats['wf035'],
        stats['wf050'],
        stats['wf060'],
        stats['wf072'],
        stats['wf085'],
        elapsed,
    )

    return AnalyzeResponse(
        status='ok',
        metadata={
            'model_version': MODEL_VERSION,
            'equivalence_validated': False,
            'aoi_kind': req.aoi_kind,
            'department': req.department, 'municipality': req.municipality,
            'fire_date': req.fire_date.isoformat(), 'analysis_end': req.analysis_end.isoformat(),
            'aoi_hectares': pre.aoi_hectares,
            'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'disclaimer': ('Automated preliminary Earth Observation estimate. This result is not '
                           'an officially validated wildfire perimeter.'),
        },
        image_counts={'pre': pre.pre_count, 'post': pre.post_count, 'history': pre.history_count},
        date_windows=pre.date_windows,
        training=TrainingInfo(
            positive_samples=n_pos, negative_samples=n_neg,
            note='Requested 3000 / 5000 pixels; Earth Engine returns an approximate count.'),
        area_statistics=stats, area_hectares=area_hectares, layers=layers,
        boundary=boundary, bounds=bounds, warnings=warnings,
        analysis_ref=_issue_ref(req, drawn, pre.aoi_hectares, stats, pre.date_windows),
        aoi={'kind': req.aoi_kind, 'hectares': pre.aoi_hectares,
             'department': req.department, 'municipality': req.municipality})


def _issue_ref(req: WildfireRequest, drawn, aoi_hectares: float | None, stats: dict[str, float],
               windows=None) -> str:
    """Signed reference the Exposure module uses instead of any client-supplied burned polygon."""
    payload = {
        'kind': req.aoi_kind, 'fire_date': req.fire_date.isoformat(),
        'analysis_end': req.analysis_end.isoformat(), 'aoi_hectares': aoi_hectares,
        'model_version': MODEL_VERSION, 'area_ha': stats,
        'date_windows': windows.model_dump() if windows is not None else None,
    }
    if drawn is not None:
        payload['ring'] = drawn.ring
    else:
        payload['department'], payload['municipality'] = req.department, req.municipality
    return analysis_ref.issue(payload)
