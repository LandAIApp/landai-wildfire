"""Exposure metrics: intersect OpenStreetMap features with the satellite-derived affected footprint.

Everything here is pure geometry on shapely objects (no network, no Earth Engine) so it is fully unit-testable.

Definitions (also in docs/exposure-methodology.md):
* ``intersecting``  = the feature physically touches/overlaps the affected footprint (shapely ``intersects``).
* ``within_buffer`` = the feature touches the footprint buffered by ``buffer_m`` metres (inclusive of the
  intersecting ones). The buffer is a proximity indicator, NOT a damage zone.
* Road lengths are metres of the UNION of the geometries clipped to the footprint (no double counting of
  overlapping ways), computed in a projected CRS.
* A category without a single OSM feature in the whole study area is reported as ``None`` /
  ``coverage='no_osm_data'`` – never as a confirmed zero.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import shapely
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from . import spatial
from .osm import OsmData, OsmFeature

BUILDING_GROUPS = {
    'residential': {'residential', 'house', 'apartments', 'detached', 'semidetached_house', 'terrace',
                    'bungalow', 'dormitory', 'cabin', 'farm', 'static_caravan', 'hut'},
    'commercial': {'commercial', 'retail', 'office', 'supermarket', 'kiosk', 'hotel', 'warehouse'},
    'industrial': {'industrial', 'factory', 'manufacture', 'service'},
    'public': {'public', 'civic', 'government', 'school', 'kindergarten', 'college', 'university',
               'hospital', 'clinic', 'church', 'chapel', 'cathedral', 'mosque', 'temple', 'religious',
               'fire_station', 'train_station', 'transportation'},
    'agricultural': {'barn', 'stable', 'cowshed', 'greenhouse', 'farm_auxiliary', 'agricultural',
                     'sty', 'silo'},
}
BUILDING_ORDER = ['residential', 'commercial', 'industrial', 'public', 'agricultural', 'other']
ROAD_ORDER = ['motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'unclassified', 'residential',
              'service', 'living_street', 'track', 'road']


def building_group(tags: dict[str, str]) -> str:
    value = tags.get('building', 'yes')
    for group, values in BUILDING_GROUPS.items():
        if value in values:
            return group
    return 'other'


def road_class(tags: dict[str, str]) -> str:
    value = tags.get('highway', 'road')
    return value[:-5] if value.endswith('_link') else value


@dataclass
class Metric:
    value: float | int | None
    coverage: str = 'mapped'          # mapped | no_osm_data
    unit: str = ''

    def as_dict(self) -> dict:
        return {'value': self.value, 'coverage': self.coverage, 'unit': self.unit}


@dataclass
class ExposureMetrics:
    metrics: dict = field(default_factory=dict)
    details: dict = field(default_factory=dict)
    # exposed geometries in WGS84 with properties, for the map layers / GeoJSON export
    layers: dict[str, list[tuple[BaseGeometry, dict]]] = field(default_factory=dict)
    warnings: list[dict] = field(default_factory=list)


def _metric_geoms(features: list[OsmFeature], crs: str) -> list[BaseGeometry]:
    return [spatial.to_metric(f.geom, crs) for f in features]


def _flags(geoms: list[BaseGeometry], hazard, zone) -> tuple[list[bool], list[bool]]:
    if not geoms:
        return [], []
    arr = np.array(geoms, dtype=object)
    inter = shapely.intersects(arr, hazard)
    near = shapely.intersects(arr, zone)
    return [bool(v) for v in inter], [bool(v) for v in near]


def compute(osm: OsmData, hazard: BaseGeometry, crs: str, *, buffer_m: float,
            max_layer_features: int = 5000, with_layers: bool = True,
            zone: BaseGeometry | None = None) -> ExposureMetrics:
    """Compute all OSM-based indicators for one footprint (all geometries in the metric ``crs``)."""
    out = ExposureMetrics()
    shapely.prepare(hazard)
    if zone is None:   # callers that already built the proximity zone pass it in (buffering a raw outline is slow)
        zone = spatial.buffer_parts(hazard, buffer_m, quad_segs=4) if buffer_m > 0 else hazard
    shapely.prepare(zone)

    # ---- buildings -----------------------------------------------------------------------
    b_geoms = _metric_geoms(osm.buildings, crs)
    b_in, b_near = _flags(b_geoms, hazard, zone)
    by_cat = {c: {'intersecting': 0, 'within_buffer': 0} for c in BUILDING_ORDER}
    exposed_buildings = []
    footprint_m2 = 0.0
    for feature, geom, hit, near in zip(osm.buildings, b_geoms, b_in, b_near):
        group = building_group(feature.tags)
        if near:
            by_cat[group]['within_buffer'] += 1
        if hit:
            by_cat[group]['intersecting'] += 1
            footprint_m2 += geom.area
            exposed_buildings.append((feature, group))
    no_b = not osm.buildings
    out.metrics['buildings_intersecting'] = Metric(None if no_b else len(exposed_buildings),
                                                   'no_osm_data' if no_b else 'mapped', 'count').as_dict()
    out.metrics['buildings_within_buffer'] = Metric(None if no_b else sum(1 for v in b_near if v),
                                                    'no_osm_data' if no_b else 'mapped', 'count').as_dict()
    out.details['buildings_by_category'] = None if no_b else by_cat
    out.details['buildings_footprint_m2'] = None if no_b else round(footprint_m2, 1)
    out.layers['buildings'] = [
        (f.geom, {'osm': f'{f.key[0]}/{f.key[1]}', 'category': g, 'building': f.tags.get('building'),
                  'name': f.tags.get('name')}) for f, g in exposed_buildings]

    # ---- roads (metric union of clipped geometries) ----------------------------------------
    r_geoms = _metric_geoms(osm.roads, crs)
    no_r = not osm.roads
    by_class: dict[str, list[BaseGeometry]] = {}
    by_class_buf: dict[str, list[BaseGeometry]] = {}
    for feature, geom in zip(osm.roads, r_geoms):
        cls = road_class(feature.tags)
        if geom.intersects(hazard):
            by_class.setdefault(cls, []).append(geom.intersection(hazard))
        if geom.intersects(zone):
            by_class_buf.setdefault(cls, []).append(geom.intersection(zone))
    class_km: dict[str, float] = {}
    clipped_all: list[BaseGeometry] = []
    for cls in sorted(by_class, key=lambda c: ROAD_ORDER.index(c) if c in ROAD_ORDER else 99):
        union = unary_union(by_class[cls])
        class_km[cls] = round(union.length / 1000.0, 4)
        clipped_all.append(union)
    total_union = unary_union(clipped_all) if clipped_all else None
    total_km = round(total_union.length / 1000.0, 4) if total_union is not None else 0.0
    buf_union = unary_union([g for lst in by_class_buf.values() for g in lst]) if by_class_buf else None
    buf_km = round(buf_union.length / 1000.0, 4) if buf_union is not None else 0.0
    out.metrics['roads_km_intersecting'] = Metric(None if no_r else total_km,
                                                  'no_osm_data' if no_r else 'mapped', 'km').as_dict()
    out.metrics['roads_km_within_buffer'] = Metric(None if no_r else buf_km,
                                                   'no_osm_data' if no_r else 'mapped', 'km').as_dict()
    out.details['roads_km_by_class'] = None if no_r else class_km
    out.details['roads_class_sum_km'] = None if no_r else round(sum(class_km.values()), 4)
    layer_roads: list[tuple[BaseGeometry, dict]] = []
    for cls, geoms in (by_class.items() if with_layers else []):
        for geom in geoms:
            wgs = spatial.to_wgs84(geom, crs)
            if not wgs.is_empty:
                layer_roads.append((wgs, {'class': cls}))
    out.layers['roads'] = layer_roads

    # ---- facilities ---------------------------------------------------------------------------
    for key, features in (('health', osm.health), ('education', osm.education)):
        facilities = _facility_rows(features, crs, hazard, zone)
        none = not features
        inside = [r for r in facilities if r['status'] == 'intersecting']
        near = [r for r in facilities if r['status'] in ('intersecting', 'within_buffer')]
        out.metrics[f'{key}_intersecting'] = Metric(None if none else len(inside),
                                                    'no_osm_data' if none else 'mapped', 'count').as_dict()
        out.metrics[f'{key}_within_buffer'] = Metric(None if none else len(near),
                                                     'no_osm_data' if none else 'mapped', 'count').as_dict()
        out.details[f'{key}_facilities'] = [
            {k: v for k, v in r.items() if k != 'geom'} for r in sorted(near, key=lambda r: r['distance_m'])
        ][:200] if not none else None
        out.layers[key] = [(r['geom'], {k: v for k, v in r.items() if k not in ('geom',)}) for r in near]

    # ---- warnings -------------------------------------------------------------------------------
    for cat, missing in (('buildings', no_b), ('roads', no_r), ('health', not osm.health),
                         ('education', not osm.education)):
        if missing:
            out.warnings.append({'code': 'osm_no_data', 'category': cat})
    if osm.skipped_relations:
        out.warnings.append({'code': 'osm_relations_skipped', 'count': osm.skipped_relations})
    for name, items in out.layers.items():
        if len(items) > max_layer_features:
            out.warnings.append({'code': 'layer_truncated', 'layer': name, 'total': len(items),
                                 'shown': max_layer_features})
    out.details['osm_features_in_study_area'] = {
        'buildings': len(osm.buildings), 'roads': len(osm.roads),
        'health': len(osm.health), 'education': len(osm.education)}
    return out


def _facility_rows(features: list[OsmFeature], crs: str, hazard, zone) -> list[dict]:
    """One row per facility. A point mapped inside a polygon of the same facility class is dropped
    (the same hospital is often mapped both as a node and as a building)."""
    items = [(f, spatial.to_metric(f.geom, crs)) for f in features]
    polygons = [g for _f, g in items if g.geom_type in ('Polygon', 'MultiPolygon')]
    rows = []
    for feature, geom in items:
        if isinstance(geom, Point) and any(p.contains(geom) for p in polygons):
            continue
        distance = float(geom.distance(hazard))
        status = 'intersecting' if distance == 0 else ('within_buffer' if geom.intersects(zone) else 'outside')
        rows.append({
            'osm': f'{feature.key[0]}/{feature.key[1]}', 'name': feature.tags.get('name'),
            'class': feature.tags.get('amenity') or feature.tags.get('healthcare') or 'facility',
            'distance_m': round(distance, 1), 'status': status,
            'geom': feature.geom})
    return rows
