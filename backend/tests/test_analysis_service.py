from unittest.mock import MagicMock

import pytest

from app.core.errors import (
    EarthEngineServiceError, MunicipalityNotFoundError, NoTrainingSamplesError,
    PreflightFailedError,
)
from app.schemas.wildfire import (
    DateRange, DateWindows, Issue, LayerInfo, PreflightResponse,
)
from app.services import analysis


def ok_preflight():
    return PreflightResponse(
        status='ok', valid=True, pre_count=10, post_count=3, history_count=25,
        aoi_hectares=10000.0,
        date_windows=DateWindows(pre=DateRange(start='a', end='b'), post=DateRange(start='c', end='d'),
                                 history=DateRange(start='e', end='f')))


@pytest.fixture
def wired(monkeypatch):
    """Patch the analysis service so only the logic under test runs."""
    monkeypatch.setattr(analysis, 'ee', MagicMock())
    monkeypatch.setattr(analysis, 'run_preflight', lambda r: ok_preflight())
    monkeypatch.setattr(analysis.administrative, 'select_municipality', lambda d, m: MagicMock())
    monkeypatch.setattr(analysis.administrative, 'boundary_geojson', lambda c: {
        'type': 'Feature', 'properties': {},
        'geometry': {'type': 'Polygon', 'coordinates': [[[-75.2, 4.1], [-75.1, 4.1], [-75.1, 4.2],
                                                            [-75.2, 4.1]]]}})
    monkeypatch.setattr(analysis, 'run_burn_model',
                        lambda *a, **k: {'trainingCounts': 'COUNTS', 'areaStatistics': 'AREAS'})
    monkeypatch.setattr(analysis, 'build_layers', lambda r: ([
        LayerInfo(id='post', label='POST', group='Imagery', description='d',
                  tile_url='https://x/{z}/{x}/{y}', visible_by_default=True)], []))
    values = {'COUNTS': {'positive': 800, 'negative': 2500},
              'AREAS': {'wf035': 120.5, 'wf050': 90.0, 'wf060': 70.0, 'wf072': 40.0, 'wf085': None}}

    def fake_evaluate(obj, what='x'):
        v = values[obj]
        if isinstance(v, Exception):
            raise v
        return v
    monkeypatch.setattr(analysis, 'evaluate', fake_evaluate)
    return values


def test_successful_analysis(wired, req):
    out = analysis.run_analysis(req)
    assert out.status == 'ok'
    assert out.training.positive_samples == 800 and out.training.negative_samples == 2500
    assert [a.key for a in out.area_hectares] == ['wf035', 'wf050', 'wf060', 'wf072', 'wf085']
    assert out.area_statistics['wf085'] == 0.0  # null -> 0
    assert out.area_statistics['wf050'] == 90.0
    assert out.image_counts == {'pre': 10, 'post': 3, 'history': 25}
    assert out.metadata['equivalence_validated'] is False
    assert 'not an officially validated' in out.metadata['disclaimer']
    assert out.bounds == [[4.1, -75.2], [4.2, -75.1]]


def test_zero_positive_samples_is_blocking(wired, req):
    wired['COUNTS'] = {'positive': 0, 'negative': 2500}
    with pytest.raises(NoTrainingSamplesError) as e:
        analysis.run_analysis(req)
    assert 'positive' in e.value.message


def test_zero_negative_samples_is_blocking(wired, req):
    wired['COUNTS'] = {'positive': 300, 'negative': 0}
    with pytest.raises(NoTrainingSamplesError) as e:
        analysis.run_analysis(req)
    assert 'negative' in e.value.message


def test_few_positive_samples_only_warns(wired, req):
    wired['COUNTS'] = {'positive': 10, 'negative': 100}
    out = analysis.run_analysis(req)
    assert 'few_positive_samples' in [w.code for w in out.warnings]


def test_no_area_detected_warns(wired, req):
    wired['AREAS'] = {k: None for k in ('wf035', 'wf050', 'wf060', 'wf072', 'wf085')}
    out = analysis.run_analysis(req)
    assert 'no_area_detected' in [w.code for w in out.warnings]


def test_earth_engine_error_propagates(wired, req):
    wired['AREAS'] = EarthEngineServiceError('boom')
    with pytest.raises(EarthEngineServiceError):
        analysis.run_analysis(req)


def test_blocked_preflight_raises(monkeypatch, req):
    blocked = PreflightResponse(status='blocked', valid=False,
                                blocking_errors=[Issue(code='no_post_images', message='No POST')])
    monkeypatch.setattr(analysis, 'run_preflight', lambda r: blocked)
    with pytest.raises(PreflightFailedError):
        analysis.run_analysis(req)


def test_unknown_municipality_raises_404_error(monkeypatch, req):
    blocked = PreflightResponse(status='blocked', valid=False, blocking_errors=[
        Issue(code='municipality_not_found', message='nope')])
    monkeypatch.setattr(analysis, 'run_preflight', lambda r: blocked)
    with pytest.raises(MunicipalityNotFoundError):
        analysis.run_analysis(req)
