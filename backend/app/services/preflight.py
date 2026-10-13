"""Data-availability preflight. Never trains the Random Forest."""
from __future__ import annotations

from datetime import date, datetime, timezone

import ee

from ..core.config import get_settings
from ..core.earth_engine import evaluate
from ..schemas.wildfire import (
    DateRange, DateWindows, Issue, PreflightResponse, WildfireRequest,
)
from ..wildfire.sentinel2 import get_input_availability
from . import administrative, aoi as aoi_service

LONG_WINDOW_DAYS = 60


def _issue(code: str, message: str) -> Issue:
    return Issue(code=code, message=message)


def _date_issues(req: WildfireRequest, settings) -> list[Issue]:
    blocking: list[Issue] = []
    today = datetime.now(timezone.utc).date()
    if req.fire_date > today:
        blocking.append(_issue('future_date', 'The fire date is in the future.'))
    if req.fire_date < date.fromisoformat(settings.min_fire_date):
        blocking.append(_issue(
            'date_too_early',
            f'Fire dates before {settings.min_fire_date} are not supported '
            '(Cloud Score+ and the 6-month history need coverage).'))
    if req.analysis_end < req.fire_date:
        blocking.append(_issue('invalid_dates', 'analysis_end must be on or after fire_date.'))
    return blocking


def _availability(req: WildfireRequest, geometry, area_ha: float, aoi_kind: str,
                  blocking: list[Issue], warnings: list[Issue]) -> PreflightResponse:
    """Scene counts (one small Earth Engine call) and the resulting issues. Shared by both AOI modes."""
    avail = evaluate(get_input_availability(
        geometry,
        ee.Date(req.fire_date.isoformat()), ee.Date(req.analysis_end.isoformat())),
        'checking Sentinel-2 availability')

    pre, post, hist = int(avail['preScenes']), int(avail['postScenes']), int(avail['historyScenes'])
    if pre < 1:
        blocking.append(_issue('no_pre_images', 'No Sentinel-2 images exist for the PRE period.'))
    if post < 1:
        blocking.append(_issue('no_post_images',
                               'No Sentinel-2 images exist for the POST period. Extend the end date.'))
    if hist < 2:
        blocking.append(_issue('insufficient_history',
                               'Insufficient historical Sentinel-2 context (at least 2 scenes needed).'))
    if not blocking:
        if pre < 2 or post < 2:
            warnings.append(_issue(
                'few_scenes', 'Very few scenes are available; the estimate may be less reliable.'))
        if (req.analysis_end - req.fire_date).days > LONG_WINDOW_DAYS:
            warnings.append(_issue(
                'long_window', f'Analysis windows over {LONG_WINDOW_DAYS} days are slower '
                               'and may include post-fire regrowth or later events.'))

    windows = DateWindows(
        pre=DateRange(start=avail['preStart'], end=avail['preEnd']),
        post=DateRange(start=avail['postStart'], end=avail['postEnd']),
        history=DateRange(start=avail['historyStart'], end=avail['historyEnd']))
    return PreflightResponse(
        status='blocked' if blocking else 'ok', valid=not blocking, pre_count=pre,
        post_count=post, history_count=hist, date_windows=windows, aoi_hectares=area_ha,
        aoi_kind=aoi_kind, warnings=warnings, blocking_errors=blocking)


def run_preflight(req: WildfireRequest) -> PreflightResponse:
    if req.geometry is not None:
        return _preflight_drawn(req)
    settings = get_settings()
    warnings: list[Issue] = []
    blocking = _date_issues(req, settings)

    collection = administrative.select_municipality(req.department, req.municipality)
    info = evaluate(ee.Dictionary({
        'matches': collection.size(),
        'area_ha': collection.geometry().area(100).divide(10000),
    }), 'resolving the municipality')

    if not info or not info.get('matches'):
        blocking.append(_issue(
            'municipality_not_found',
            f"Municipality '{req.municipality}' was not found in department '{req.department}'."))
        return PreflightResponse(status='blocked', valid=False, warnings=warnings,
                                 aoi_kind='municipality', blocking_errors=blocking)

    area_ha = float(info.get('area_ha') or 0)
    if area_ha > settings.max_aoi_hectares:
        blocking.append(_issue(
            'aoi_too_large',
            f'The municipality covers {area_ha:,.0f} ha, above the configured limit of '
            f'{settings.max_aoi_hectares:,.0f} ha.'))
    elif area_ha > settings.warn_aoi_hectares:
        warnings.append(_issue(
            'aoi_large', f'Large area ({area_ha:,.0f} ha): processing may be slow or hit limits.'))

    if blocking:
        return PreflightResponse(status='blocked', valid=False, aoi_hectares=area_ha,
                                 aoi_kind='municipality', warnings=warnings, blocking_errors=blocking)

    return _availability(req, collection.geometry(), area_ha, 'municipality', blocking, warnings)


def _preflight_drawn(req: WildfireRequest) -> PreflightResponse:
    """Drawn polygon: local validation first (no Earth Engine quota for an invalid/oversized area)."""
    settings = get_settings()
    blocking = _date_issues(req, settings)
    ring, hectares, aoi_blocking, warnings = aoi_service.check_drawn(req, settings)
    blocking += aoi_blocking
    if blocking:
        return PreflightResponse(status='blocked', valid=False, aoi_hectares=hectares, aoi_kind='drawn',
                                 warnings=warnings, blocking_errors=blocking)
    drawn = aoi_service.build_drawn(ring, hectares)  # type: ignore[arg-type]
    return _availability(req, drawn.geometry, hectares, 'drawn', blocking, warnings)  # type: ignore[arg-type]
