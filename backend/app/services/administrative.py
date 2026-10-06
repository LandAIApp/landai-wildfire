"""Departments / municipalities from the private municipal FeatureCollection."""
from __future__ import annotations

from functools import lru_cache

import ee

from ..core.config import get_settings
from ..core.earth_engine import ensure_initialized, evaluate
from ..core.errors import DepartmentNotFoundError

DEPARTMENT_FIELD = 'ADM1_ES'
MUNICIPALITY_FIELD = 'ADM2_ES'
MUNICIPALITY_CODE_FIELD = 'ADM2_PCODE'  # declared by the asset; unused by V7.6


def municipalities_collection() -> ee.FeatureCollection:
    ensure_initialized()
    return ee.FeatureCollection(get_settings().municipalities_asset)


@lru_cache(maxsize=1)
def _departments() -> tuple[str, ...]:
    values = evaluate(
        municipalities_collection().aggregate_array(DEPARTMENT_FIELD).distinct().sort(),
        'loading departments')
    return tuple(values or ())


@lru_cache(maxsize=128)
def _municipalities(department: str) -> tuple[str, ...]:
    values = evaluate(
        municipalities_collection().filter(ee.Filter.eq(DEPARTMENT_FIELD, department))
        .aggregate_array(MUNICIPALITY_FIELD).distinct().sort(),
        'loading municipalities')
    return tuple(values or ())


def clear_cache() -> None:
    _departments.cache_clear()
    _municipalities.cache_clear()


def list_departments() -> list[str]:
    return list(_departments())


def list_municipalities(department: str) -> list[str]:
    values = _municipalities(department)
    if not values:
        raise DepartmentNotFoundError(f"Department '{department}' was not found.")
    return list(values)


def select_municipality(department: str, municipality: str) -> ee.FeatureCollection:
    """Same selection as V7.6: department AND municipality name, all matches."""
    return (municipalities_collection()
            .filter(ee.Filter.eq(DEPARTMENT_FIELD, department))
            .filter(ee.Filter.eq(MUNICIPALITY_FIELD, municipality)))


def _walk(coords, acc):
    if coords and isinstance(coords[0], (int, float)):
        acc.append(coords)
    else:
        for c in coords or []:
            _walk(c, acc)


def geometry_bounds(geometry: dict) -> list[list[float]]:
    """[[south, west], [north, east]] from a GeoJSON geometry (for Leaflet)."""
    pts: list = []
    if geometry.get('type') == 'GeometryCollection':
        for g in geometry.get('geometries', []):
            _walk(g.get('coordinates'), pts)
    else:
        _walk(geometry.get('coordinates'), pts)
    if not pts:
        return [[-4.3, -79.0], [13.5, -66.8]]  # Colombia fallback
    lons, lats = [p[0] for p in pts], [p[1] for p in pts]
    return [[min(lats), min(lons)], [max(lats), max(lons)]]


def boundary_geojson(collection: ee.FeatureCollection) -> dict:
    """Simplified boundary for DISPLAY only (scientific AOI is never simplified)."""
    geometry = evaluate(collection.geometry().simplify(100), 'loading the municipal boundary')
    return {'type': 'Feature', 'properties': {}, 'geometry': geometry}
