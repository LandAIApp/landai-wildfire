"""Local input checks and offline EE graph parity against V7.6."""
import ast
from pathlib import Path
from unittest.mock import patch

import ee
from ee import apitestcase
import pytest

from backend.app.wildfire import historical_variability as history
from backend.app.wildfire.spectral_indices import add_history_indices


@pytest.fixture
def ee_offline():
    case = apitestcase.ApiTestCase()
    # Also restore the internal installer replaced by EE's test helper.
    with patch.object(ee.data, '_install_cloud_api_resource'):
        case.setUp()
        try:
            with patch.object(ee.data, 'computeValue', side_effect=AssertionError('Remote evaluation')):
                yield
        finally:
            case.tearDown()


@pytest.mark.parametrize('value', ['2024-02-29', '2026-08-05', '2026-01-31'])
def test_valid_local_dates(value):
    assert history.validate_fire_date(value) == value


@pytest.mark.parametrize('value', ['', '2026-02-29', '2026-13-01', '20260805', '2026-8-5', '2026-08-05T00:00:00Z'])
def test_invalid_local_dates(value):
    with pytest.raises(ValueError):
        history.validate_fire_date(value)


@pytest.mark.parametrize('value', [None, 20260805, {}, True])
def test_invalid_date_types(value):
    with pytest.raises(TypeError):
        history.validate_fire_date(value)


def test_calendar_window_and_server_date(ee_offline):
    fire = ee.Date('2024-08-31')
    assert history.validate_fire_date(fire) is fire
    start, end = history.historical_window(fire)
    assert start.serialize() == fire.advance(-6, 'month').serialize()
    assert end.serialize() == fire.advance(-15, 'day').serialize()


def test_exact_mask_scaling_and_timestamp(ee_offline):
    scene = ee.Image('test-scene')
    scl = scene.select('SCL')
    valid = (scl.neq(1).And(scl.neq(3)).And(scl.neq(7)).And(scl.neq(8))
             .And(scl.neq(9)).And(scl.neq(10)).And(scl.neq(11)))
    expected = (scene.updateMask(scene.select('cs_cdf').gte(.55)).updateMask(valid)
                .divide(10000).copyProperties(scene, ['system:time_start']))
    assert history.mask_historical_s2(scene).serialize() == expected.serialize()


def test_collection_filters_and_historical_indices(ee_offline):
    aoi = ee.Geometry.Point([-75, 4])
    fire = ee.Date('2026-08-05')
    expected = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                .linkCollection(ee.ImageCollection('GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED'), ['cs_cdf'])
                .filterBounds(aoi).filterDate(fire.advance(-6, 'month'), fire.advance(-15, 'day'))
                .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 85))
                .map(history.mask_historical_s2).map(add_history_indices))
    result = history.historical_collection(aoi, '2026-08-05')
    assert result.serialize() == expected.serialize()
    indexed = add_history_indices(ee.Image('test-scene'))
    expected_indices = ee.Image.cat(
        ee.Image('test-scene').normalizedDifference(['B8A', 'B12']).rename('NBR'),
        ee.Image('test-scene').normalizedDifference(['B8', 'B4']).rename('NDVI'),
    ).copyProperties(ee.Image('test-scene'), ['system:time_start'])
    assert indexed.serialize() == expected_indices.serialize()


def test_reducer_unmask_anomaly_and_evidence(ee_offline):
    collection = ee.ImageCollection([ee.Image.constant([.2, .3]).rename(['NBR', 'NDVI'])])
    expected_std = ee.Image.cat(
        collection.select('NBR').reduce(ee.Reducer.stdDev()).rename('NBR_std').unmask(0),
        collection.select('NDVI').reduce(ee.Reducer.stdDev()).rename('NDVI_std').unmask(0),
    )
    actual_std = history.temporal_variability(collection)
    assert actual_std.serialize() == expected_std.serialize()
    dnbr = ee.Image(.3).rename('dNBR')
    expected_z = (dnbr.select('dNBR').divide(expected_std.select('NBR_std').add(.03))
                  .clamp(-10, 10).rename('NBR_change_z'))
    actual_z = history.nbr_change_anomaly(dnbr, actual_std)
    assert actual_z.serialize() == expected_z.serialize()
    expected_evidence = (expected_z.select('NBR_change_z').subtract(1)
                         .divide(ee.Number(5).subtract(1)).clamp(0, 1).rename('AnomalyEvidence'))
    assert history.anomaly_evidence(actual_z).serialize() == expected_evidence.serialize()


def test_combined_output_and_validation(ee_offline):
    aoi = ee.Geometry.Point([-75, 4])
    dnbr = ee.Image(.3).rename('dNBR')
    std = history.temporal_variability(history.historical_collection(aoi, '2026-08-05'))
    z = history.nbr_change_anomaly(dnbr, std)
    expected = ee.Image.cat(std, z, history.anomaly_evidence(z))
    result = history.build_historical_features(aoi, '2026-08-05', dnbr)
    assert result.serialize() == expected.serialize()
    assert history.OUTPUT_BANDS == ('NBR_std', 'NDVI_std', 'NBR_change_z', 'AnomalyEvidence')
    for function, args in [
        (history.historical_collection, (None, '2026-08-05')),
        (history.mask_historical_s2, (None,)),
        (history.temporal_variability, (None,)),
        (history.nbr_change_anomaly, (None, dnbr)),
        (history.anomaly_evidence, (None,)),
        (history.build_historical_features, (aoi, '2026-08-05', None)),
    ]:
        with pytest.raises(TypeError):
            function(*args)


def test_no_evaluation_reprojection_or_out_of_scope_calls():
    source = Path(history.__file__).read_text(encoding='utf-8')
    tree = ast.parse(source, feature_version=(3, 11))
    forbidden = {'getInfo', 'evaluate', 'computeValue', 'reproject', 'getMapId', 'train', 'classify'}
    assert not [node.func.attr for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in forbidden]
