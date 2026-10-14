"""Custom (drawn) AOI: schema, validation, limits, preflight and analysis wiring (Earth Engine mocked)."""
from datetime import date
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app
from app.schemas.wildfire import DateRange, DateWindows, PreflightResponse, WildfireRequest
from app.services import analysis, aoi as aoi_service, preflight

DATES = {'fire_date': date(2026, 8, 5), 'analysis_end': date(2026, 8, 15)}
SQUARE = {'type': 'Polygon', 'coordinates': [[[-75.0, 4.0], [-74.97, 4.0], [-74.97, 4.03], [-75.0, 4.03], [-75.0, 4.0]]]}


def drawn(geometry=SQUARE, **kw):
    return WildfireRequest(geometry=geometry, **DATES, **kw)


def test_municipality_request_still_valid():
    r = WildfireRequest(department='Tolima', municipality='San Luis', **DATES)
    assert r.aoi_kind == 'municipality'


@pytest.mark.parametrize('extra', [
    {'department': 'Tolima', 'municipality': 'San Luis'},     # both modes
    {},                                                       # neither
    {'department': 'Tolima'},                                 # half municipality
])
def test_conflicting_or_missing_area_selection_rejected(extra):
    with pytest.raises(ValidationError):
        WildfireRequest(geometry=SQUARE if extra.get('municipality') else None, **extra, **DATES) \
            if extra.get('municipality') else WildfireRequest(**extra, **DATES)


def test_multipolygon_is_rejected_by_schema():
    with pytest.raises(ValidationError):
        drawn({'type': 'MultiPolygon', 'coordinates': [SQUARE['coordinates']]})


S = Settings(_env_file=None)


def test_valid_polygon_area_in_hectares():
    ring, hectares, blocking, warnings = aoi_service.check_drawn(drawn(), S)
    assert ring is not None and not blocking
    assert 1000 < hectares < 1200                      # ~3.3 km x 3.3 km


def test_too_large_is_blocked_never_truncated():
    big = {'type': 'Polygon', 'coordinates': [[[-75, 4], [-73, 4], [-73, 6], [-75, 6], [-75, 4]]]}
    ring, hectares, blocking, _ = aoi_service.check_drawn(drawn(big), Settings(_env_file=None))
    assert [b.code for b in blocking] == ['aoi_too_large'] and blocking[0].params['max'] == 100000


def test_too_small_and_warning_band():
    tiny = {'type': 'Polygon', 'coordinates': [[[-75, 4], [-74.9995, 4], [-74.9995, 4.0005], [-75, 4.0005], [-75, 4]]]}
    _r, _h, blocking, _w = aoi_service.check_drawn(drawn(tiny), S)
    assert [b.code for b in blocking] == ['aoi_too_small']
    s = Settings(_env_file=None, max_custom_aoi_hectares=2000, warn_custom_aoi_hectares=500)
    _r, _h, blocking, warnings = aoi_service.check_drawn(drawn(), s)
    assert not blocking and [w.code for w in warnings] == ['aoi_large']


@pytest.mark.parametrize('coords,code', [
    ([[[-75, 4], [-74.9, 4.1], [-74.9, 4], [-75, 4.1], [-75, 4]]], 'geometry_self_intersecting'),
    ([[[-75, 4], [-74, 4], [-75, 4]]], 'geometry_too_few_points'),
    ([[[-75, 4], [-75, 4.1], [-75, 4.2], [-75, 4]]], 'geometry_degenerate'),
    ([[[-200, 4], [-199, 4], [-199, 5], [-200, 4]]], 'geometry_out_of_range'),
    ([[[-75, 4], [-74, 4], [-74, 5], [-75, 4]], [[-74.8, 4.1], [-74.7, 4.1], [-74.7, 4.2], [-74.8, 4.1]]], 'geometry_holes'),
])
def test_invalid_geometries_have_specific_codes(coords, code):
    _r, _h, blocking, _w = aoi_service.check_drawn(drawn({'type': 'Polygon', 'coordinates': coords}), S)
    assert code in [b.code for b in blocking]


def test_too_many_vertices():
    import math
    n = 500
    ring = [[-75 + 0.01 * math.cos(2 * math.pi * i / n), 4 + 0.01 * math.sin(2 * math.pi * i / n)] for i in range(n)]
    ring.append(ring[0])
    _r, _h, blocking, _w = aoi_service.check_drawn(drawn({'type': 'Polygon', 'coordinates': [ring]}), S)
    assert 'geometry_too_many_points' in [b.code for b in blocking]


