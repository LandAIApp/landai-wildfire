import json

import httpx
import pytest
from shapely.geometry import box

from app.core.config import Settings
from app.core.errors import ExternalSourceError
from app.services import worldpop

CRS = 'EPSG:32618'
HAZARD = box(600000, 500000, 601000, 501000)          # 100 ha


def s(**kw):
    return Settings(_env_file=None, worldpop_poll_interval_s=0.01, worldpop_max_wait_s=1, **kw)


def run(handler, settings=None, **kw):
    worldpop.clear_cache()
    return worldpop.estimate(HAZARD, CRS, settings or s(), transport=httpx.MockTransport(handler),
                             sleep=lambda _x: None, **kw)


def test_async_success_posts_real_polygon_not_bbox():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == 'POST':
            body = json.loads(request.content)
            assert body['year'] == 2020 and body['resolution'] == '100m'
            assert body['geojson']['geometry']['type'] == 'Polygon'
            return httpx.Response(202, json={'status': 'created', 'task_id': 'abc'})
        if len([c for c in calls if c[0] == 'GET']) == 1:
            return httpx.Response(200, json={'status': 'running'})
        return httpx.Response(200, json={'status': 'finished', 'data': {'total_population': 123.45}})

    result = run(handler)
    assert result.estimate == pytest.approx(123.45, abs=0.06)
    assert result.year == 2020 and result.resolution == '100m' and result.task_id == 'abc'
    assert result.analysis_area_ha == 100.0 and not result.simplification['applied']
    assert ('GET', '/v2/tasks/abc') in calls


def test_year_comes_from_config_not_event_date():
    result = run(lambda r: httpx.Response(200, json={'status': 'finished', 'total_population': 5}),
                 s(worldpop_year=2018))
    assert result.year == 2018


def test_failure_task_is_unavailable_not_zero():
    def handler(request):
        if request.method == 'POST':
            return httpx.Response(200, json={'task_id': 'x'})
        return httpx.Response(200, json={'status': 'failed'})

    with pytest.raises(ExternalSourceError) as exc:
        run(handler)
    assert exc.value.code == 'worldpop_task_failed'


def test_bounded_polling_times_out():
    def handler(request):
        if request.method == 'POST':
            return httpx.Response(200, json={'task_id': 'x'})
        return httpx.Response(200, json={'status': 'running'})

    ticks = iter(range(0, 1000))
    with pytest.raises(ExternalSourceError) as exc:
        worldpop.clear_cache()
        worldpop.estimate(HAZARD, CRS, s(), transport=httpx.MockTransport(handler),
                          sleep=lambda _x: None, clock=lambda: next(ticks) * 0.3)
    assert exc.value.code == 'worldpop_timeout'


@pytest.mark.parametrize('status,code', [(429, 'worldpop_rate_limited'), (500, 'worldpop_http_error')])
def test_http_errors(status, code):
    with pytest.raises(ExternalSourceError) as exc:
        run(lambda r: httpx.Response(status))
    assert exc.value.code == code


def test_non_json_is_bad_response():
    with pytest.raises(ExternalSourceError) as exc:
        run(lambda r: httpx.Response(200, text='<html>'))
    assert exc.value.code == 'worldpop_bad_response'


def test_finished_without_value_is_error_not_zero():
    def handler(request):
        if request.method == 'POST':
            return httpx.Response(200, json={'task_id': 'x'})
        return httpx.Response(200, json={'status': 'finished', 'data': {}})

    with pytest.raises(ExternalSourceError):
        run(handler)


def test_cache_avoids_second_request():
    count = []

    def handler(request):
        count.append(1)
        return httpx.Response(200, json={'status': 'finished', 'total_population': 7})

    worldpop.clear_cache()
    t = httpx.MockTransport(handler)
    a = worldpop.estimate(HAZARD, CRS, s(), transport=t)
    b = worldpop.estimate(HAZARD, CRS, s(), transport=t)
    assert len(count) == 1 and b.from_cache and a.estimate == b.estimate == 7


def test_api_key_header_only_when_configured():
    seen = {}

    def handler(request):
        seen['key'] = request.headers.get('x-api-key')
        return httpx.Response(200, json={'status': 'finished', 'total_population': 1})

    run(handler)
    assert seen['key'] is None
    run(handler, s(worldpop_api_key='secret'))
    assert seen['key'] == 'secret'


def test_simplification_is_reported_and_bounded():
    import math
    n = 400
    ring = [(600500 + 400 * math.cos(2 * math.pi * i / n) * (1 + 0.002 * (i % 2)),
             500500 + 400 * math.sin(2 * math.pi * i / n) * (1 + 0.002 * (i % 2))) for i in range(n)]
    from shapely.geometry import Polygon
    poly = Polygon(ring)
    geom, report = worldpop.prepare_geometry(poly, CRS, s(worldpop_max_vertices=100))
    assert report['applied'] and report['vertices_after'] <= 100 and report['vertices_before'] > 100
    assert abs(report['area_change_pct']) < 5
    _g, none = worldpop.prepare_geometry(poly, CRS, s())
    assert not none['applied']


def test_v1_uses_documented_stats_endpoint():
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json={'status': 'finished', 'data': {'total_population': 3}})

    result = run(handler, s(worldpop_api_version='v1'))
    assert paths == ['/v1/services/stats'] and result.api_version == 'v1'
