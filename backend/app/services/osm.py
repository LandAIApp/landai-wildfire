"""OpenStreetMap retrieval through the Overpass API (server-side, POST, bounded, cached).

Query strategy: one bounding-box query for buildings, roads, health and education features, preceded by a
cheap ``out count`` query that rejects over-large requests BEFORE downloading them. The exact AOI and the
hazard footprint are applied locally (see exposure_metrics.py). No retries on 429/5xx: public Overpass
instances are shared and must not be hammered.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
from shapely.geometry import LineString, Point, Polygon
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


def _post(client: httpx.Client, settings: Settings, query: str) -> dict:
    try:
        response = client.post(settings.overpass_endpoint, data={'data': query})
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


def fetch(bounds: tuple[float, float, float, float], settings: Settings,
          transport: httpx.BaseTransport | None = None) -> OsmData:
    """Retrieve OSM data for a bbox (west, south, east, north). Cached for equivalent queries."""
    cache_key = (settings.overpass_endpoint, tuple(round(v, 4) for v in bounds))
    cached = _cache.get(cache_key)
    if cached is not None:
        cached.from_cache = True
        return cached
    count_query, data_query = build_queries(bounds, settings)
    headers = {'User-Agent': settings.overpass_user_agent, 'Accept': 'application/json'}
    with slot('overpass', settings.overpass_max_concurrent, wait_seconds=20,
              busy_message='Another OpenStreetMap query is running. Please retry in a moment.'):
        with httpx.Client(headers=headers, timeout=settings.overpass_http_timeout_s,
                          transport=transport) as client:
            counted = _post(client, settings, count_query)
            total = _total_from_count(counted)
            if total is not None and total > settings.overpass_max_elements:
                raise ExternalSourceError(
                    f'The area contains about {total:,} OpenStreetMap elements, above the limit of '
                    f'{settings.overpass_max_elements:,}. Draw a smaller area.',
                    code='osm_too_many_elements', status_code=422,
                    details={'elements': total, 'limit': settings.overpass_max_elements})
            payload = _post(client, settings, data_query)
    elements = payload.get('elements', [])
    if len(elements) > settings.overpass_max_elements:
        raise ExternalSourceError('Too many OpenStreetMap elements returned. Draw a smaller area.',
                                  code='osm_too_many_elements', status_code=422,
                                  details={'elements': len(elements), 'limit': settings.overpass_max_elements})
    data = parse_elements(elements)
    data.retrieved_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    data.endpoint = settings.overpass_endpoint
    data.bbox = tuple(bounds)  # type: ignore[assignment]
    _cache.set(cache_key, data, settings.overpass_cache_ttl_seconds)
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