def test_non_finite_coordinates_rejected_by_json_layer():
    client = TestClient(create_app(), raise_server_exceptions=False)
    body = {'geometry': {'type': 'Polygon', 'coordinates': [[[-75, 4], [-74, 4], [-74, 5], [-75, 4]]]},
            'fire_date': '2026-08-05', 'analysis_end': '2026-08-15'}
    raw = '{"geometry":{"type":"Polygon","coordinates":[[[NaN,4],[-74,4],[-74,5],[NaN,4]]]},"fire_date":"2026-08-05","analysis_end":"2026-08-15"}'
    r = client.post('/api/v1/wildfire/preflight', content=raw, headers={'content-type': 'application/json'})
    assert r.status_code in (400, 422) or (r.json()['valid'] is False and
                                           r.json()['blocking_errors'][0]['code'] == 'geometry_out_of_range')
    assert client.post('/api/v1/wildfire/preflight', json={**body, 'department': 'a', 'municipality': 'b'}).status_code == 422


def ok_availability():
    return {'preScenes': 5, 'postScenes': 3, 'historyScenes': 10, 'preStart': 'a', 'preEnd': 'b', 'postStart': 'c',
            'postEnd': 'd', 'historyStart': 'e', 'historyEnd': 'f'}


@pytest.fixture
def ee_mocks(monkeypatch):
    monkeypatch.setattr(preflight, 'ee', MagicMock())
    monkeypatch.setattr(preflight, 'evaluate', lambda *a, **k: ok_availability())
    monkeypatch.setattr(preflight, 'get_input_availability', lambda *a, **k: MagicMock())
    monkeypatch.setattr(aoi_service, 'build_drawn', lambda ring, ha: MagicMock(geometry=MagicMock(), ring=ring))


def test_preflight_drawn_ok(ee_mocks):
    out = preflight.run_preflight(drawn())
    assert out.valid and out.aoi_kind == 'drawn' and 1000 < out.aoi_hectares < 1200


def test_preflight_drawn_invalid_does_not_call_earth_engine(monkeypatch):
    called = []
    monkeypatch.setattr(preflight, 'evaluate', lambda *a, **k: called.append(1))
    big = {'type': 'Polygon', 'coordinates': [[[-75, 4], [-73, 4], [-73, 6], [-75, 6], [-75, 4]]]}
    out = preflight.run_preflight(drawn(big))
    assert not out.valid and not called


def test_analysis_with_drawn_aoi_returns_signed_reference(monkeypatch):
    from app.services import analysis_ref
    monkeypatch.setattr(analysis, 'ee', MagicMock())
    pre = PreflightResponse(status='ok', valid=True, pre_count=5, post_count=3, history_count=9, aoi_hectares=1100.0,
                            aoi_kind='drawn', date_windows=DateWindows(pre=DateRange(), post=DateRange(), history=DateRange()))
    monkeypatch.setattr(analysis, 'run_preflight', lambda r: pre)
    monkeypatch.setattr(aoi_service, 'build_drawn', lambda ring, ha: MagicMock(
        geometry=MagicMock(), ring=ring, boundary={'type': 'Feature', 'properties': {}, 'geometry': {}},
        bounds=[[4.0, -75.0], [4.03, -74.97]]))
    monkeypatch.setattr(analysis, 'run_burn_model', lambda *a, **k: {'trainingCounts': 'C', 'areaStatistics': 'A'})
    monkeypatch.setattr(analysis, 'build_layers', lambda r: ([], []))
    vals = {'C': {'positive': 500, 'negative': 900},
            'A': {'wf035': 10.0, 'wf050': 8.0, 'wf060': 6.0, 'wf072': 4.0, 'wf085': 1.0}}
    monkeypatch.setattr(analysis, 'evaluate', lambda obj, what='x': vals[obj])
    out = analysis.run_analysis(drawn())
    assert out.metadata['aoi_kind'] == 'drawn' and out.aoi['kind'] == 'drawn'
    payload = analysis_ref.verify(out.analysis_ref)
    assert payload['ring'][0] == [-75.0, 4.0] and payload['area_ha']['wf072'] == 4.0
