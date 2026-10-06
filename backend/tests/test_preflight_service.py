from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.schemas.wildfire import WildfireRequest
from app.services.preflight import run_preflight

AOI_OK = {'matches': 1, 'area_ha': 25_000.0}


def codes(items):
    return [i.code for i in items]


def test_successful_preflight(mock_preflight_ee, req, avail_ok):
    mock_preflight_ee(AOI_OK, avail_ok)
    r = run_preflight(req)
    assert r.valid and r.status == 'ok'
    assert (r.pre_count, r.post_count, r.history_count) == (12, 4, 30)
    assert r.date_windows.pre.start == '2026-05-07'
    assert r.date_windows.post.end == '2026-08-15'
    assert r.blocking_errors == []


def test_invalid_municipality(mock_preflight_ee, req):
    mock_preflight_ee({'matches': 0, 'area_ha': 0})
    r = run_preflight(req)
    assert not r.valid
    assert codes(r.blocking_errors) == ['municipality_not_found']
    assert r.pre_count is None  # availability never queried


def test_zero_pre_images(mock_preflight_ee, req, avail_ok):
    mock_preflight_ee(AOI_OK, {**avail_ok, 'preScenes': 0})
    r = run_preflight(req)
    assert not r.valid and codes(r.blocking_errors) == ['no_pre_images']


def test_zero_post_images(mock_preflight_ee, req, avail_ok):
    mock_preflight_ee(AOI_OK, {**avail_ok, 'postScenes': 0})
    r = run_preflight(req)
    assert not r.valid and codes(r.blocking_errors) == ['no_post_images']


def test_insufficient_history(mock_preflight_ee, req, avail_ok):
    mock_preflight_ee(AOI_OK, {**avail_ok, 'historyScenes': 1})
    r = run_preflight(req)
    assert not r.valid and codes(r.blocking_errors) == ['insufficient_history']


def test_history_of_exactly_two_is_valid(mock_preflight_ee, req, avail_ok):
    mock_preflight_ee(AOI_OK, {**avail_ok, 'historyScenes': 2})
    assert run_preflight(req).valid


def test_all_three_blocking_errors_are_reported_together(mock_preflight_ee, req, avail_ok):
    mock_preflight_ee(AOI_OK, {**avail_ok, 'preScenes': 0, 'postScenes': 0, 'historyScenes': 0})
    assert set(codes(run_preflight(req).blocking_errors)) == {
        'no_pre_images', 'no_post_images', 'insufficient_history'}


def test_few_scenes_is_only_a_warning(mock_preflight_ee, req, avail_ok):
    mock_preflight_ee(AOI_OK, {**avail_ok, 'preScenes': 1})
    r = run_preflight(req)
    assert r.valid and 'few_scenes' in codes(r.warnings)


def test_oversized_aoi_blocks(mock_preflight_ee, req):
    mock_preflight_ee({'matches': 1, 'area_ha': 5_000_000})
    r = run_preflight(req)
    assert not r.valid and codes(r.blocking_errors) == ['aoi_too_large']


def test_large_aoi_warns(mock_preflight_ee, req, avail_ok):
    mock_preflight_ee({'matches': 1, 'area_ha': 200_000}, avail_ok)
    r = run_preflight(req)
    assert r.valid and 'aoi_large' in codes(r.warnings)


def test_future_date_blocks(mock_preflight_ee):
    future = date.today() + timedelta(days=30)
    r = WildfireRequest(department='A', municipality='B', fire_date=future,
                        analysis_end=future + timedelta(days=2))
    mock_preflight_ee(AOI_OK)
    out = run_preflight(r)
    assert not out.valid and 'future_date' in codes(out.blocking_errors)


def test_date_before_supported_range_blocks(mock_preflight_ee):
    r = WildfireRequest(department='A', municipality='B', fire_date=date(2016, 1, 1),
                        analysis_end=date(2016, 1, 10))
    mock_preflight_ee(AOI_OK)
    assert 'date_too_early' in codes(run_preflight(r).blocking_errors)


def test_invalid_dates_rejected_by_schema():
    with pytest.raises(ValidationError):
        WildfireRequest(department='A', municipality='B', fire_date=date(2026, 8, 15),
                        analysis_end=date(2026, 8, 5))
    with pytest.raises(ValidationError):
        WildfireRequest(department='A', municipality='B', fire_date='2026-02-30',
                        analysis_end='2026-03-05')
