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
from . import administrative

LONG_WINDOW_DAYS = 60


def _issue(code: str, message: str) -> Issue:
    return Issue(code=code, message=message)


def run_preflight(req: WildfireRequest) -> PreflightResponse:
    settings = get_settings()
    blocking: list[Issue] = []
    warnings: list[Issue] = []

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
                                 blocking_errors=blocking)

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
                                 warnings=warnings, blocking_errors=blocking)

    avail = evaluate(get_input_availability(
        collection.geometry(),
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
        warnings=warnings, blocking_errors=blocking)
