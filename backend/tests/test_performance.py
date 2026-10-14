"""Cost/performance protections: caches, single-flight, kill switches, live stages, concurrency gates."""
import threading
import time
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.core import progress
from app.core.config import Settings
from app.core.errors import ServerBusyError, ServicePausedError
from app.core.gate import slot
from app.core.memo import Memo, fingerprint
from app.main import create_app
from app.schemas.exposure import ExposureRequest
from app.schemas.wildfire import WildfireRequest
from app.services import analysis, exposure
from test_exposure_service import RING, fp_with, osm_data, pop, token

S = Settings(_env_file=None)
PID = 'abcdefghijklmnop1234'


# --- Memo (bounded cache + single-flight) -----------------------------------------------------------
def test_memo_hits_and_expires_and_is_bounded():
    now = [0.0]
    memo = Memo(max_items=2)
    memo._cache._clock = lambda: now[0]
    calls = []
    compute = lambda k: (lambda: calls.append(k) or k)  # noqa: E731
    assert memo.get_or_compute('a', compute('a'), ttl=10) == ('a', 'computed')
    assert memo.get_or_compute('a', compute('a'), ttl=10) == ('a', 'hit')
    memo.get_or_compute('b', compute('b'), ttl=10)
    memo.get_or_compute('c', compute('c'), ttl=10)           # evicts 'a' (max 2 items)
    assert memo.get('a') is None and memo.get('c') == 'c'
    now[0] = 11
    assert memo.get('c') is None                              # TTL


def test_memo_does_not_cache_when_ttl_zero_or_not_cacheable():
    memo = Memo(max_items=2)
    memo.get_or_compute('a', lambda: 1, ttl=0)
    assert memo.get('a') is None
    memo.get_or_compute('b', lambda: 2, ttl=10, cacheable=lambda v: False)
    assert memo.get('b') is None


def test_memo_runs_identical_concurrent_requests_once_and_shares_errors():
    memo = Memo(max_items=2)
    started, release, runs = threading.Event(), threading.Event(), []

    def slow():
        runs.append(1)
        started.set()
        release.wait(5)
        return 'value'

    results = []
    leader = threading.Thread(target=lambda: results.append(memo.get_or_compute('k', slow, ttl=0)))
    leader.start()
    started.wait(5)
    follower = threading.Thread(target=lambda: results.append(memo.get_or_compute('k', slow, ttl=0)))
    follower.start()
    time.sleep(0.1)
    release.set()
    leader.join(5), follower.join(5)
    assert len(runs) == 1 and sorted(h for _v, h in results) == ['computed', 'shared']

    def boom():
        raise ServerBusyError('x')
    with pytest.raises(ServerBusyError):
        memo.get_or_compute('e', boom, ttl=10)
    assert memo.get('e') is None                               # failures are never cached


def test_fingerprint_changes_with_any_part():
    base = fingerprint('x', {'ring': [[0, 0]]}, 0.72, 500)
    assert base == fingerprint('x', {'ring': [[0, 0]]}, 0.72, 500)
    assert base != fingerprint('x', {'ring': [[0, 1]]}, 0.72, 500)
    assert base != fingerprint('x', {'ring': [[0, 0]]}, 0.85, 500)
    assert base != fingerprint('x', {'ring': [[0, 0]]}, 0.72, 600)


# --- Exposure: footprint + result caches ------------------------------------------------------------------
@pytest.fixture
def counted(monkeypatch):
    calls = {'ee': [], 'osm': 0, 'pop': 0}

    def ee(ctx, keys, settings):
        calls['ee'].append(sorted(keys))
        return fp_with(tuple(keys))

    def osm_fetch(b, s, transport=None, region=None, on_progress=None):
        calls['osm'] += 1
        calls['bounds'] = b
        if on_progress:
            on_progress(1, 1)
        return osm_data()

    def population(*a, **k):
        calls['pop'] += 1
        return pop()

    monkeypatch.setattr(exposure, '_resolve_earth_engine', ee)
    monkeypatch.setattr(exposure.osm, 'fetch', osm_fetch)
    monkeypatch.setattr(exposure.worldpop, 'estimate', population)
    return calls


