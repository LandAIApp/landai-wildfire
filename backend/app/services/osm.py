"""OpenStreetMap retrieval through the Overpass API (server-side, POST, bounded, cached).

Query strategy: one bounding-box query for buildings, roads, health and education features, preceded by a
cheap ``out count`` query that rejects over-large requests BEFORE downloading them. The exact AOI and the
hazard footprint are applied locally (see exposure_metrics.py). A failing public instance (429/5xx/timeout) is
never retried; the same query is tried ONCE on each configured fallback mirror (OVERPASS_FALLBACK_ENDPOINTS), with
a pause between servers, so a busy instance does not make the whole exposure analysis partial.
"""
from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union
from shapely.validation import make_valid

from ..core.cache import TTLCache
from ..core.config import Settings
from ..core.errors import ExternalSourceError
from ..core.gate import slot

logger = logging.getLogger('landai.osm')
_cache = TTLCache(max_items=32)

# Documented tag sets (docs/exposure-methodology.md)
HIGHWAY_CLASSES = ('motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'unclassified', 'residential',
                   'service', 'living_street', 'track', 'road')
ROAD_RE = '^(' + '|'.join(f'{c}(_link)?' if c in ('motorway', 'trunk', 'primary', 'secondary', 'tertiary')
                         else c for c in HIGHWAY_CLASSES) + ')$'
HEALTH_AMENITY = ('hospital', 'clinic', 'doctors')
HEALTH_HEALTHCARE = ('hospital', 'clinic', 'centre', 'doctor')
EDU_AMENITY = ('school', 'kindergarten', 'college', 'university')


@dataclass
class OsmFeature:
    key: tuple[str, int]
    geom: BaseGeometry                      # WGS84
    tags: dict[str, str]


@dataclass
class OsmData:
    buildings: list[OsmFeature] = field(default_factory=list)
    roads: list[OsmFeature] = field(default_factory=list)
    health: list[OsmFeature] = field(default_factory=list)
    education: list[OsmFeature] = field(default_factory=list)
    retrieved_at: str = ''
    endpoint: str = ''
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)       # west, south, east, north
    element_count: int = 0
    skipped_relations: int = 0
    skipped_other: int = 0
    from_cache: bool = False
    cells: int = 1


def _union_clauses(bbox: str) -> str:
    return (f'nwr["building"]({bbox});'
            f'nwr["highway"~"{ROAD_RE}"]({bbox});'
            f'nwr["amenity"~"^({"|".join(HEALTH_AMENITY)})$"]({bbox});'
            f'nwr["healthcare"~"^({"|".join(HEALTH_HEALTHCARE)})$"]({bbox});'
            f'nwr["amenity"~"^({"|".join(EDU_AMENITY)})$"]({bbox});')


def build_queries(bounds: tuple[float, float, float, float], settings: Settings) -> tuple[str, str]:
    west, south, east, north = bounds
    bbox = f'{south:.6f},{west:.6f},{north:.6f},{east:.6f}'
    timeout = settings.overpass_query_timeout_s
    clauses = _union_clauses(bbox)
    count = f'[out:json][timeout:{min(timeout, 25)}];({clauses});out count;'
    data = (f'[out:json][timeout:{timeout}][maxsize:{settings.overpass_max_response_bytes}];'
            f'({clauses});out tags geom;')
    return count, data


