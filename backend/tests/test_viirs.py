"""Offline graph parity and validation for the unchanged V7.6 VIIRS flow."""
import ast
from pathlib import Path
from unittest.mock import patch

import ee
from ee import apitestcase
import pytest

from backend.app.wildfire import viirs


@pytest.fixture
def ee_offline():
    case = apitestcase.ApiTestCase()
    with patch.object(ee.data, '_install_cloud_api_resource'):
        case.setUp()
        try:
            with patch.object(ee.data, 'computeValue', side_effect=AssertionError('Remote evaluation')):
                yield
        finally:
            case.tearDown()


@pytest.mark.parametrize('fire,end', [('2026-08-05', '2026-08-05'), ('2024-02-29', '2024-03-01'),
                                     ('2026-12-31', '2027-01-01')])
def test_inclusive_dates(ee_offline, fire, end):
    start, stop = viirs.viirs_window(fire, end)
    assert start.serialize() == ee.Date(fire).advance(-10, 'day').serialize()
    assert stop.serialize() == ee.Date(end).advance(1, 'day').serialize()
    assert viirs.viirs_window(ee.Date(fire), ee.Date(end))[1].serialize() == stop.serialize()


@pytest.mark.parametrize('fire,end,error', [
    ('2026-08-05', '2026-08-04', ValueError), ('2026-02-29', '2026-03-01', ValueError),
    ('2026-08-05', 'invalid', ValueError), (None, '2026-08-05', TypeError),
    ('2026-08-05', 20260815, TypeError), ('20260805', '2026-08-15', ValueError),
])
def test_invalid_dates(fire, end, error):
    with pytest.raises(error):
        viirs.viirs_window(fire, end)


def test_normalization_and_sources(ee_offline):
    image = ee.Image('scene')
    expected = (image.select('confidence').unmask(0).toByte().rename('confidence')
                .copyProperties(image, ['system:time_start']))
    assert viirs.normalize_viirs_confidence(image).serialize() == expected.serialize()
    aoi = ee.Geometry.Point([-75, 4])
    start, stop = ee.Date('2026-08-05').advance(-10, 'day'), ee.Date('2026-08-15').advance(1, 'day')
    snpp = (ee.ImageCollection('NASA/LANCE/SNPP_VIIRS/C2').filterBounds(aoi)
            .filterDate(start, stop).map(viirs.normalize_viirs_confidence))
    noaa = (ee.ImageCollection('NASA/LANCE/NOAA20_VIIRS/C2').filterBounds(aoi)
            .filterDate(start, stop).map(viirs.normalize_viirs_confidence))
    assert viirs.viirs_collection(aoi, '2026-08-05', '2026-08-15').serialize() == snpp.merge(noaa).serialize()


@pytest.mark.parametrize('values', [[], [0], [0, 1, 2]])
def test_fallback_maximum_and_fire_mask(ee_offline, values):
    aoi = ee.Geometry.Point([-75, 4])
    collection = ee.ImageCollection([ee.Image(v).toByte().rename('confidence') for v in values])
    fallback = ee.Image.constant(0).toByte().rename('confidence').clip(aoi)
    expected = ee.ImageCollection([fallback]).merge(collection).max().toByte().rename('confidence')
    actual = viirs.maximum_confidence(collection, aoi)
    assert actual.serialize() == expected.serialize()
    fire = expected.gte(1).selfMask().toByte().rename('VIIRS')
    assert viirs.viirs_fire(actual).serialize() == fire.serialize()


def test_vector_parameters_buffers_and_paint(ee_offline):
    aoi = ee.Geometry.Point([-75, 4])
    fire = ee.Image(1).toByte().rename('VIIRS')
    expected_points = fire.reduceToVectors(geometry=aoi, scale=375, geometryType='centroid',
                                           eightConnected=True, maxPixels=1e7, tileScale=4)
    points = viirs.viirs_points(fire, aoi)
    assert points.serialize() == expected_points.serialize()
    zones = viirs.viirs_zones(points, aoi)
    expected_seed = ee.Image(0).byte().paint(points.map(lambda f: f.buffer(700)), 1).clip(aoi)
    expected_prior = ee.Image(0).byte().paint(points.map(lambda f: f.buffer(3000)), 1).clip(aoi)
    assert zones['viirsSeedZone'].serialize() == expected_seed.serialize()
    assert zones['viirsPriorZone'].serialize() == expected_prior.serialize()
    # Empty centroids still build zero-background zone graphs, without fetching size.
    empty = ee.FeatureCollection([])
    assert viirs.viirs_zones(empty, aoi)['viirsSeedZone'].serialize() == (
        ee.Image(0).byte().paint(empty.map(lambda f: f.buffer(700)), 1).clip(aoi).serialize())


def test_outputs_and_alias(ee_offline):
    aoi = ee.Geometry.Point([-75, 4])
    result = viirs.build_viirs_context(aoi, '2026-08-05', '2026-08-15')
    assert set(result) == {'viirs', 'viirsFire', 'viirsPoints', 'viirsSeedZone', 'viirsPriorZone'}
    assert result['viirs'] is result['viirsFire']
    assert isinstance(result['viirsPoints'], ee.FeatureCollection)
    for name in ('viirs', 'viirsFire', 'viirsSeedZone', 'viirsPriorZone'):
        assert isinstance(result[name], ee.Image)
        result[name].serialize()


def test_input_types(ee_offline):
    aoi = ee.Geometry.Point([-75, 4])
    cases = [
        (viirs.normalize_viirs_confidence, (None,)),
        (viirs.viirs_collection, (None, '2026-08-05', '2026-08-15')),
        (viirs.maximum_confidence, (None, aoi)),
        (viirs.maximum_confidence, (ee.ImageCollection([]), None)),
        (viirs.viirs_fire, (None,)), (viirs.viirs_points, (None, aoi)),
        (viirs.viirs_points, (ee.Image(1), None)), (viirs.viirs_zones, (None, aoi)),
        (viirs.viirs_zones, (ee.FeatureCollection([]), None)),
    ]
    for function, args in cases:
        with pytest.raises(TypeError):
            function(*args)


def test_no_client_evaluation_or_training():
    tree = ast.parse(Path(viirs.__file__).read_text(), feature_version=(3, 11))
    forbidden = {'getInfo', 'evaluate', 'computeValue', 'reproject', 'getMapId', 'train', 'classify', 'size'}
    assert not [n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute) and n.func.attr in forbidden]