def run_ref(**kw):
    return exposure.analyze(ExposureRequest(analysis_ref=token(), **kw), S)


def test_identical_request_is_served_from_the_result_cache(counted):
    first = run_ref(threshold=0.72)
    second = run_ref(threshold=0.72)
    assert counted['ee'] == [['burn035', 'burn050', 'burn060', 'burn072', 'burn085']] and counted['osm'] == 1 and counted['pop'] == 1
    assert first.analysis['processing']['served_from_cache'] is False
    assert second.analysis['processing']['served_from_cache'] is True
    assert second.metrics == first.metrics and second.analysis['generated_at'] == first.analysis['generated_at']


def test_other_threshold_or_buffer_never_reuses_a_result_but_reuses_the_footprint(counted):
    a = run_ref(threshold=0.72)
    b = run_ref(threshold=0.85)
    c = run_ref(threshold=0.72, buffer_m=900)
    assert len(counted['ee']) == 1                              # one Earth Engine download for the three runs
    assert counted['osm'] == 3
    assert b.analysis['threshold'] == 0.85 and c.analysis['buffer_m'] == 900
    assert all(r.analysis['processing']['served_from_cache'] is False for r in (a, b, c))
    assert b.metrics['affected_area_ha'] != a.metrics['affected_area_ha'] or b.analysis['threshold'] != a.analysis['threshold']


def test_other_analysis_does_not_share_cache(counted):
    exposure.analyze(ExposureRequest(analysis_ref=token(), threshold=0.72), S)
    exposure.analyze(ExposureRequest(analysis_ref=token(analysis_end='2026-08-20'), threshold=0.72), S)
    assert len(counted['ee']) == 2


def test_footprint_cache_is_extended_when_more_thresholds_are_needed(counted):
    run_ref(threshold=0.72, include_sensitivity=False)
    run_ref(threshold=0.72, include_sensitivity=True)
    assert counted['ee'] == [['burn072'], ['burn035', 'burn050', 'burn060', 'burn072', 'burn085']]
    run_ref(threshold=0.85, include_sensitivity=False)
    assert len(counted['ee']) == 2                              # served from the extended footprint


def test_osm_area_ignores_other_thresholds_when_sensitivity_is_off(counted):
    run_ref(threshold=0.85, include_sensitivity=True)
    wide = counted['bounds']
    exposure.reset_caches()
    run_ref(threshold=0.85, include_sensitivity=True)           # footprints cached by the previous call are gone
    run_ref(threshold=0.85, include_sensitivity=False)
    narrow = counted['bounds']
    assert (narrow[2] - narrow[0]) <= (wide[2] - wide[0]) and (narrow[3] - narrow[1]) <= (wide[3] - wide[1])


def test_partial_results_are_not_cached(monkeypatch, counted):
    from app.core.errors import ExternalSourceError

    def failing(*a, **k):
        raise ExternalSourceError('down', code='osm_timeout')
    monkeypatch.setattr(exposure.osm, 'fetch', failing)
    first = run_ref()
    assert first.status == 'partial'
    monkeypatch.setattr(exposure.osm, 'fetch', lambda *a, **k: osm_data())
    second = run_ref()
    assert second.status == 'success' and second.analysis['processing']['served_from_cache'] is False
    assert len(counted['ee']) == 1                              # the footprint was still reusable