def _post(client: httpx.Client, settings: Settings, query: str, endpoint: str | None = None) -> dict:
    try:
        response = client.post(endpoint or settings.overpass_endpoint, data={'data': query})
    except httpx.TimeoutException as exc:
        raise ExternalSourceError('OpenStreetMap (Overpass) timed out.', code='osm_timeout',
                                  status_code=504) from exc
    except httpx.HTTPError as exc:
        raise ExternalSourceError('OpenStreetMap (Overpass) could not be reached.', code='osm_unavailable',
                                  details=type(exc).__name__) from exc
    if response.status_code == 429:
        raise ExternalSourceError('OpenStreetMap (Overpass) is rate limiting requests. Try again later.',
                                  code='osm_rate_limited', status_code=429,
                                  details={'retry_after': response.headers.get('retry-after')})
    if response.status_code in (504, 408):
        raise ExternalSourceError('OpenStreetMap (Overpass) timed out on the server side.',
                                  code='osm_timeout', status_code=504)
    if response.status_code >= 500:
        raise ExternalSourceError('OpenStreetMap (Overpass) is temporarily unavailable.',
                                  code='osm_unavailable', details={'http_status': response.status_code})
    if response.status_code != 200:
        raise ExternalSourceError('OpenStreetMap (Overpass) rejected the request.', code='osm_unavailable',
                                  details={'http_status': response.status_code,
                                           'body': response.text[:300]})
    if len(response.content) > settings.overpass_max_response_bytes:
        raise ExternalSourceError('The OpenStreetMap response is larger than the allowed size. '
                                  'Use a smaller area.', code='osm_response_too_large', status_code=422)
    try:
        payload = response.json()
    except ValueError as exc:
        raise ExternalSourceError('OpenStreetMap (Overpass) returned an unreadable response.',
                                  code='osm_unavailable') from exc
    remark = str(payload.get('remark', ''))
    if 'runtime error' in remark.lower() or 'out of memory' in remark.lower():
        # Overpass answers 200 with a remark when the query was cut short: the data is INCOMPLETE.
        raise ExternalSourceError('OpenStreetMap (Overpass) could not complete the query (server limits). '
                                  'Use a smaller area.', code='osm_incomplete', status_code=422,
                                  details=remark[:200])
    return payload


def _relation_geometry(element: dict) -> BaseGeometry | None:
    outers, inners = [], []
    for member in element.get('members', []):
        geometry = member.get('geometry')
        if member.get('type') != 'way' or not geometry or len(geometry) < 2:
            continue
        line = LineString([(p['lon'], p['lat']) for p in geometry])
        (inners if member.get('role') == 'inner' else outers).append(line)
    if not outers:
        return None
    polygons = list(polygonize(unary_union(outers)))
    if not polygons:
        return None
    result = unary_union(polygons)
    if inners:
        holes = list(polygonize(unary_union(inners)))
        if holes:
            result = result.difference(unary_union(holes))
    return make_valid(result) if not result.is_valid else result


def _geometry(element: dict, is_area_hint: bool) -> BaseGeometry | None:
    kind = element.get('type')
    if kind == 'node':
        if 'lat' not in element or 'lon' not in element:
            return None
        return Point(element['lon'], element['lat'])
    if kind == 'way':
        coords = [(p['lon'], p['lat']) for p in element.get('geometry', [])]
        if len(coords) < 2:
            return None
        closed = len(coords) >= 4 and coords[0] == coords[-1]
        if closed and is_area_hint:
            poly = Polygon(coords)
            return poly if poly.is_valid else make_valid(poly)
        return LineString(coords)
    if kind == 'relation':
        return _relation_geometry(element)
    return None


def _is_health(tags: dict) -> bool:
    return tags.get('amenity') in HEALTH_AMENITY or tags.get('healthcare') in HEALTH_HEALTHCARE


