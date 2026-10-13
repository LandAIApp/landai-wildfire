"""Exposure orchestration + API (Earth Engine, Overpass and WorldPop replaced by fakes)."""
import csv
import io

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import LineString, Point, Polygon, box

from app.core.config import Settings
from app.core.errors import ExternalSourceError, NoAffectedAreaError
from app.core.gate import reset_gates
from app.main import create_app
from app.schemas.exposure import ExposureRequest
from app.services import analysis_ref, exposure, exposure_export, footprint, spatial, worldpop
from app.services.osm import OsmData, OsmFeature

S = Settings(_env_file=None)
AOI_WGS = box(-74.03, 4.58, -73.98, 4.63)                     # ~ 30 km2
RING = [list(p) for p in AOI_WGS.exterior.coords]
HAZ_WGS = box(-74.010, 4.600, -74.000, 4.610)                 # ~123 ha


def fp_with(thresholds=('burn072',)):
    crs = spatial.utm_epsg(-74.0, 4.6)
    aoi = spatial.to_metric(AOI_WGS, crs)
    base = spatial.to_metric(HAZ_WGS, crs)
    out = {}
    for i, key in enumerate(('burn035', 'burn050', 'burn060', 'burn072', 'burn085')):
        if key in thresholds or len(thresholds) > 1:
            out[key] = base.buffer((3 - i) * 100) if len(thresholds) > 1 else base
    return footprint.Footprint(crs=crs, pixel_size_m=20, aoi=aoi, footprints=out,
                               pixel_counts={k: 1 for k in out})


def ctx(**kw):
    c = {'mode': 'wildfire_analysis', 'kind': 'drawn', 'aoi_hectares': 3000.0, 'fire_date': '2026-08-05',
         'analysis_end': '2026-08-15', 'model_version': 'V7.6', 'analysis_area_ha': {'wf072': 123.0},
         'date_windows': None, 'department': None, 'municipality': None, 'ring': RING}
    c.update(kw)
    return c


def osm_data():
    d = OsmData(retrieved_at='2026-10-01T00:00:00+00:00', endpoint='https://x', bbox=(0, 0, 1, 1), element_count=5)
    d.buildings = [OsmFeature(('way', 1), box(-74.005, 4.605, -74.0048, 4.6052), {'building': 'house'}),
                   OsmFeature(('way', 2), box(-74.02, 4.62, -74.0198, 4.6202), {'building': 'yes'})]
    d.roads = [OsmFeature(('way', 3), LineString([(-74.02, 4.605), (-73.99, 4.605)]), {'highway': 'primary'})]
    d.health = [OsmFeature(('node', 4), Point(-74.005, 4.602), {'amenity': 'clinic', 'name': 'C'})]
    return d


def pop(*_a, **_k):
    return worldpop.PopulationResult(estimate=321.0, year=2020, resolution='100m', dataset='WorldPop',
                                     api_version='v2', task_id='t', analysis_area_ha=123.0,
                                     simplification={'applied': False, 'vertices_before': 5, 'vertices_after': 5,
                                                     'tolerance_m': 0, 'area_change_pct': 0})


def req(**kw):
    return ExposureRequest(analysis_ref='x' * 30, **kw)


def run(fp=None, osm_fetch=None, pop_fn=pop, request=None, context=None, settings=S):
    return exposure.build_response(request or req(), context or ctx(), fp or fp_with(), settings,
                                   osm_fetch=osm_fetch or (lambda b, s: osm_data()), pop_estimate=pop_fn)


def test_success_all_sources():
    r = run()
    assert r['status'] == 'success' and r['hazard_type'] == 'wildfire'
    m = r['metrics']
    assert m['affected_area_ha'] == pytest.approx(123, rel=0.05)
    assert m['affected_pct_of_aoi'] == pytest.approx(m['affected_area_ha'] / 3000 * 100, abs=0.01)
    assert m['population']['value'] == 321.0 and m['population']['year'] == 2020
    assert m['buildings_intersecting']['value'] == 1 and m['health_intersecting']['value'] == 1
    assert m['roads_km_intersecting']['value'] == pytest.approx(1.1, rel=0.1)
    assert set(r['sources']) == {'earth_observation', 'openstreetmap', 'worldpop'}
    assert 'not confirm physical damage' in r['notice']['en'] and 'no confirma daños' in r['notice']['es']


def test_footprint_layer_is_not_the_aoi():
    r = run()
    foot = spatial.area_ha(spatial.to_metric(__import__('shapely').geometry.shape(
        r['layers']['footprint']['features'][0]['geometry']), 'EPSG:32618'))
    aoi = r['analysis']['aoi_hectares']
    assert foot < aoi / 10 and r['layers']['aoi']['features'][0]['properties']['role'] == 'study_area'


