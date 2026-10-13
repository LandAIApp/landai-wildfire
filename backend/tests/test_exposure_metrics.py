"""Geometric exposure indicators: intersections, metric lengths, no double counting, null-vs-zero."""
import pytest
from shapely.geometry import LineString, Point, Polygon, box

from app.services import exposure_metrics as em
from app.services import spatial
from app.services.osm import OsmData, OsmFeature

CRS = 'EPSG:32618'
# hazard: 0.01 deg box (~1.1 km) in WGS84 -> metric
HAZARD_WGS = box(-74.010, 4.600, -74.000, 4.610)
HAZARD = spatial.to_metric(HAZARD_WGS, CRS)


def sq(lon, lat, d=0.0002):
    return Polygon([(lon, lat), (lon + d, lat), (lon + d, lat + d), (lon, lat + d)])


def f(i, geom, **tags):
    return OsmFeature(key=('way', i), geom=geom, tags={k: str(v) for k, v in tags.items()})


def data(**kw):
    d = OsmData()
    for k, v in kw.items():
        setattr(d, k, v)
    return d


def test_buildings_inside_buffer_outside_and_categories():
    osm = data(buildings=[
        f(1, sq(-74.005, 4.605), building='house'),              # inside
        f(2, sq(-74.0105, 4.605), building="commercial"),        # outside hazard, ~20 m away
        f(3, sq(-74.020, 4.605), building='yes'),                # far away
        f(4, sq(-74.006, 4.606), building='school'),
    ])
    r = em.compute(osm, HAZARD, CRS, buffer_m=100)
    assert r.metrics['buildings_intersecting']['value'] == 2
    assert r.metrics['buildings_within_buffer']['value'] == 3
    cats = r.details['buildings_by_category']
    assert cats['residential']['intersecting'] == 1 and cats['public']['intersecting'] == 1
    assert cats['commercial'] == {'intersecting': 0, 'within_buffer': 1}
    assert len(r.layers['buildings']) == 2


def test_building_touching_boundary_counts_as_intersecting():
    osm = data(buildings=[f(1, sq(-74.0102, 4.605, d=0.0002), building='yes')])  # edge overlaps boundary
    assert em.compute(osm, HAZARD, CRS, buffer_m=0).metrics['buildings_intersecting']['value'] == 1


def test_road_length_in_metres_clipped_and_no_double_counting():
    road = LineString([(-74.020, 4.605), (-73.990, 4.605)])      # crosses the box E-W
    dup = LineString([(-74.020, 4.605), (-73.990, 4.605)])      # same geometry mapped twice
    osm = data(roads=[f(1, road, highway='primary'), f(2, dup, highway='primary')])
    r = em.compute(osm, HAZARD, CRS, buffer_m=0)
    width_m = HAZARD.bounds[2] - HAZARD.bounds[0]
    km = r.metrics['roads_km_intersecting']['value']
    assert km == pytest.approx(width_m / 1000, rel=0.01)           # once, not twice
    assert r.details['roads_km_by_class'] == {'primary': pytest.approx(km, abs=1e-6)}
    assert r.metrics['roads_km_intersecting']['unit'] == 'km'


def test_road_classes_link_merged_and_sorted():
    osm = data(roads=[
        f(1, LineString([(-74.009, 4.601), (-74.001, 4.601)]), highway='residential'),
        f(2, LineString([(-74.009, 4.609), (-74.001, 4.609)]), highway='primary_link'),
    ])
    r = em.compute(osm, HAZARD, CRS, buffer_m=0)
    assert set(r.details['roads_km_by_class']) == {'residential', 'primary'}


def test_facilities_distance_status_and_point_inside_polygon_deduplicated():
    hospital_poly = sq(-74.005, 4.605, d=0.0004)
    osm = data(
        health=[f(1, hospital_poly, amenity='hospital', name='A'),
                OsmFeature(('node', 2), Point(-74.0049, 4.6051), {'amenity': 'hospital', 'name': 'A'}),
                OsmFeature(('node', 3), Point(-74.0108, 4.605), {'amenity': 'clinic', 'name': 'B'})],
        education=[OsmFeature(('node', 4), Point(-74.05, 4.6), {'amenity': 'school'})])
    r = em.compute(osm, HAZARD, CRS, buffer_m=200)
    assert r.metrics['health_intersecting']['value'] == 1          # node inside same polygon not double counted
    assert r.metrics['health_within_buffer']['value'] == 2
    rows = r.details['health_facilities']
    assert rows[0]['distance_m'] == 0 and rows[1]['status'] == 'within_buffer'
    assert r.metrics['education_intersecting']['value'] == 0       # mapped, none exposed -> real zero
    assert r.metrics['education_intersecting']['coverage'] == 'mapped'


def test_missing_osm_data_is_none_not_zero():
    r = em.compute(OsmData(), HAZARD, CRS, buffer_m=100)
    for key in ('buildings_intersecting', 'roads_km_intersecting', 'health_intersecting',
                'education_intersecting', 'buildings_within_buffer'):
        assert r.metrics[key]['value'] is None and r.metrics[key]['coverage'] == 'no_osm_data'
    assert {w['category'] for w in r.warnings if w['code'] == 'osm_no_data'} == {
        'buildings', 'roads', 'health', 'education'}


def test_layer_truncation_is_warned_but_metrics_use_all():
    osm = data(buildings=[f(i, sq(-74.009 + i * 0.0003, 4.605), building='yes') for i in range(10)])
    r = em.compute(osm, HAZARD, CRS, buffer_m=0, max_layer_features=3)
    assert r.metrics['buildings_intersecting']['value'] == 10
    assert any(w['code'] == 'layer_truncated' for w in r.warnings)


def test_building_group_mapping():
    assert em.building_group({'building': 'apartments'}) == 'residential'
    assert em.building_group({'building': 'barn'}) == 'agricultural'
    assert em.building_group({'building': 'unknown_thing'}) == 'other'


def test_shared_proximity_zone_and_skipped_buffer_do_not_change_the_numbers():
    """Performance refactor guard: one pre-built buffer, and no buffer for the sensitivity table, give the same results."""
    from shapely.geometry import box

    from app.services import exposure_metrics
    from test_exposure_service import fp_with, osm_data

    fp = fp_with()
    hazard = fp.footprints['burn072']
    data = osm_data()
    default = exposure_metrics.compute(data, hazard, fp.crs, buffer_m=500)
    zone = hazard.buffer(500, quad_segs=4)
    shared = exposure_metrics.compute(data, hazard, fp.crs, buffer_m=500, zone=zone)
    assert shared.metrics == default.metrics and shared.details == default.details
    no_buffer = exposure_metrics.compute(data, hazard, fp.crs, buffer_m=0, with_layers=False)
    for key in ('buildings_intersecting', 'roads_km_intersecting', 'health_intersecting', 'education_intersecting'):
        assert no_buffer.metrics[key] == default.metrics[key]
