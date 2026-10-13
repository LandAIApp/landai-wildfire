"""Overpass retrieval/parsing with a mocked HTTP transport (no network)."""
import json

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import ExternalSourceError
from app.core.gate import reset_gates
from app.services import osm

BOUNDS = (-74.01, 4.60, -74.00, 4.61)


def settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def square(lon, lat, d=0.0002):
    pts = [(lon, lat), (lon + d, lat), (lon + d, lat + d), (lon, lat + d), (lon, lat)]
    return [{'lon': x, 'lat': y} for x, y in pts]


ELEMENTS = [
    {'type': 'way', 'id': 1, 'tags': {'building': 'house'}, 'geometry': square(-74.005, 4.605)},
    {'type': 'way', 'id': 1, 'tags': {'building': 'house'}, 'geometry': square(-74.005, 4.605)},  # duplicate
    {'type': 'way', 'id': 2, 'tags': {'highway': 'residential'},
     'geometry': [{'lon': -74.01, 'lat': 4.6}, {'lon': -74.0, 'lat': 4.61}]},
    {'type': 'node', 'id': 3, 'lat': 4.603, 'lon': -74.004, 'tags': {'amenity': 'hospital', 'name': 'H'}},
    {'type': 'way', 'id': 4, 'tags': {'amenity': 'school', 'building': 'school'}, 'geometry': square(-74.007, 4.607)},
    {'type': 'way', 'id': 5, 'tags': {'barrier': 'fence'}, 'geometry': square(-74.007, 4.607)},
    {'type': 'relation', 'id': 6, 'tags': {'building': 'yes'}, 'members': []},
]


def transport(handler):
    return httpx.MockTransport(handler)


def test_parse_dedupes_and_categorises():
    data = osm.parse_elements(ELEMENTS)
    assert len(data.buildings) == 2            # house + school building, duplicate removed
    assert len(data.roads) == 1
    assert len(data.health) == 1
    assert len(data.education) == 1            # the school is both a building and an education facility
    assert data.skipped_other == 1 and data.skipped_relations == 1


def test_queries_use_bbox_and_bounded_output():
    count, data = osm.build_queries(BOUNDS, settings())
    assert 'out count' in count and 'out tags geom' in data
    assert '4.600000,-74.010000,4.610000,-74.000000' in data


def test_fetch_ok_uses_post_and_user_agent_and_caches():
    osm.clear_cache(); reset_gates()
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        if b'out+count' in request.content or b'out%20count' in request.content:
            return httpx.Response(200, json={'elements': [{'type': 'count', 'tags': {'total': '10'}}]})
        return httpx.Response(200, json={'elements': ELEMENTS})

    s = settings()
    first = osm.fetch(BOUNDS, s, transport=transport(handler))
    assert not first.from_cache and len(first.buildings) == 2
    assert all(r.method == 'POST' for r in seen) and len(seen) == 2
    assert 'LandAI' in seen[0].headers['user-agent']
    second = osm.fetch(BOUNDS, s, transport=transport(handler))
    assert second.from_cache and len(seen) == 2          # no new HTTP calls


def test_fetch_empty_response_is_valid_but_empty():
    osm.clear_cache(); reset_gates()
    handler = lambda r: httpx.Response(200, json={'elements': []})  # noqa: E731
    data = osm.fetch(BOUNDS, settings(), transport=transport(handler))
    assert data.buildings == [] and data.element_count == 0


@pytest.mark.parametrize('status,code', [(429, 'osm_rate_limited'), (504, 'osm_timeout'), (503, 'osm_unavailable')])
def test_fetch_http_errors_map_to_codes_without_retry(status, code):
    osm.clear_cache(); reset_gates()
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(status)

    with pytest.raises(ExternalSourceError) as exc:
        osm.fetch(BOUNDS, settings(overpass_fallback_endpoints=''), transport=transport(handler))
    assert exc.value.code == code and len(calls) == 1        # a single instance is never retried


