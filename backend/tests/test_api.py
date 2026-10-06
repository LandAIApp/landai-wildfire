from fastapi.testclient import TestClient

from app.core import earth_engine
from app.core.errors import (
    DepartmentNotFoundError, EarthEngineServiceError, NoTrainingSamplesError,
)
from app.main import create_app
from app.schemas.wildfire import PreflightResponse

import ee

client = TestClient(create_app(), raise_server_exceptions=False)
BODY = {'department': 'Tolima', 'municipality': 'San Luis',
        'fire_date': '2026-08-05', 'analysis_end': '2026-08-15'}


def test_health():
    r = client.get('/health')
    assert r.status_code == 200 and r.json()['status'] == 'ok'


def test_departments(monkeypatch):
    monkeypatch.setattr('app.api.administrative.administrative.list_departments',
                        lambda: ['Antioquia', 'Tolima'])
    assert client.get('/api/v1/administrative/departments').json() == {
        'departments': ['Antioquia', 'Tolima']}


def test_municipalities_unknown_department(monkeypatch):
    def boom(dep):
        raise DepartmentNotFoundError(f"Department '{dep}' was not found.")
    monkeypatch.setattr('app.api.administrative.administrative.list_municipalities', boom)
    r = client.get('/api/v1/administrative/municipalities', params={'department': 'Nada'})
    assert r.status_code == 404 and r.json()['code'] == 'department_not_found'


def test_municipalities_requires_department():
    r = client.get('/api/v1/administrative/municipalities')
    assert r.status_code == 422 and r.json()['code'] == 'invalid_request'


def test_malformed_request_missing_fields():
    r = client.post('/api/v1/wildfire/preflight', json={'department': 'Tolima'})
    assert r.status_code == 422 and r.json()['status'] == 'error'


def test_invalid_date_format():
    r = client.post('/api/v1/wildfire/analyze', json={**BODY, 'fire_date': '05/08/2026'})
    assert r.status_code == 422 and r.json()['code'] == 'invalid_request'


def test_end_before_start():
    r = client.post('/api/v1/wildfire/preflight',
                    json={**BODY, 'fire_date': '2026-08-15', 'analysis_end': '2026-08-05'})
    assert r.status_code == 422 and 'analysis_end' in r.json()['message']


def test_preflight_endpoint(monkeypatch):
    monkeypatch.setattr('app.api.wildfire.run_preflight', lambda r: PreflightResponse(
        status='ok', valid=True, pre_count=5, post_count=2, history_count=9))
    r = client.post('/api/v1/wildfire/preflight', json=BODY)
    assert r.status_code == 200 and r.json()['pre_count'] == 5


def test_analyze_no_samples_maps_to_422(monkeypatch):
    def boom(r):
        raise NoTrainingSamplesError('none')
    monkeypatch.setattr('app.api.wildfire.run_analysis', boom)
    r = client.post('/api/v1/wildfire/analyze', json=BODY)
    assert r.status_code == 422 and r.json()['code'] == 'no_training_samples'


def test_analyze_ee_error_maps_to_502(monkeypatch):
    def boom(r):
        raise EarthEngineServiceError('ee down')
    monkeypatch.setattr('app.api.wildfire.run_analysis', boom)
    r = client.post('/api/v1/wildfire/analyze', json=BODY)
    assert r.status_code == 502 and r.json()['code'] == 'earth_engine_error'


def test_unexpected_error_is_sanitized(monkeypatch):
    def boom(r):
        raise RuntimeError('secret internals')
    monkeypatch.setattr('app.api.wildfire.run_analysis', boom)
    r = client.post('/api/v1/wildfire/analyze', json=BODY)
    assert r.status_code == 500 and 'secret' not in r.text


def test_map_ee_error_classification():
    m = earth_engine.map_ee_error
    assert m(ee.EEException('Computation timed out.'), 'x').status_code == 504
    assert m(ee.EEException('User memory limit exceeded.'), 'x').status_code == 422
    assert m(ee.EEException('Quota exceeded'), 'x').status_code == 429
    assert m(ee.EEException('Asset not found'), 'x').status_code == 502
    assert m(ee.EEException('weird'), 'x').code == 'earth_engine_error'


def test_evaluate_wraps_ee_exception(monkeypatch):
    monkeypatch.setattr(earth_engine, 'ensure_initialized', lambda: None)

    class Obj:
        def getInfo(self):
            raise ee.EEException('Computation timed out.')
    try:
        earth_engine.evaluate(Obj(), 'testing')
    except Exception as exc:  # noqa: BLE001
        assert exc.status_code == 504
    else:
        raise AssertionError('expected error')