def parse_elements(elements: list[dict]) -> OsmData:
    """Categorise and deduplicate raw Overpass elements. An element can belong to several categories
    (e.g. a school building is both a building and an educational facility)."""
    data = OsmData()
    seen: set[tuple[str, int]] = set()
    for element in elements:
        kind, ident = element.get('type'), element.get('id')
        if kind not in ('node', 'way', 'relation') or ident is None:
            continue
        key = (kind, int(ident))
        if key in seen:
            continue                      # same element returned twice (overlapping union clauses)
        seen.add(key)
        tags = {str(k): str(v) for k, v in (element.get('tags') or {}).items()}
        is_building = tags.get('building', 'no') != 'no' and 'building' in tags
        is_road = kind == 'way' and 'highway' in tags
        is_health = _is_health(tags)
        is_edu = tags.get('amenity') in EDU_AMENITY
        if not (is_building or is_road or is_health or is_edu):
            data.skipped_other += 1
            continue
        geom = _geometry(element, is_area_hint=is_building or is_health or is_edu)
        if geom is None or geom.is_empty:
            if kind == 'relation':
                data.skipped_relations += 1
            else:
                data.skipped_other += 1
            continue
        feature = OsmFeature(key=key, geom=geom, tags=tags)
        if is_building:
            data.buildings.append(feature)
        if is_road and isinstance(geom, LineString):
            data.roads.append(feature)
        if is_health:
            data.health.append(feature)
        if is_edu:
            data.education.append(feature)
    data.element_count = len(seen)
    return data


def plan_cells(bounds: tuple[float, float, float, float], settings: Settings,
               region: BaseGeometry | None = None) -> list[tuple[float, float, float, float]]:
    """Split a bbox into ~``overpass_cell_km`` cells (west, south, east, north); [bounds] when it is small.

    A big query ({building, highway, ...} over a whole municipality-sized bbox) makes public Overpass servers
    answer 504 / time out, while many small ones are quick. ``region`` (WGS84, e.g. the buffered footprint)
    drops the cells that cannot contain anything relevant.
    """
    west, south, east, north = bounds
    lat_mid = (south + north) / 2
    dlat = settings.overpass_cell_km / 111.32
    dlon = settings.overpass_cell_km / (111.32 * max(math.cos(math.radians(lat_mid)), 0.2))
    if (east - west) <= dlon * 1.5 and (north - south) <= dlat * 1.5:
        return [bounds]
    nx = max(1, math.ceil((east - west) / dlon))
    ny = max(1, math.ceil((north - south) / dlat))
    wx, wy = (east - west) / nx, (north - south) / ny
    cells = []
    for j in range(ny):
        for i in range(nx):
            cell = (west + i * wx, south + j * wy, west + (i + 1) * wx, south + (j + 1) * wy)
            if region is None or region.intersects(box(*cell)):
                cells.append(cell)
    return cells


def _query_bbox(client_factory, settings: Settings, bounds, endpoints: list[str], with_count: bool):
    """Run one bbox query, trying each endpoint ONCE in order. Returns (elements, endpoint_used).

    A 429 ("no free slot") is the server asking us to wait: we wait for what it says (bounded) and ask the SAME
    server again, at most ``overpass_rate_limit_retries`` times, before moving on to the next mirror.
    """
    count_query, data_query = build_queries(bounds, settings)
    last_error: ExternalSourceError | None = None
    for attempt, endpoint in enumerate(endpoints):
        if attempt:
            time.sleep(settings.overpass_fallback_pause_s)
        waits = 0
        while True:
            try:
                with client_factory() as client:
                    if with_count:
                        total = _total_from_count(_post(client, settings, count_query, endpoint))
                        if total is not None and total > settings.overpass_max_elements:
                            raise ExternalSourceError(
                                f'The area contains about {total:,} OpenStreetMap elements, above the limit of '
                                f'{settings.overpass_max_elements:,}. Draw a smaller area.',
                                code='osm_too_many_elements', status_code=422,
                                details={'elements': total, 'limit': settings.overpass_max_elements})
                    payload = _post(client, settings, data_query, endpoint)
                return payload.get('elements', []), endpoint
            except ExternalSourceError as exc:
                if exc.code not in ('osm_timeout', 'osm_unavailable', 'osm_rate_limited'):
                    raise                      # a size/limit problem is the same on every mirror
                logger.warning('overpass_endpoint_failed endpoint=%s code=%s', endpoint, exc.code)
                last_error = exc
                if exc.code == 'osm_rate_limited' and waits < settings.overpass_rate_limit_retries:
                    waits += 1
                    time.sleep(_retry_wait(exc, settings))
                    continue
                break
    raise last_error  # type: ignore[misc]


