"""Custom (drawn) study area: validation, area limits and the Earth Engine geometry.

Municipality mode is untouched (see preflight.py / analysis.py). The drawn polygon replaces ONLY the
spatial input: the V7.6 graph receives an ee.Geometry exactly as it receives the municipal geometry.
"""
from __future__ import annotations

from dataclasses import dataclass

import ee

from ..core.config import Settings
from ..core.earth_engine import ensure_initialized
from ..core.geometry import ring_bounds, validate_polygon
from ..schemas.wildfire import Issue, WildfireRequest

MESSAGES = {
    'aoi_too_large': 'The drawn area covers {hectares:,.0f} ha, above the limit of {max:,.0f} ha.',
    'aoi_too_small': 'The drawn area covers {hectares:,.1f} ha; the minimum is {min:,.0f} ha.',
    'aoi_large': 'Large area ({hectares:,.0f} ha): processing may be slow or hit limits.',
    'geometry_holes': 'Polygons with holes are not supported; draw a single outer ring.',
    'geometry_out_of_range': 'The polygon has coordinates outside valid longitude/latitude ranges.',
    'geometry_too_few_points': 'The polygon needs at least {min} vertices.',
    'geometry_too_many_points': 'The polygon has {count} vertices; the maximum is {max}.',
    'geometry_self_intersecting': 'The polygon crosses itself. Redraw it without crossing edges.',
    'geometry_degenerate': 'The polygon has no area.',
}


def make_issue(code: str, **params) -> Issue:
    return Issue(code=code, message=MESSAGES[code].format(**params), params=params)


@dataclass
class DrawnAOI:
    ring: list[list[float]]
    hectares: float
    geometry: ee.Geometry          # planar edges: what the user sees on the map
    boundary: dict
    bounds: list[list[float]]


def custom_limit_issues(hectares: float, settings: Settings) -> tuple[list[Issue], list[Issue]]:
    """(blocking, warnings) for a drawn area. Never truncates: an oversized AOI is rejected."""
    blocking: list[Issue] = []
    warnings: list[Issue] = []
    if hectares > settings.max_custom_aoi_hectares:
        blocking.append(make_issue('aoi_too_large', hectares=hectares, max=settings.max_custom_aoi_hectares))
    elif hectares < settings.min_custom_aoi_hectares:
        blocking.append(make_issue('aoi_too_small', hectares=hectares, min=settings.min_custom_aoi_hectares))
    elif hectares > settings.warn_custom_aoi_hectares:
        warnings.append(make_issue('aoi_large', hectares=hectares))
    return blocking, warnings


def check_drawn(req: WildfireRequest, settings: Settings) -> tuple[list | None, float | None, list[Issue], list[Issue]]:
    """Pure-Python checks (no Earth Engine): returns (ring, hectares, blocking, warnings)."""
    check = validate_polygon(req.geometry.coordinates, settings.max_polygon_vertices)  # type: ignore[union-attr]
    if check.ring is None:
        return None, None, [make_issue(code, **params) for code, params in check.issues], []
    blocking, warnings = custom_limit_issues(float(check.hectares or 0), settings)
    return check.ring, float(check.hectares or 0), blocking, warnings


def build_drawn(ring: list[list[float]], hectares: float) -> DrawnAOI:
    ensure_initialized()
    return DrawnAOI(
        ring=ring, hectares=hectares, geometry=ee.Geometry.Polygon([ring], None, False),
        boundary={'type': 'Feature', 'properties': {}, 'geometry': {'type': 'Polygon', 'coordinates': [ring]}},
        bounds=ring_bounds(ring))