def test_fetch_timeout():
    osm.clear_cache(); reset_gates()

    def handler(request):
        raise httpx.ReadTimeout('slow')

    with pytest.raises(ExternalSourceError) as exc:
        osm.fetch(BOUNDS, settings(), transport=transport(handler))
    assert exc.value.code == 'osm_timeout'


def test_fetch_rejects_too_many_elements_before_downloading():
    osm.clear_cache(); reset_gates()
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'elements': [{'type': 'count', 'tags': {'total': '999999'}}]})

    with pytest.raises(ExternalSourceError) as exc:
        osm.fetch(BOUNDS, settings(overpass_max_elements=1000), transport=transport(handler))
    assert exc.value.code == 'osm_too_many_elements' and len(calls) == 1


def test_overpass_runtime_remark_is_treated_as_incomplete():
    osm.clear_cache(); reset_gates()

    def handler(request):
        return httpx.Response(200, json={'elements': [], 'remark': 'runtime error: Query timed out'})

    with pytest.raises(ExternalSourceError) as exc:
        osm.fetch(BOUNDS, settings(), transport=transport(handler))
    assert exc.value.code == 'osm_incomplete'


def test_relation_multipolygon_is_assembled():
    outer = [{'lon': 0, 'lat': 0}, {'lon': 0.001, 'lat': 0}, {'lon': 0.001, 'lat': 0.001},
             {'lon': 0, 'lat': 0.001}, {'lon': 0, 'lat': 0}]
    rel = {'type': 'relation', 'id': 9, 'tags': {'building': 'yes', 'type': 'multipolygon'},
           'members': [{'type': 'way', 'role': 'outer', 'geometry': outer}]}
    data = osm.parse_elements([rel])
    assert len(data.buildings) == 1 and data.buildings[0].geom.geom_type == 'Polygon'


def test_fallback_mirror_is_tried_once_when_the_main_instance_fails():
    osm.clear_cache(); reset_gates()
    hosts = []

    def handler(request):
        hosts.append(request.url.host)
        if request.url.host == 'overpass-api.de':
            return httpx.Response(504)
        body = request.content.decode()
        if 'out+count' in body or 'out%20count' in body or 'out count' in body:
            return httpx.Response(200, json={'elements': [{'type': 'count', 'tags': {'total': '1'}}]})
        return httpx.Response(200, json={'elements': []})

    s = settings(overpass_fallback_endpoints='https://mirror.example.org/api/interpreter',
                 overpass_fallback_pause_s=0)
    data = osm.fetch(BOUNDS, s, transport=transport(handler))
    assert hosts[0] == 'overpass-api.de' and hosts.count('overpass-api.de') == 1     # main: asked once, no retry
    assert 'mirror.example.org' in hosts and data.endpoint == 'https://mirror.example.org/api/interpreter'


def test_all_instances_failing_reports_the_error():
    osm.clear_cache(); reset_gates()
    hosts = []

    def handler(request):
        hosts.append(request.url.host)
        return httpx.Response(504)

    s = settings(overpass_fallback_endpoints='https://m1.example.org/x,https://m2.example.org/x',
                 overpass_fallback_pause_s=0)
    with pytest.raises(ExternalSourceError) as exc:
        osm.fetch(BOUNDS, s, transport=transport(handler))
    assert exc.value.code == 'osm_timeout' and hosts == ['overpass-api.de', 'm1.example.org', 'm2.example.org']


def test_size_limit_is_not_retried_on_mirrors():
    osm.clear_cache(); reset_gates()
    hosts = []

    def handler(request):
        hosts.append(request.url.host)
        return httpx.Response(200, json={'elements': [{'type': 'count', 'tags': {'total': '999999999'}}]})

    s = settings(overpass_fallback_endpoints='https://m1.example.org/x', overpass_fallback_pause_s=0)
    with pytest.raises(ExternalSourceError) as exc:
        osm.fetch(BOUNDS, s, transport=transport(handler))
    assert exc.value.code == 'osm_too_many_elements' and hosts == ['overpass-api.de']
