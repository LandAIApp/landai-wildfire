"""run_burn_model: orchestrates the V7.6 pipeline (deferred, server-side only)."""
from __future__ import annotations

import ee

from .agricultural_context import build_agricultural_context, worldcover_masks
from .evidence import enhanced_evidence, spectral_evidence
from .historical_variability import (
    anomaly_evidence, historical_collection, nbr_change_anomaly, temporal_variability,
)
from .postprocessing import calculate_area_statistics, create_threshold_masks
from .probability import (
    apply_agricultural_exception, base_likelihood, cleaned_likelihood, observation_quality,
)
from .seeds import negative_seed, positive_seed
from .sentinel2 import (
    build_composites, build_post_collection, build_pre_collection, observation_counts,
)
from .spectral_indices import build_model_features, temporal_differences
from .training import (
    classify_random_forest, sample_counts, sample_training, train_random_forest,
)
from .viirs import build_viirs_context
from .windows import get_time_windows

CONTRACT_KEYS = (
    'pre', 'post', 'dNBR', 'spectralEvidence', 'enhancedEvidence', 'cropProbability',
    'cropFrequency', 'agricultureScore', 'viirs', 'viirsPoints', 'rfLikelihood',
    'observationQuality', 'wildfireLikelihood', 'burn035', 'burn050', 'burn060',
    'burn072', 'burn085', 'areaStatistics',
)


def run_burn_model(aoi: ee.Geometry, fire_date: ee.Date, analysis_end: ee.Date) -> dict:
    """Build the full V7.6 graph. Nothing is evaluated here.

    Returns the 19 reference outputs (CONTRACT_KEYS) plus two extras for the
    application layer: trainingCounts (ee.Dictionary) and agriculturalBurnAccepted.
    """
    t = get_time_windows(fire_date, analysis_end)

    # Sentinel-2 PRE / POST
    pre_col = build_pre_collection(aoi, t)
    post_col = build_post_collection(aoi, t)
    counts = observation_counts(pre_col, post_col)
    observed = counts['observed']
    pre, post = build_composites(pre_col, post_col, aoi)

    # Changes
    diff = temporal_differences(pre, post)
    dnbr, dmirbi = diff.select('dNBR'), diff.select('dMIRBI')

    # Historical context and anomaly
    variability = temporal_variability(historical_collection(aoi, fire_date))
    nbr_std, ndvi_std = variability.select('NBR_std'), variability.select('NDVI_std')
    nbr_change_z = nbr_change_anomaly(dnbr, variability)
    anomaly = anomaly_evidence(nbr_change_z)

    # Agriculture / land cover
    agri = build_agricultural_context(aoi, fire_date)
    agri_score = agri['agricultureScore']
    agri_strong, agri_very_strong = agri['agricultureStrong'], agri['agricultureVeryStrong']
    water, built = agri['waterMask'], agri['builtMask']

    # VIIRS
    viirs = build_viirs_context(aoi, fire_date, analysis_end)
    seed_zone, prior_zone = viirs['viirsSeedZone'], viirs['viirsPriorZone']

    # Evidence
    spectral = spectral_evidence(diff)
    enhanced = enhanced_evidence(spectral, anomaly)

    # Seeds
    pos_seed = positive_seed(
        viirs_seed_zone=seed_zone, viirs_prior_zone=prior_zone, enhanced=enhanced,
        dnbr=dnbr, dmirbi=dmirbi, nbr_change_z=nbr_change_z, agri_strong=agri_strong,
        agri_very_strong=agri_very_strong, water=water, built=built, observed=observed)
    neg_seed = negative_seed(
        dnbr=dnbr, dmirbi=dmirbi, agri_strong=agri_strong, agri_very_strong=agri_very_strong,
        crop_frequency=agri['cropFrequency'], nbr_change_z=nbr_change_z, enhanced=enhanced,
        viirs_seed_zone=seed_zone, viirs_prior_zone=prior_zone, nbr_std=nbr_std,
        ndvi_std=ndvi_std, water=water, built=built, observed=observed)

    # Random Forest (30 predictors)
    context = ee.Image.cat(nbr_std, ndvi_std, nbr_change_z, agri['cropProbability'],
                           agri['cropFrequency'], worldcover_masks(aoi)['wcCrop'],
                           agri_score, enhanced)
    features = build_model_features(pre, post, context, observed, aoi)
    samples = sample_training(features, pos_seed, neg_seed, aoi)
    classifier = train_random_forest(samples['training'], features.bandNames())
    rf = classify_random_forest(features, classifier)

    # Probability
    quality = observation_quality(counts['preCount'], counts['postCount'])
    base = base_likelihood(rf, enhanced, prior_zone, water, built, quality)
    cleaned = cleaned_likelihood(base, agri_score, agri['cropFrequency'], enhanced,
                                 anomaly, nbr_std, ndvi_std)
    wildfire, accepted = apply_agricultural_exception(
        cleaned, base, enhanced, nbr_change_z, agri_strong, agri_very_strong, prior_zone)

    # Delimitation and statistics
    masks = create_threshold_masks(wildfire)
    stats = calculate_area_statistics(masks, aoi)

    return {
        'pre': pre, 'post': post, 'dNBR': dnbr,
        'spectralEvidence': spectral, 'enhancedEvidence': enhanced,
        'cropProbability': agri['cropProbability'], 'cropFrequency': agri['cropFrequency'],
        'agricultureScore': agri_score,
        'viirs': viirs['viirs'], 'viirsPoints': viirs['viirsPoints'],
        'rfLikelihood': rf, 'observationQuality': quality,
        'wildfireLikelihood': wildfire,
        'burn035': masks['burn035'], 'burn050': masks['burn050'], 'burn060': masks['burn060'],
        'burn072': masks['burn072'], 'burn085': masks['burn085'],
        'areaStatistics': stats,
        # application-layer extras (not part of the 19-key V7.6 contract)
        'trainingCounts': sample_counts(samples),
        'agriculturalBurnAccepted': accepted,
    }

