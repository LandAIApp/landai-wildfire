"""Offline structural checks of the full V7.6 graph (no Earth Engine access)."""
from unittest.mock import patch

import ee
from ee import apitestcase
import pytest

from app.wildfire import config, model, probability, seeds
from app.wildfire.spectral_indices import MODEL_BANDS
from app.wildfire.windows import get_time_windows


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


def _aoi():
    return ee.Geometry.Rectangle([-75.2, 4.1, -75.1, 4.2])


def test_predictor_stack_is_exactly_the_30_v76_bands_in_order():
    assert len(MODEL_BANDS) == 30
    assert MODEL_BANDS == (
        'pre_B4', 'pre_B5', 'pre_B8A', 'pre_B11', 'pre_B12', 'pre_NBR',
        'post_B4', 'post_B5', 'post_B8A', 'post_B11', 'post_B12', 'post_NBR',
        'dB4', 'dB5', 'dB8A', 'dB11', 'dB12',
        'dNBR', 'dNBR2', 'dMIRBI', 'dNDVI', 'dBAIS2',
        'NBR_std', 'NDVI_std', 'NBR_change_z',
        'cropProbability', 'cropFrequency', 'wcCrop', 'AgricultureScore',
        'EnhancedEvidence',
    )


def test_threshold_contract():
    assert [(t, k, a) for t, k, a, _ in config.THRESHOLD_SPECS] == [
        (0.35, 'burn035', 'wf035'), (0.50, 'burn050', 'wf050'), (0.60, 'burn060', 'wf060'),
        (0.72, 'burn072', 'wf072'), (0.85, 'burn085', 'wf085')]
    assert config.MIN_CONNECTED_PIXELS == 6


def test_rf_and_sampling_constants():
    assert (config.N_TREES, config.RF_MIN_LEAF_POPULATION, config.RF_BAG_FRACTION,
            config.RF_SEED, config.RF_VARIABLES_PER_SPLIT) == (150, 3, 0.65, 2026, None)
    assert (config.N_POSITIVE_SAMPLES, config.N_NEGATIVE_SAMPLES) == (3000, 5000)
    assert (config.POSITIVE_SAMPLE_SEED, config.NEGATIVE_SAMPLE_SEED) == (2026, 2027)


def test_run_burn_model_builds_full_contract_without_evaluation(ee_offline):
    result = model.run_burn_model(_aoi(), ee.Date('2026-08-05'), ee.Date('2026-08-15'))
    for key in model.CONTRACT_KEYS:
        assert key in result, key
    assert 'trainingCounts' in result
    for key in model.CONTRACT_KEYS:
        assert result[key].serialize()  # graph is serializable


def test_time_windows_are_deferred_ee_dates(ee_offline):
    t = get_time_windows(ee.Date('2026-08-05'), ee.Date('2026-08-15'))
    assert set(t) == {'PRE_START', 'PRE_END', 'POST_START', 'POST_END',
                      'HISTORY_START', 'HISTORY_END'}
    assert t['PRE_START'].serialize() == ee.Date('2026-08-05').advance(-90, 'day').serialize()
    assert t['PRE_END'].serialize() == ee.Date('2026-08-05').advance(-7, 'day').serialize()
    assert t['POST_END'].serialize() == ee.Date('2026-08-15').advance(1, 'day').serialize()
    assert t['HISTORY_START'].serialize() == ee.Date('2026-08-05').advance(-6, 'month').serialize()
    assert t['HISTORY_END'].serialize() == ee.Date('2026-08-05').advance(-15, 'day').serialize()


def test_agricultural_exception_returns_final_product(ee_offline):
    one = ee.Image(1)
    final, accepted = probability.apply_agricultural_exception(
        one, one, one, one, one, one, one)
    assert final.serialize() and accepted.serialize()


def test_seed_functions_build(ee_offline):
    one = ee.Image(1)
    p = seeds.positive_seed(viirs_seed_zone=one, viirs_prior_zone=one, enhanced=one, dnbr=one,
                            dmirbi=one, nbr_change_z=one, agri_strong=one, agri_very_strong=one,
                            water=one, built=one, observed=one)
    n = seeds.negative_seed(dnbr=one, dmirbi=one, agri_strong=one, agri_very_strong=one,
                            crop_frequency=one, nbr_change_z=one, enhanced=one,
                            viirs_seed_zone=one, viirs_prior_zone=one, nbr_std=one,
                            ndvi_std=one, water=one, built=one, observed=one)
    assert p.serialize() and n.serialize()