def test_concurrent_identical_exposure_requests_compute_once(counted, monkeypatch):
    gate, released = threading.Event(), threading.Event()
    real = exposure.osm.fetch

    def slow(*a, **k):
        gate.set()
        released.wait(5)
        return real(*a, **k)
    monkeypatch.setattr(exposure.osm, 'fetch', slow)
    out = []
    t1 = threading.Thread(target=lambda: out.append(run_ref()))
    t1.start()
    gate.wait(5)
    t2 = threading.Thread(target=lambda: out.append(run_ref()))
    t2.start()
    time.sleep(0.1)
    released.set()
    t1.join(10), t2.join(10)
    assert len(out) == 2 and counted['osm'] == 1 and len(counted['ee']) == 1
    assert sorted(r.analysis['processing']['served_from_cache'] for r in out) == [False, True]


def test_cache_respects_item_bound(counted):
    small = Settings(_env_file=None, exposure_cache_items=1)
    exposure.reset_caches()
    exposure.analyze(ExposureRequest(analysis_ref=token(), threshold=0.72), small)
    exposure.analyze(ExposureRequest(analysis_ref=token(), threshold=0.85), small)
    exposure.analyze(ExposureRequest(analysis_ref=token(), threshold=0.72), small)    # evicted: recomputed
    assert counted['osm'] == 3


def test_stage_timings_are_reported(counted):
    r = run_ref()
    t = r.analysis['processing']['timings_s']
    for key in ('footprint_s', 'prepare_s', 'osm_s', 'population_s', 'sources_s', 'zone_s', 'metrics_s',
                'sensitivity_s', 'layers_s', 'exports_s', 'total_s'):
        assert key in t, key


# --- Kill switches and gates ------------------------------------------------------------------------
def test_exposure_kill_switch(counted):
    with pytest.raises(ServicePausedError):
        exposure.analyze(ExposureRequest(analysis_ref=token()), Settings(_env_file=None, exposure_enabled=False))
    assert counted['osm'] == 0


def test_analysis_kill_switch_and_gate(monkeypatch):
    request = WildfireRequest(department='Tolima', municipality='San Luis', fire_date=date(2026, 8, 5),
                              analysis_end=date(2026, 8, 15))
    monkeypatch.setattr(analysis, '_run_analysis', lambda r, p=None: 'ok')
    assert analysis.run_analysis(request) == 'ok'
    monkeypatch.setattr(analysis, 'get_settings', lambda: Settings(_env_file=None, analysis_enabled=False))
    with pytest.raises(ServicePausedError):
        analysis.run_analysis(request)
    from app.core.gate import reset_gates
    reset_gates()                                   # semaphores keep the limit they were created with
    monkeypatch.setattr(analysis, 'get_settings', lambda: Settings(_env_file=None, analysis_max_concurrent=1))
    with slot('analysis', 1):
        with pytest.raises(ServerBusyError):
            analysis.run_analysis(request)


def test_identical_concurrent_analyses_share_one_computation(monkeypatch):
    request = WildfireRequest(department='Tolima', municipality='San Luis', fire_date=date(2026, 8, 5),
                              analysis_end=date(2026, 8, 15))
    started, release, runs = threading.Event(), threading.Event(), []

    def slow(r, p=None):
        runs.append(1)
        started.set()
        release.wait(5)
        return 'result'
    monkeypatch.setattr(analysis, '_run_analysis', slow)
    out = []
    a = threading.Thread(target=lambda: out.append(analysis.run_analysis(request)))
    a.start()
    started.wait(5)
    b = threading.Thread(target=lambda: out.append(analysis.run_analysis(request)))
    b.start()
    time.sleep(0.1)
    release.set()
    a.join(5), b.join(5)
    assert out == ['result', 'result'] and len(runs) == 1


# --- Live stages ----------------------------------------------------------------------------------------------
def test_progress_reports_real_stages_without_percentages(counted):
    exposure.analyze(ExposureRequest(analysis_ref=token(), progress_id=PID, include_population=False), S)
    snap = progress.snapshot(PID)
    assert snap['finished'] is True
    states = {s['key']: s['state'] for s in snap['stages']}
    assert states == {'earth_observation': 'done', 'openstreetmap': 'done', 'population': 'skipped',
                      'spatial_analysis': 'done', 'response': 'done'}
    assert next(s for s in snap['stages'] if s['key'] == 'openstreetmap')['detail'] == {'cells_done': 1, 'cells_total': 1}
    assert 'percent' not in str(snap).lower()


