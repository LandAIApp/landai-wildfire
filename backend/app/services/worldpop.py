"""WorldPop population estimate for the real affected footprint (asynchronous task API, bounded polling).

The client implements the contract described for the project (WorldPop API v2):

    POST {base}/v2/population          body: {"geojson": <GeoJSON>, "year": 2020, "resolution": "100m"}
    GET  {base}/v2/tasks/{task_id}

and, selectable with WORLDPOP_API_VERSION=v1, the publicly documented v1 service
(``GET /v1/services/stats?dataset=wpgppop&year=..&geojson=..&runasync=true`` + ``GET /v1/tasks/{id}``).
The response parser is deliberately tolerant about field names; ``scripts/smoke_test_exposure.py`` prints
the raw responses so the contract can be verified against the live service. If the service cannot be reached
or answers something unintelligible the result is *unavailable* (never zero).

Population year is a configuration value (WORLDPOP_YEAR); it is NOT derived from the event date.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

import httpx
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry

from ..core.cache import TTLCache
from ..core.config import Settings
from ..core.errors import ExternalSourceError
from . import spatial

logger = logging.getLogger('landai.worldpop')
_cache = TTLCache(max_items=64)

DONE = {'finished', 'completed', 'complete', 'success', 'succeeded', 'done'}
FAILED = {'failed', 'error', 'failure', 'cancelled', 'canceled'}
POPULATION_KEYS = ('total_population', 'population', 'total', 'sum', 'estimate')


@dataclass
class PopulationResult:
    estimate: float
    year: int
    resolution: str
    dataset: str
    api_version: str
    task_id: str | None
    analysis_area_ha: float
    simplification: dict = field(default_factory=dict)
    retrieved_at: str = ''
    from_cache: bool = False


def clear_cache() -> None:
    _cache.clear()


def prepare_geometry(hazard_metric: BaseGeometry, crs: str, settings: Settings) -> tuple[BaseGeometry, dict]:
    """Return (WGS84 geometry to send, simplification report). Simplifies ONLY if the vertex count exceeds
    the configured maximum and always reports the vertices and area change."""
    vertices = spatial.count_vertices(hazard_metric)
    area_before = hazard_metric.area
    report = {'applied': False, 'vertices_before': vertices, 'vertices_after': vertices,
              'tolerance_m': 0.0, 'area_change_pct': 0.0}
    geom = hazard_metric
    if vertices > settings.worldpop_max_vertices:
        tolerance = settings.worldpop_simplify_tolerance_m
        for _ in range(6):
            candidate = hazard_metric.simplify(tolerance, preserve_topology=True)
            if spatial.count_vertices(candidate) <= settings.worldpop_max_vertices:
                geom = candidate
                break
            tolerance *= 2
        else:
            raise ExternalSourceError(
                'The affected area geometry is too complex to send to WorldPop.',
                code='worldpop_geometry_too_complex', status_code=422,
                details={'vertices': vertices, 'max_vertices': settings.worldpop_max_vertices})
        change = 0.0 if area_before == 0 else (geom.area - area_before) / area_before * 100.0
        report.update(applied=True, vertices_after=spatial.count_vertices(geom),
                      tolerance_m=tolerance, area_change_pct=round(change, 3))
    return spatial.to_wgs84(geom, crs), report


def _extract_total(payload) -> float | None:
    """Find the population total in a (possibly nested) task payload."""
    if isinstance(payload, dict):
        for key in POPULATION_KEYS:
            value = payload.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
            if isinstance(value, str):
                try:
                    return float(value)
                except ValueError:
                    pass
        for key in ('data', 'result', 'results', 'output'):
            if key in payload:
                found = _extract_total(payload[key])
                if found is not None:
                    return found
    elif isinstance(payload, list) and payload:
        return _extract_total(payload[0])
    return None


def _task_id(payload: dict) -> str | None:
    for key in ('task_id', 'taskid', 'taskId', 'id'):
        if payload.get(key):
            return str(payload[key])
    return None


def _status(payload: dict) -> str:
    return str(payload.get('status') or payload.get('state') or '').lower()


def _fail(message: str, code: str, status_code: int = 502, **details) -> ExternalSourceError:
    return ExternalSourceError(message, code=code, status_code=status_code, details=details or None)


def estimate(hazard_metric: BaseGeometry, crs: str, settings: Settings, *,
             transport: httpx.BaseTransport | None = None,
             sleep: Callable[[float], None] = time.sleep,
             clock: Callable[[], float] = time.monotonic) -> PopulationResult:
    """Population inside the real footprint polygon. Raises ExternalSourceError when unavailable."""
    wgs, simplification = prepare_geometry(hazard_metric, crs, settings)
    geojson = {'type': 'Feature', 'properties': {}, 'geometry': mapping(spatial.round_coords(wgs, 6))}
    body = json.dumps(geojson, sort_keys=True, separators=(',', ':'))
    cache_key = (settings.worldpop_base_url, settings.worldpop_api_version, settings.worldpop_year,
                 settings.worldpop_resolution, hashlib.sha256(body.encode()).hexdigest())
    cached = _cache.get(cache_key)
    if cached is not None:
        cached.from_cache = True
        return cached

    headers = {'User-Agent': settings.overpass_user_agent, 'Accept': 'application/json'}
    if settings.worldpop_api_key:
        headers['X-API-Key'] = settings.worldpop_api_key
    base = settings.worldpop_base_url.rstrip('/')
    v1 = settings.worldpop_api_version.lower() == 'v1'
    try:
        with httpx.Client(headers=headers, timeout=settings.worldpop_http_timeout_s, transport=transport) as client:
            if v1:
                response = client.get(f'{base}/v1/services/stats', params={
                    'dataset': 'wpgppop', 'year': settings.worldpop_year, 'geojson': body, 'runasync': 'true'})
            else:
                response = client.post(f'{base}/v2/population', json={
                    'geojson': geojson, 'year': settings.worldpop_year,
                    'resolution': settings.worldpop_resolution})
            first = _json(response)
            task_id = _task_id(first)
            total = _extract_total(first) if _status(first) in DONE else None
            if total is None:
                if not task_id:
                    raise _fail('WorldPop did not return a task identifier.', 'worldpop_bad_response')
                total = _poll(client, base, task_id, v1, settings, sleep, clock)
    except httpx.TimeoutException as exc:
        raise _fail('WorldPop did not answer in time.', 'worldpop_timeout', 504) from exc
    except httpx.HTTPError as exc:
        raise _fail('WorldPop could not be reached.', 'worldpop_unreachable') from exc

    if total < 0 or total != total:
        raise _fail('WorldPop returned an invalid population value.', 'worldpop_bad_response')
    result = PopulationResult(
        estimate=round(total, 1), year=settings.worldpop_year, resolution=settings.worldpop_resolution,
        dataset='WorldPop gridded population (constrained, UN-adjusted where available)'
        if not v1 else 'WorldPop wpgppop', api_version='v1' if v1 else 'v2', task_id=task_id,
        analysis_area_ha=round(hazard_metric.area / 10_000.0, 2), simplification=simplification,
        retrieved_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
    _cache.set(cache_key, result, settings.worldpop_cache_ttl_seconds)
    return result


def _json(response: httpx.Response) -> dict:
    if response.status_code == 429:
        raise _fail('WorldPop rate limit reached. Try again later.', 'worldpop_rate_limited', 429)
    if response.status_code >= 400:
        raise _fail(f'WorldPop answered HTTP {response.status_code}.', 'worldpop_http_error',
                    502 if response.status_code >= 500 else 422, http_status=response.status_code)
    try:
        payload = response.json()
    except ValueError as exc:
        raise _fail('WorldPop returned a response that is not JSON.', 'worldpop_bad_response') from exc
    if not isinstance(payload, dict):
        raise _fail('WorldPop returned an unexpected response.', 'worldpop_bad_response')
    return payload


def _poll(client: httpx.Client, base: str, task_id: str, v1: bool, settings: Settings,
          sleep: Callable[[float], None], clock: Callable[[], float]) -> float:
    url = f'{base}/v1/tasks/{task_id}' if v1 else f'{base}/v2/tasks/{task_id}'
    deadline = clock() + settings.worldpop_max_wait_s
    while True:
        payload = _json(client.get(url))
        state = _status(payload)
        if state in FAILED:
            raise _fail('WorldPop could not compute the population for this area.', 'worldpop_task_failed',
                        502, task_id=task_id)
        if state in DONE:
            total = _extract_total(payload)
            if total is None:
                raise _fail('WorldPop finished but returned no population value.', 'worldpop_bad_response')
            return total
        if clock() + settings.worldpop_poll_interval_s > deadline:
            raise _fail('WorldPop is still processing; the estimate is unavailable for now.',
                        'worldpop_timeout', 504, task_id=task_id)
        sleep(settings.worldpop_poll_interval_s)