def _retry_wait(exc: ExternalSourceError, settings: Settings) -> float:
    retry_after = exc.details.get('retry_after') if isinstance(exc.details, dict) else None
    try:
        wait = float(retry_after)
    except (TypeError, ValueError):
        wait = settings.overpass_rate_limit_wait_s
    return max(1.0, min(wait, settings.overpass_rate_limit_wait_s * 2))


def fetch(bounds: tuple[float, float, float, float], settings: Settings,
          transport: httpx.BaseTransport | None = None, region: BaseGeometry | None = None) -> OsmData:
    """Retrieve OSM data for a bbox (west, south, east, north), in small cells when the bbox is large.

    Results are cached per cell. ``region`` (optional, WGS84) limits the cells to those touching it.
    """
    cells = plan_cells(bounds, settings, region)
    if len(cells) > settings.overpass_max_cells:
        raise ExternalSourceError(
            f'The area needs {len(cells)} OpenStreetMap requests, above the limit of {settings.overpass_max_cells}. '
            'Use a smaller area.', code='osm_too_many_elements', status_code=422,
            details={'cells': len(cells), 'limit': settings.overpass_max_cells})
    single = len(cells) == 1
    headers = {'User-Agent': settings.overpass_user_agent, 'Accept': 'application/json'}
    endpoints = [settings.overpass_endpoint] + [
        e.strip() for e in settings.overpass_fallback_endpoints.split(',')
        if e.strip() and e.strip() != settings.overpass_endpoint]

    def client_factory():
        return httpx.Client(headers=headers, timeout=settings.overpass_http_timeout_s, transport=transport)

    elements: list[dict] = []
    used = endpoints[0]
    from_cache = True
    with slot('overpass', settings.overpass_max_concurrent, wait_seconds=20,
              busy_message='Another OpenStreetMap query is running. Please retry in a moment.'):
        for index, cell in enumerate(cells):
            cache_key = ('cell', tuple(round(v, 5) for v in cell))
            cached = _cache.get(cache_key)
            if cached is not None:
                elements.extend(cached)
                continue
            from_cache = False
            if index:
                time.sleep(settings.overpass_cell_pause_s)
            try:
                cell_elements, endpoint = _query_bbox(client_factory, settings, cell, endpoints, with_count=single)
            except ExternalSourceError as exc:
                if len(cells) > 1:     # finished cells stay cached: the next attempt resumes where this one stopped
                    base = exc.details if isinstance(exc.details, dict) else {}
                    exc.details = {**base, 'cells_done': index, 'cells_total': len(cells)}
                raise
            if endpoint != used:                        # keep using the server that last answered
                endpoints = [endpoint] + [e for e in endpoints if e != endpoint]
                used = endpoint
            _cache.set(cache_key, cell_elements, settings.overpass_cache_ttl_seconds)
            elements.extend(cell_elements)
            if len(elements) > settings.overpass_max_elements:
                break
            logger.info('overpass_cell %s/%s elements=%s', index + 1, len(cells), len(cell_elements))
    if len(elements) > settings.overpass_max_elements:
        raise ExternalSourceError('Too many OpenStreetMap elements returned. Draw a smaller area.',
                                  code='osm_too_many_elements', status_code=422,
                                  details={'elements': len(elements), 'limit': settings.overpass_max_elements})
    data = parse_elements(elements)
    data.retrieved_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    data.endpoint = used
    data.bbox = tuple(bounds)  # type: ignore[assignment]
    data.from_cache = from_cache
    data.cells = len(cells)
    return data


def _total_from_count(payload: dict) -> int | None:
    for element in payload.get('elements', []):
        if element.get('type') == 'count':
            tags = element.get('tags', {})
            try:
                return int(tags.get('total'))
            except (TypeError, ValueError):
                return None
    return None


def clear_cache() -> None:
    _cache.clear()