def test_progress_marks_cached_and_failed_honestly(counted, monkeypatch):
    run_ref()
    exposure.analyze(ExposureRequest(analysis_ref=token(), progress_id=PID), S)
    assert {s['state'] for s in progress.snapshot(PID)['stages']} == {'cached'}
    exposure.reset_caches()

    def boom(*a, **k):
        raise RuntimeError('x')
    monkeypatch.setattr(exposure, '_resolve_earth_engine', boom)
    other = 'zyxwvutsrqponmlk9876'
    with pytest.raises(RuntimeError):
        exposure.analyze(ExposureRequest(analysis_ref=token(), progress_id=other), S)
    states = {s['key']: s['state'] for s in progress.snapshot(other)['stages']}
    assert states['earth_observation'] == 'failed'               # a stage left running is never reported as done


def test_progress_ids_are_validated_and_bounded():
    assert progress.begin('short', ['a']).snapshot()['stages'] == []         # ignored, no-op reporter
    assert progress.snapshot('../etc/passwd') is None
    with pytest.raises(ValueError):
        ExposureRequest(analysis_ref='x' * 30, progress_id='bad id!')
    for i in range(80):
        progress.begin(f'id{i:018d}', ['a'])
    assert progress.snapshot('id' + '0' * 18) is None                       # oldest entries were evicted (max 64)


def test_progress_endpoint(counted):
    client = TestClient(create_app(), raise_server_exceptions=False)
    assert client.get(f'/api/v1/progress/{PID}').status_code == 404
    r = client.post('/api/v1/exposure/analyze', json={'analysis_ref': token(), 'progress_id': PID})
    assert r.status_code == 200
    body = client.get(f'/api/v1/progress/{PID}').json()
    assert body['status'] == 'ok' and body['finished'] is True and len(body['stages']) == 5
    assert client.get('/api/v1/progress/not%20valid').status_code == 404


def test_public_config_reports_service_state_and_limits():
    body = TestClient(create_app()).get('/api/v1/config').json()
    assert body['service']['exposure_enabled'] is True and body['service']['analysis_enabled'] is True
    assert body['service']['max_concurrent_exposure'] == 1


def test_httpx_request_urls_are_not_logged_at_info():
    import logging
    create_app()
    assert logging.getLogger('httpx').level >= logging.WARNING


# ---- part-wise buffer (memory fix: a one-shot buffer of a fragmented raster outline exhausted 2 GiB) ----------------

def _fragmented(n: int = 300):
    import numpy as np
    import shapely
    from shapely.geometry import box
    rng = np.random.default_rng(3)
    cells = []
    for _ in range(n):
        x, y = rng.uniform(0, 4000), rng.uniform(0, 4000)
        w, h = rng.integers(1, 6) * 20, rng.integers(1, 6) * 20
        cells.append(box(x, y, x + w, y + h))
    return shapely.union_all(cells)


def test_buffer_parts_matches_one_shot_buffer():
    from app.services import spatial
    geom = _fragmented()
    assert len(getattr(geom, 'geoms', [geom])) > 5
    expected = geom.buffer(500, quad_segs=4)
    got = spatial.buffer_parts(geom, 500, quad_segs=4)
    assert expected.symmetric_difference(got).area < 1e-3          # m2: same shape
    assert abs(expected.area - got.area) < 1e-3


def test_buffer_parts_edge_cases():
    from shapely.geometry import Polygon, box
    from app.services import spatial
    assert spatial.buffer_parts(Polygon(), 500).is_empty
    single = box(0, 0, 100, 100)
    assert spatial.buffer_parts(single, 50).equals(single.buffer(50, quad_segs=4))
    assert spatial.buffer_parts(single, 0) is single               # no buffer requested: returned untouched
