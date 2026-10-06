from unittest.mock import MagicMock

import ee
import pytest

from app.core.errors import TileGenerationError
from app.services import tiles

KEYS = {spec[4] for spec in tiles.LAYER_SPECS}


def fake_image(fail=False):
    img = MagicMock()
    if fail:
        img.getMapId.side_effect = ee.EEException('boom')
    else:
        img.getMapId.return_value = {'tile_fetcher': MagicMock(url_format='https://ee/{z}/{x}/{y}')}
    return img


@pytest.fixture(autouse=True)
def no_init(monkeypatch):
    monkeypatch.setattr(tiles, 'ensure_initialized', lambda: None)


def test_required_layers_and_defaults():
    ids = {s[0] for s in tiles.LAYER_SPECS}
    assert {'post', 'pre', 'dnbr', 'spectral_evidence', 'wildfire_likelihood', 'burn_050',
            'burn_072', 'viirs', 'agriculture_score', 'observation_quality'} <= ids
    defaults = {s[0] for s in tiles.LAYER_SPECS if s[6]}
    assert defaults == {'post', 'burn_050'}


def test_reference_visualization_parameters():
    spec = {s[0]: s for s in tiles.LAYER_SPECS}
    assert spec['post'][5] == {'bands': ['B12', 'B8A', 'B4'], 'min': 0.02, 'max': 0.40}
    assert (spec['dnbr'][5]['min'], spec['dnbr'][5]['max']) == (-0.20, 0.70)
    assert spec['burn_050'][5]['palette'] == ['FF0000']
    assert spec['burn_072'][5]['palette'] == ['8B0000']


def test_build_layers_returns_tile_urls():
    layers, warnings = tiles.build_layers({k: fake_image() for k in KEYS})
    assert len(layers) == len(tiles.LAYER_SPECS) and warnings == []
    assert all(l.tile_url.startswith('https://') for l in layers)


def test_single_layer_failure_becomes_warning():
    result = {k: fake_image() for k in KEYS}
    result['viirs'] = fake_image(fail=True)
    layers, warnings = tiles.build_layers(result)
    assert 'viirs' not in {l.id for l in layers}
    assert [w.code for w in warnings] == ['layer_unavailable']


def test_all_layers_failing_raises():
    with pytest.raises(TileGenerationError):
        tiles.build_layers({k: fake_image(fail=True) for k in KEYS})
