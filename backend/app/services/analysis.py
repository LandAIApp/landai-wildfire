"""End-to-end wildfire analysis service (API boundary around run_burn_model)."""
from __future__ import annotations

from datetime import datetime, timezone

import ee

from ..core.earth_engine import evaluate
from ..core.errors import (
    MunicipalityNotFoundError, NoTrainingSamplesError, PreflightFailedError,
)
from ..schemas.wildfire import (
    AnalyzeResponse, AreaEntry, Issue, TrainingInfo, WildfireRequest,
)
from ..wildfire.config import THRESHOLD_SPECS
from ..wildfire.model import run_burn_model
from . import administrative
from .preflight import run_preflight
from .tiles import build_layers

MODEL_VERSION = 'FIRE FOREST COLOMBIA V7.6 (Python port)'
LOW_SAMPLE_WARNING = 50  # application heuristic only, not part of V7.6
THRESHOLD_LABELS = {
    'wf035': 'Possible', 'wf050': 'Probable', 'wf060': 'Moderate-high',
    'wf072': 'High confidence', 'wf085': 'Very high confidence',
}


def run_analysis(req: WildfireRequest) -> AnalyzeResponse:
    pre = run_preflight(req)
    if not pre.valid:
        if any(i.code == 'municipality_not_found' for i in pre.blocking_errors):
            raise MunicipalityNotFoundError(pre.blocking_errors[0].message)
        raise PreflightFailedError(
            'The analysis cannot run: ' + ' '.join(i.message for i in pre.blocking_errors),
            details=[i.model_dump() for i in pre.blocking_errors])

    collection = administrative.select_municipality(req.department, req.municipality)
    aoi = collection.geometry()
    result = run_burn_model(aoi, ee.Date(req.fire_date.isoformat()),
                            ee.Date(req.analysis_end.isoformat()))

    warnings: list[Issue] = list(pre.warnings)

    counts = evaluate(result['trainingCounts'], 'sampling training pixels')
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

    raw = evaluate(result['areaStatistics'], 'calculating affected area') or {}
    stats = {key: float(raw.get(key) or 0.0) for _t, _k, key, _b in THRESHOLD_SPECS}
    if not any(stats.values()):
        warnings.append(Issue(code='no_area_detected',
                              message='No area reached any likelihood threshold.'))
    area_hectares = [AreaEntry(threshold=t, key=key, label=THRESHOLD_LABELS[key], hectares=stats[key])
                     for t, _k, key, _b in THRESHOLD_SPECS]

    layers, layer_warnings = build_layers(result)
    warnings.extend(layer_warnings)
    boundary = administrative.boundary_geojson(collection)

    return AnalyzeResponse(
        status='ok',
        metadata={
            'model_version': MODEL_VERSION,
            'equivalence_validated': False,
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
        boundary=boundary, bounds=administrative.geometry_bounds(boundary['geometry']),
        warnings=warnings)
