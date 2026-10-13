"""Metric spatial helpers. Lengths and areas are ALWAYS computed in a projected (UTM) CRS, never in degrees."""
from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
import shapely
from pyproj import Transformer
from shapely.geometry.base import BaseGeometry

WGS84 = 'EPSG:4326'


def utm_epsg(lon: float, lat: float) -> str:
    zone = int((lon + 180) // 6) + 1
    zone = min(max(zone, 1), 60)
    return f"EPSG:{(32600 if lat >= 0 else 32700) + zone}"


@lru_cache(maxsize=64)
def _transformer(src: str, dst: str) -> Transformer:
    return Transformer.from_crs(src, dst, always_xy=True)


def reproject(geom: BaseGeometry, src: str, dst: str) -> BaseGeometry:
    if src == dst:
        return geom
    transformer = _transformer(src, dst)

    def convert(coords: np.ndarray) -> np.ndarray:
        x, y = transformer.transform(coords[:, 0], coords[:, 1])
        return np.column_stack([x, y])

    return shapely.transform(geom, convert)


def to_metric(geom: BaseGeometry, crs: str) -> BaseGeometry:
    return reproject(geom, WGS84, crs)


def to_wgs84(geom: BaseGeometry, crs: str) -> BaseGeometry:
    return reproject(geom, crs, WGS84)


def projected_bbox_size(bounds: tuple[float, float, float, float], crs: str) -> tuple[float, float]:
    """(width_m, height_m) of a lon/lat bbox in a projected CRS."""
    west, south, east, north = bounds
    t = _transformer(WGS84, crs)
    xs, ys = zip(*[t.transform(x, y) for x, y in ((west, south), (east, south), (east, north), (west, north))])
    return max(xs) - min(xs), max(ys) - min(ys)


def area_ha(metric_geom: BaseGeometry) -> float:
    return metric_geom.area / 10_000.0


def count_vertices(geom: BaseGeometry) -> int:
    return int(shapely.get_num_coordinates(geom))


def round_coords(geom: BaseGeometry, decimals: int = 6) -> BaseGeometry:
    return shapely.set_precision(geom, 10 ** -decimals) if decimals else geom


def feature(geom: BaseGeometry, properties: dict | None = None, decimals: int = 6) -> dict:
    """GeoJSON Feature from a WGS84 shapely geometry (coordinates rounded to ~0.1 m)."""
    g = round_coords(geom, decimals)
    return {'type': 'Feature', 'properties': properties or {}, 'geometry': shapely.geometry.mapping(g)}


def is_finite_number(value) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)
