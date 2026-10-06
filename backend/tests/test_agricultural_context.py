"""Offline V7.6 agriculture parity, threshold boundaries and validation."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import ee
from ee import apitestcase
import pytest

from backend.app.wildfire import agricultural_context as ag
from backend.tests.test_spectral_indices import Pixel


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


def test_reference_configuration():
    assert ag.DYNAMIC_WORLD_COLLECTION == 'GOOGLE/DYNAMICWORLD/V1'
    assert ag.WORLDCOVER_COLLECTION == 'ESA/WorldCover/v200'
    assert (ag.WC_CROP_CLASS, ag.WC_BUILT_CLASS, ag.WC_WATER_CLASS) == (40, 50, 80)
    assert (ag.WC_WEIGHT, ag.PROBABILITY_WEIGHT, ag.FREQUENCY_WEIGHT) == (.5, .2, .3)
    assert ag.WC_WEIGHT + ag.PROBABILITY_WEIGHT + ag.FREQUENCY_WEIGHT == 1
    assert (ag.DW_CROP_PROB_THRESHOLD, ag.AGRI_STRONG_THRESHOLD, ag.AGRI_VERY_STRONG_THRESHOLD) == (.4, .55, .7)


def test_collection_window_and_filters(ee_offline):
    aoi, fire = ee.Geometry.Point([-75, 4]), ee.Date('2026-08-05')
    expected = (ee.ImageCollection('GOOGLE/DYNAMICWORLD/V1').filterBounds(aoi)
                .filterDate(fire.advance(-6, 'month'), fire.advance(-15, 'day')).select('crops'))
    assert ag.dynamic_world_collection(aoi, fire).serialize() == expected.serialize()


def test_flag_reductions_and_mask_order(ee_offline):
    aoi = ee.Geometry.Point([-75, 4])
    collection = ee.ImageCollection([ee.Image(.4).rename('crops')])
    image = ee.Image(.4).rename('crops')
    assert ag.crop_flag(image).serialize() == image.select('crops').gte(.4).rename('cropFlag').serialize()
    crops = collection.select('crops')
    expected_probability = crops.median().unmask(0).clip(aoi).rename('cropProbability')
    expected_frequency = (crops.map(lambda x: x.select('crops').gte(.4).rename('cropFlag'))
                          .mean().unmask(0).clip(aoi).rename('cropFrequency'))
    result = ag.crop_statistics(collection, aoi)
    assert result['cropProbability'].serialize() == expected_probability.serialize()
    assert result['cropFrequency'].serialize() == expected_frequency.serialize()


def test_worldcover_first_and_classes(ee_offline):
    aoi = ee.Geometry.Point([-75, 4])
    cover = ee.ImageCollection('ESA/WorldCover/v200').first().select('Map').clip(aoi)
    result = ag.worldcover_masks(aoi)
    for name, code in [('wcCrop', 40), ('builtMask', 50), ('waterMask', 80)]:
        assert result[name].serialize() == cover.eq(code).rename(name).serialize()


def test_score_and_complete_output_graphs(ee_offline):
    aoi = ee.Geometry.Point([-75, 4])
    stats = ag.crop_statistics(ag.dynamic_world_collection(aoi, '2026-08-05'), aoi)
    masks = ag.worldcover_masks(aoi)
    expected = (masks['wcCrop'].select('wcCrop').multiply(.5)
                .add(stats['cropProbability'].select('cropProbability').multiply(.2))
                .add(stats['cropFrequency'].select('cropFrequency').multiply(.3))
                .clamp(0, 1).rename('AgricultureScore'))
    output = ag.build_agricultural_context(aoi, '2026-08-05')
    assert set(output) == {'cropProbability', 'cropFrequency', 'agricultureScore',
                           'agricultureStrong', 'agricultureVeryStrong', 'waterMask', 'builtMask'}
    assert output['agricultureScore'].serialize() == expected.serialize()
    for name in stats:
        assert output[name].serialize() == stats[name].serialize()
    for name in ('waterMask', 'builtMask'):
        assert output[name].serialize() == masks[name].serialize()
    for name, threshold in [('agricultureStrong', .55), ('agricultureVeryStrong', .7)]:
        assert output[name].serialize() == expected.select('AgricultureScore').gte(threshold).rename(name).serialize()


@pytest.fixture
def scalar_images(monkeypatch):
    # Reuse the existing arithmetic test double without changing validated tests.
    monkeypatch.setattr(Pixel, 'clamp', lambda self, low, high: Pixel(
        {k: min(max(v, low), high) for k, v in self.bands.items()}), raising=False)
    monkeypatch.setattr(Pixel, 'gte', lambda self, threshold: Pixel(
        {k: int(v >= threshold) for k, v in self.bands.items()}), raising=False)
    monkeypatch.setattr(ag, 'ee', SimpleNamespace(Image=Pixel))


@pytest.mark.parametrize('crop,prob,freq,expected', [
    (0, 0, 0, 0), (1, 0, 0, .5), (0, 1, 1, .5),
    (1, .5, .5, .75), (1, 1, 1, 1), (1, 2, 2, 1), (0, -1, -1, 0),
])
def test_continuous_score_and_clamp(scalar_images, crop, prob, freq, expected):
    result = ag.agriculture_score(Pixel({'wcCrop': crop}), Pixel({'cropProbability': prob}),
                                  Pixel({'cropFrequency': freq}))
    assert result.bands == {'AgricultureScore': pytest.approx(expected)}


@pytest.mark.parametrize('score,strong,very_strong', [(.5499, 0, 0), (.55, 1, 0), (.6999, 1, 0), (.7, 1, 1)])
def test_inclusive_score_thresholds(scalar_images, score, strong, very_strong):
    result = ag.agriculture_thresholds(Pixel({'AgricultureScore': score}))
    assert result['agricultureStrong'].bands == {'agricultureStrong': strong}
    assert result['agricultureVeryStrong'].bands == {'agricultureVeryStrong': very_strong}


@pytest.mark.parametrize('value,expected', [(.3999, 0), (.4, 1), (.4001, 1)])
def test_inclusive_crop_flag(scalar_images, value, expected):
    assert ag.crop_flag(Pixel({'crops': value})).bands == {'cropFlag': expected}


def test_invalid_inputs(ee_offline):
    aoi, image = ee.Geometry.Point([-75, 4]), ee.Image(0)
    for function, args in [
        (ag.dynamic_world_collection, (None, '2026-08-05')),
        (ag.crop_flag, (None,)), (ag.crop_statistics, (image, aoi)),
        (ag.crop_statistics, (ee.ImageCollection([]), None)),
        (ag.worldcover_masks, (None,)), (ag.agriculture_thresholds, (None,)),
        (ag.build_agricultural_context, (None, '2026-08-05')),
        (ag.build_agricultural_context, (aoi, 20260805)),
    ]:
        with pytest.raises(TypeError):
            function(*args)
    for position in range(3):
        args = [image, image, image]
        args[position] = None
        with pytest.raises(TypeError):
            ag.agriculture_score(*args)
    with pytest.raises(ValueError):
        ag.build_agricultural_context(aoi, '2026-02-29')


def test_no_prohibited_calls():
    tree = ast.parse(Path(ag.__file__).read_text(), feature_version=(3, 11))
    forbidden = {'getInfo', 'evaluate', 'computeValue', 'reproject', 'getMapId', 'train', 'classify', 'selfMask'}
    assert not [n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute) and n.func.attr in forbidden]
