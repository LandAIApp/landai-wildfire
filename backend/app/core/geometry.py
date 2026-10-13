"""Pure-Python polygon helpers for user-drawn areas (no Earth Engine calls).

Validating and measuring a drawn polygon here lets the API reject an oversized or invalid
area before spending any Earth Engine quota. The area formula is the same spherical
(Chamberlain-Duquette) one used by the frontend, so the live meter and the server agree.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

EARTH_RADIUS_M = 6378137.0

Ring = list[list[float]]


def ring_area_hectares(ring: Ring) -> float:
    """Spherical area of a closed lon/lat ring, in hectares."""
    total = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(ring, ring[1:]):
        total += math.radians(lon2 - lon1) * (2 + math.sin(math.radians(lat1)) + math.sin(math.radians(lat2)))
    return abs(total * EARTH_RADIUS_M ** 2 / 2) / 10_000


def _orient(p, q, r) -> float:
    return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])


def _on_segment(p, q, r) -> bool:
    return min(p[0], r[0]) <= q[0] <= max(p[0], r[0]) and min(p[1], r[1]) <= q[1] <= max(p[1], r[1])


def _segments_intersect(p1, q1, p2, q2) -> bool:
    o1, o2 = _orient(p1, q1, p2), _orient(p1, q1, q2)
    o3, o4 = _orient(p2, q2, p1), _orient(p2, q2, q1)
    if o1 * o2 < 0 and o3 * o4 < 0:
        return True
    return ((o1 == 0 and _on_segment(p1, p2, q1)) or (o2 == 0 and _on_segment(p1, q2, q1))
            or (o3 == 0 and _on_segment(p2, p1, q2)) or (o4 == 0 and _on_segment(p2, q1, q2)))


def has_self_intersection(ring: Ring) -> bool:
    """True when any two non-adjacent edges of the closed ring touch or cross."""
    n = len(ring) - 1
    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue
            if _segments_intersect(ring[i], ring[i + 1], ring[j], ring[j + 1]):
                return True
    return False


def normalize_ring(positions: list[list[float]]) -> Ring:
    """Drop altitude and consecutive duplicates, then close the ring."""
    ring: Ring = []
    for position in positions:
        point = [float(position[0]), float(position[1])]
        if not ring or point != ring[-1]:
            ring.append(point)
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring.pop()
    if ring:
        ring.append(list(ring[0]))
    return ring


def ring_bounds(ring: Ring) -> list[list[float]]:
    """[[south, west], [north, east]] (Leaflet order)."""
    lons, lats = [p[0] for p in ring], [p[1] for p in ring]
    return [[min(lats), min(lons)], [max(lats), max(lons)]]


@dataclass
class PolygonCheck:
    ring: Ring | None = None
    hectares: float | None = None
    issues: list[tuple[str, dict]] = field(default_factory=list)


def validate_polygon(coordinates: list[list[list[float]]], max_vertices: int) -> PolygonCheck:
    """Validate a GeoJSON Polygon (single ring). Issues are (code, params) pairs."""
    check = PolygonCheck()
    if len(coordinates) != 1:
        check.issues.append(('geometry_holes', {}))
        return check
    positions = coordinates[0]
    for position in positions:
        lon, lat = position[0], position[1]
        if not (math.isfinite(lon) and math.isfinite(lat) and abs(lon) <= 180 and abs(lat) <= 90):
            check.issues.append(('geometry_out_of_range', {}))
            return check
    ring = normalize_ring(positions)
    vertices = max(len(ring) - 1, 0)
    if vertices < 3:
        check.issues.append(('geometry_too_few_points', {'min': 3}))
        return check
    if vertices > max_vertices:
        check.issues.append(('geometry_too_many_points', {'max': max_vertices, 'count': vertices}))
        return check
    if has_self_intersection(ring):
        check.issues.append(('geometry_self_intersecting', {}))
        return check
    hectares = ring_area_hectares(ring)
    if hectares <= 0:
        check.issues.append(('geometry_degenerate', {}))
        return check
    check.ring, check.hectares = ring, hectares
    return check
