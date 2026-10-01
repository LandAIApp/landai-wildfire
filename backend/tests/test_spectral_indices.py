"""Offline numerical parity and real Earth Engine graph construction tests."""

import math
from types import SimpleNamespace
from unittest.mock import patch

import ee
from ee import apitestcase
import pytest

from backend.app.wildfire import spectral_indices as spectral


class Pixel:
    """Minimal scalar image double; not a simulation of EE masks/projections."""

    def __init__(self, bands):
        self.bands = bands if isinstance(bands, dict) else {'constant': bands}

    constant = classmethod(lambda cls, value: cls(value))

    def select(self, band):
        return Pixel({band: self.bands[band]})

    def rename(self, name):
        return Pixel({name: next(iter(self.bands.values()))})

    def _op(self, other, operation):
        value = next(iter(other.bands.values())) if isinstance(other, Pixel) else other
        return Pixel({k: operation(v, value) for k, v in self.bands.items()})

    def add(self, other):
        return self._op(other, lambda a, b: a + b)

    def subtract(self, other):
        return self._op(other, lambda a, b: a - b)

    def multiply(self, other):
        return self._op(other, lambda a, b: a * b)

    def divide(self, other):
        return self._op(other, lambda a, b: a / b if b else 0)

    def max(self, other):
        return self._op(other, max)

    def sqrt(self):
        return Pixel({k: math.sqrt(v) for k, v in self.bands.items()})

    @staticmethod
    def cat(*images):
        return Pixel({k: v for image in images for k, v in image.bands.items()})

    def addBands(self, image, overwrite=False):
        bands = dict(self.bands)
        for name, value in image.bands.items():
            target = name
            suffix = 1
            while target in bands and not overwrite:
                target = f'{name}_{suffix}'
                suffix += 1
            bands[target] = value
        return Pixel(bands)


def test_indices_on_scaled_reflectance():
    scene = Pixel(dict(B4=.1, B5=.15, B6=.2, B7=.25, B8=.5, B8A=.4, B11=.3, B12=.2))
    with patch.object(spectral, 'ee', SimpleNamespace(Image=Pixel)):
        result = spectral.add_burn_indices(scene)
        repeat = spectral.add_burn_indices(result)
    expected = dict(NBR=1/3, BurnNBR=-1/3, NBR2=-.2, MIRBI=1.06, NDVI=2/3,
                    BAIS2=(1-math.sqrt(.2))*(1-.2/math.sqrt(.6)))
    for band, value in expected.items():
        assert result.bands[band] == pytest.approx(value)
    assert result.bands['B12'] == .2  # No second division by 10000.
    for band in spectral.INDEX_BANDS:
        assert repeat.bands[band] == result.bands[band]
        assert repeat.bands[f'{band}_1'] == result.bands[band]


@pytest.mark.parametrize('red,red_edge,nir,swir', [(0, .2, .4, .2), (-.1, -.2, .4, .2), (.1, .2, -.4, -.2)])
def test_bais2_epsilon_and_sqrt_guards(red, red_edge, nir, swir):
    scene = Pixel(dict(B4=red, B6=red_edge, B7=.25, B8=.5, B8A=nir, B11=.3, B12=swir))
    with patch.object(spectral, 'ee', SimpleNamespace(Image=Pixel)):
        result = spectral.add_burn_indices(scene)
    expected = (1-math.sqrt(max(red_edge*.25*nir/max(red, .0001), 0))) * (
        1+(swir-nir)/math.sqrt(max(swir+nir, .0001)))
    assert result.bands['BAIS2'] == pytest.approx(expected)


def test_difference_signs_and_order():
    names = spectral.REFLECTANCE_BANDS + ('NBR', 'NBR2', 'MIRBI', 'NDVI', 'BAIS2')
    with patch.object(spectral, 'ee', SimpleNamespace(Image=Pixel)):
        result = spectral.temporal_differences(Pixel(dict.fromkeys(names, .7)), Pixel(dict.fromkeys(names, .2)))
    assert tuple(result.bands) == spectral.DIFFERENCE_BANDS
    for band, value in result.bands.items():
        assert value == pytest.approx(.5 if band in ('dNBR', 'dNDVI') else -.5)


@pytest.fixture
def ee_offline():
    # Earth Engine's bundled algorithm signatures; no credentials or network.
    case = apitestcase.ApiTestCase()
    case.setUp()
    try:
        with patch.object(ee.data, 'computeValue', side_effect=AssertionError('Unexpected evaluation')):
            yield
    finally:
        case.tearDown()


def test_real_ee_graphs_and_reference_operations(ee_offline):
    scene = ee.Image.constant([.1] * 8).rename(['B4', 'B5', 'B6', 'B7', 'B8', 'B8A', 'B11', 'B12'])
    indexed = spectral.add_burn_indices(scene)
    pre = ee.ImageCollection([indexed]).median()
    post = ee.ImageCollection([indexed]).qualityMosaic('BurnNBR')
    context = ee.Image.constant([0] * 8).rename(list(spectral.CONTEXT_BANDS))
    features = spectral.build_model_features(pre, post, context, ee.Image(1), ee.Geometry.Point([0, 0]))
    graph = features.serialize()
    assert 'Image.clip' in graph and 'Image.updateMask' in graph
    assert 'overwrite' not in indexed.serialize()
    assert 'Image.normalizedDifference' not in indexed.serialize()
    assert 'Image.normalizedDifference' in spectral.add_history_indices(scene).serialize()
    assert len(spectral.MODEL_BANDS) == len(set(spectral.MODEL_BANDS)) == 30
    for band in spectral.MODEL_BANDS:
        assert band in graph
    layers = spectral.visualization_layers(pre, post)
    assert set(layers) == {'pre_NBR', 'post_NBR', 'dNBR'}
    for image in layers.values():
        assert isinstance(image, ee.Image)
        assert 'Image.visualize' in image.serialize()
    assert '2166AC' in layers['dNBR'].serialize()


@pytest.mark.parametrize('invalid', [None, 1, 'image', {}])
def test_rejects_non_images(invalid):
    with pytest.raises(TypeError, match='ee.Image'):
        spectral.add_burn_indices(invalid)
    with pytest.raises(TypeError, match='ee.Image'):
        spectral.temporal_differences(invalid, invalid)
    with pytest.raises(TypeError, match='ee.Image'):
        spectral.visualization_layers(invalid, invalid)


def test_rejects_invalid_aoi(ee_offline):
    with pytest.raises(TypeError, match='ee.Geometry'):
        spectral.build_model_features(ee.Image(1), ee.Image(1), ee.Image(1), ee.Image(1), None)