def test_population_failure_gives_partial_and_unavailable_not_zero():
    def boom(*a, **k):
        raise ExternalSourceError('WorldPop did not answer in time.', code='worldpop_timeout', status_code=504)
    r = run(pop_fn=boom)
    assert r['status'] == 'partial'
    assert r['metrics']['population']['value'] is None and r['metrics']['population']['status'] == 'unavailable'
    assert r['sources']['worldpop']['status'] == 'error' and r['sources']['openstreetmap']['status'] == 'success'
    assert r['metrics']['buildings_intersecting']['value'] == 1           # OSM still rendered


def test_osm_failure_gives_partial_with_unavailable_metrics():
    def boom(*a, **k):
        raise ExternalSourceError('OSM down', code='osm_unavailable')
    r = run(osm_fetch=boom)
    assert r['status'] == 'partial' and r['metrics']['population']['value'] == 321.0
    for key in ('buildings_intersecting', 'roads_km_intersecting', 'health_intersecting', 'education_intersecting'):
        assert r['metrics'][key]['value'] is None and r['metrics'][key]['coverage'] == 'unavailable'
    assert any(w['code'] == 'source_failed' for w in r['warnings'])


def test_unexpected_exception_in_a_source_is_contained():
    def boom(*a, **k):
        raise RuntimeError('bug')
    r = run(pop_fn=boom)
    assert r['status'] == 'partial' and r['sources']['worldpop']['error']['code'] == 'internal_error'


def test_population_skipped_on_request():
    r = run(request=req(include_population=False), pop_fn=lambda *a, **k: pytest.fail('called'))
    assert r['status'] == 'success' and r['sources']['worldpop']['status'] == 'skipped'


def test_sensitivity_table_covers_all_thresholds_and_marks_selected():
    r = run(fp=fp_with(('burn035', 'burn050', 'burn060', 'burn072', 'burn085')))
    rows = r['sensitivity']
    assert [x['key'] for x in rows] == ['wf035', 'wf050', 'wf060', 'wf072', 'wf085']
    assert [x['selected'] for x in rows] == [False, False, False, True, False]
    assert rows[0]['area_ha'] > rows[-1]['area_ha']


def test_empty_footprint_is_a_clear_error():
    fp = fp_with()
    fp.footprints['burn072'] = Polygon()
    with pytest.raises(NoAffectedAreaError):
        run(fp=fp)


def test_invalid_buffer_rejected():
    from app.core.errors import InvalidRequestError
    with pytest.raises(InvalidRequestError):
        run(request=req(buffer_m=99999))


def test_area_mismatch_warning():
    r = run(context=ctx(analysis_area_ha={'wf072': 400.0}))
    assert any(w['code'] == 'footprint_area_mismatch' for w in r['warnings'])


def test_exports_csv_report_geojson():
    r = run()
    rows = list(csv.DictReader(io.StringIO(r['exports']['csv'])))
    by = {x['indicator']: x for x in rows}
    assert by['affected_area_ha']['unit'] == 'ha' and by['population_estimate']['value'] == '321.0'
    assert by['buildings_intersecting']['value'] == '1'
    report = r['exports']['report']
    assert report['notice']['es'] and report['sources']['openstreetmap']['status'] == 'success'
    gj = exposure_export.build_geojson(r['layers'])
    layers = {f['properties']['layer'] for f in gj['features']}
    assert {'aoi', 'footprint', 'buildings', 'roads', 'health'} <= layers


def test_csv_marks_unavailable_not_zero():
    def boom(*a, **k):
        raise ExternalSourceError('x', code='osm_unavailable')
    r = run(osm_fetch=boom, pop_fn=boom)
    by = {x['indicator']: x for x in csv.DictReader(io.StringIO(r['exports']['csv']))}
    assert by['buildings_intersecting']['value'] == '' and by['buildings_intersecting']['status'] == 'unavailable'
    assert by['population_estimate']['value'] == '' and by['population_estimate']['status'] == 'unavailable'


# --- external hazard polygon mode -------------------------------------------------------------------
def external_request(hazard=None):
    hazard = hazard or HAZ_WGS
    return ExposureRequest(hazard_geometry={'type': 'Polygon', 'coordinates': [[list(p) for p in hazard.exterior.coords]]},
                           aoi_geometry={'type': 'Polygon', 'coordinates': [RING]})


def test_external_mode_is_clearly_identified_and_runs():
    request = external_request()
    c, fp, warnings = exposure._external_footprint(request, S)
    r = exposure.build_response(request, c, fp, S, extra_warnings=warnings,
                                osm_fetch=lambda b, s: osm_data(), pop_estimate=pop)
    assert r['mode'] == 'external_polygon' and r['analysis']['threshold'] is None
    assert r['metrics']['affected_area_ha'] == pytest.approx(123, rel=0.05) and r['sensitivity'] == []


def test_external_hazard_outside_aoi_is_reported_not_silent():
    far = box(-73.9, 4.6, -73.8, 4.7)
    inside_and_out = box(-74.0, 4.6, -73.95, 4.61)          # half outside
    request = external_request(inside_and_out)
    _c, _fp, warnings = exposure._external_footprint(request, S)
    assert warnings and warnings[0]['code'] == 'hazard_clipped_to_aoi'
    with pytest.raises(NoAffectedAreaError):
        exposure._external_footprint(external_request(far), S)


def test_request_modes_are_exclusive():
    with pytest.raises(ValueError):
        ExposureRequest()
    with pytest.raises(ValueError):
        ExposureRequest(analysis_ref='x' * 30, hazard_geometry={'type': 'Polygon', 'coordinates': [[[0, 0], [1, 0], [1, 1], [0, 0]]]})
    with pytest.raises(ValueError):
        ExposureRequest(hazard_geometry={'type': 'Polygon', 'coordinates': [[[0, 0], [1, 0], [1, 1], [0, 0]]]})


# --- API -------------------------------------------------------------------------------------------
@pytest.fixture
def api(monkeypatch):
    reset_gates()
    monkeypatch.setattr(exposure, '_resolve_earth_engine', lambda c, keys, s: fp_with(tuple(keys)))
    monkeypatch.setattr(exposure.osm, 'fetch', lambda b, s, transport=None, region=None: osm_data())
    monkeypatch.setattr(exposure.worldpop, 'estimate', pop)
    return TestClient(create_app(), raise_server_exceptions=False)


def token(**over):
    payload = {'kind': 'drawn', 'fire_date': '2026-08-05', 'analysis_end': '2026-08-15', 'aoi_hectares': 3000.0,
               'model_version': 'V7.6', 'area_ha': {'wf072': 123.0}, 'ring': RING, 'date_windows': None}
    payload.update(over)
    return analysis_ref.issue(payload)


def test_endpoint_success(api):
    r = api.post('/api/v1/exposure/analyze', json={'analysis_ref': token(), 'threshold': 0.72})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['status'] == 'success' and body['mode'] == 'wildfire_analysis' and 'metrics' in body


def test_endpoint_rejects_forged_or_garbage_reference(api):
    r = api.post('/api/v1/exposure/analyze', json={'analysis_ref': 'x' * 40})
    assert r.status_code == 422 and r.json()['code'] == 'invalid_analysis_ref'


def test_endpoint_rejects_oversized_exposure_area(api):
    r = api.post('/api/v1/exposure/analyze', json={'analysis_ref': token(aoi_hectares=90000.0)})
    assert r.status_code == 422 and r.json()['code'] == 'exposure_aoi_too_large'


def test_endpoint_rejects_bad_threshold(api):
    r = api.post('/api/v1/exposure/analyze', json={'analysis_ref': token(), 'threshold': 0.4})
    assert r.status_code == 422


def test_endpoint_rejects_client_supplied_polygon_with_reference(api):
    r = api.post('/api/v1/exposure/analyze', json={
        'analysis_ref': token(), 'hazard_geometry': {'type': 'Polygon', 'coordinates': [[[0, 0], [1, 0], [1, 1], [0, 0]]]}})
    assert r.status_code == 422


def test_concurrency_gate_returns_busy(api):
    from app.core.gate import slot
    with slot('exposure', 1):
        r = api.post('/api/v1/exposure/analyze', json={'analysis_ref': token()})
    assert r.status_code == 503 and r.json()['code'] == 'server_busy'


def test_public_config_exposes_authoritative_limits_without_secrets(api):
    body = api.get('/api/v1/config').json()
    assert body['aoi']['custom']['max_hectares'] == 100000
    assert body['aoi']['municipality']['max_hectares'] == 500000
    assert body['exposure']['max_aoi_hectares'] == 50000
    assert body['rate_limits']['exposure'] and 'key' not in str(body).lower().replace('max_layer', '')


def test_rate_limit_returns_429_with_retry_after(api):
    from app.core.rate_limit import limiter
    limiter.reset()
    codes = [api.post('/api/v1/exposure/analyze', json={'analysis_ref': 'x' * 40}) for _ in range(12)]
    limited = [r for r in codes if r.status_code == 429]
    assert limited and limited[0].json()['code'] == 'rate_limit_exceeded'
    assert int(limited[0].headers['retry-after']) > 0
    assert limited[0].json()['details']['retry_after_seconds'] > 0
    limiter.reset()
