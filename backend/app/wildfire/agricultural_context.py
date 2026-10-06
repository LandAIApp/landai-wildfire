"""V7.6 agricultural context; Python 3.11, deferred Earth Engine operations.

The caller initializes EE. This module builds evidence, not an exclusion mask.
"""
from __future__ import annotations

import ee

from .historical_variability import historical_window

DYNAMIC_WORLD_COLLECTION = 'GOOGLE/DYNAMICWORLD/V1'
WORLDCOVER_COLLECTION = 'ESA/WorldCover/v200'
DW_CROP_PROB_THRESHOLD = 0.40
WC_CROP_CLASS = 40
WC_BUILT_CLASS = 50
WC_WATER_CLASS = 80
WC_WEIGHT = 0.50
PROBABILITY_WEIGHT = 0.20
FREQUENCY_WEIGHT = 0.30
AGRI_STRONG_THRESHOLD = 0.55
AGRI_VERY_STRONG_THRESHOLD = 0.70


def _validate_aoi(aoi: ee.Geometry) -> None:
    if not isinstance(aoi, ee.Geometry):
        raise TypeError('aoi must be an ee.Geometry')


def dynamic_world_collection(aoi: ee.Geometry, fire_date: str | ee.Date) -> ee.ImageCollection:
    """Return historical Dynamic World crops images for AOI and fire date.

    Uses [fireDate - 6 months, fireDate - 15 days), reusing the validated
    historical window. Each image retains its crops band and native mask.
    No Sentinel-2 cloud mask, scaling or new scene filters are applied.
    """
    _validate_aoi(aoi)
    start, end = historical_window(fire_date)
    return (ee.ImageCollection(DYNAMIC_WORLD_COLLECTION).filterBounds(aoi)
            .filterDate(start, end).select('crops'))


def crop_flag(image: ee.Image) -> ee.Image:
    """Return cropFlag = crops >= .40 for one Dynamic World ee.Image.

    Retains masked observations as masked; they are not counted as non-crop.
    """
    if not isinstance(image, ee.Image):
        raise TypeError('image must be an ee.Image')
    return image.select('crops').gte(DW_CROP_PROB_THRESHOLD).rename('cropFlag')


def crop_statistics(crops: ee.ImageCollection, aoi: ee.Geometry) -> dict[str, ee.Image]:
    """Return cropProbability and cropFrequency ee.Images from historical crops.

    Median(crops) and mean(crops >= .40) each receive unmask(0), clip(aoi),
    and their explicit band name, in V7.6 order. No empty-collection fallback
    is added. The default unmask footprint behavior is retained.
    """
    if not isinstance(crops, ee.ImageCollection):
        raise TypeError('crops must be an ee.ImageCollection')
    _validate_aoi(aoi)
    crops = crops.select('crops')
    return {
        'cropProbability': crops.median().unmask(0).clip(aoi).rename('cropProbability'),
        'cropFrequency': crops.map(crop_flag).mean().unmask(0).clip(aoi).rename('cropFrequency'),
    }


def worldcover_masks(aoi: ee.Geometry) -> dict[str, ee.Image]:
    """Return wcCrop, builtMask and waterMask ee.Images for an AOI geometry.

    Uses first() from ESA/WorldCover/v200, selects Map and clips before class
    comparisons. Classes are 40/50/80. Native masks are preserved; no selfMask
    is used, so observed nonmatching pixels remain zero.
    """
    _validate_aoi(aoi)
    worldcover = ee.ImageCollection(WORLDCOVER_COLLECTION).first().select('Map').clip(aoi)
    return {
        'wcCrop': worldcover.eq(WC_CROP_CLASS).rename('wcCrop'),
        'builtMask': worldcover.eq(WC_BUILT_CLASS).rename('builtMask'),
        'waterMask': worldcover.eq(WC_WATER_CLASS).rename('waterMask'),
    }


def agriculture_score(
    wc_crop: ee.Image, crop_probability: ee.Image, crop_frequency: ee.Image,
) -> ee.Image:
    """Return AgricultureScore = clamp(.50*wcCrop + .20*prob + .30*freq, 0, 1).

    Inputs must contain wcCrop, cropProbability and cropFrequency respectively.
    Uses native EE mask intersections, with no new unmask or clip. The output
    band keeps V7.6's capitalized name for compatibility with model features.
    """
    for name, image in (('wc_crop', wc_crop), ('crop_probability', crop_probability),
                        ('crop_frequency', crop_frequency)):
        if not isinstance(image, ee.Image):
            raise TypeError(f'{name} must be an ee.Image')
    return (wc_crop.select('wcCrop').multiply(WC_WEIGHT)
            .add(crop_probability.select('cropProbability').multiply(PROBABILITY_WEIGHT))
            .add(crop_frequency.select('cropFrequency').multiply(FREQUENCY_WEIGHT))
            .clamp(0, 1).rename('AgricultureScore'))


def agriculture_thresholds(score: ee.Image) -> dict[str, ee.Image]:
    """Return agricultureStrong >= .55 and agricultureVeryStrong >= .70.

    Input contains AgricultureScore. Output images have the respective key as
    band name; pixels below threshold remain zero, with source masks retained.
    """
    if not isinstance(score, ee.Image):
        raise TypeError('score must be an ee.Image')
    score = score.select('AgricultureScore')
    return {
        'agricultureStrong': score.gte(AGRI_STRONG_THRESHOLD).rename('agricultureStrong'),
        'agricultureVeryStrong': score.gte(AGRI_VERY_STRONG_THRESHOLD).rename('agricultureVeryStrong'),
    }


def build_agricultural_context(aoi: ee.Geometry, fire_date: str | ee.Date) -> dict[str, ee.Image]:
    """Return the seven requested context outputs, each a deferred ee.Image.

    Inputs: AOI ee.Geometry and YYYY-MM-DD or ee.Date fire date. Keys:
    cropProbability, cropFrequency, agricultureScore, agricultureStrong,
    agricultureVeryStrong, waterMask, builtMask. See docs for band names.
    No penalties, seeds, burn exception or final likelihood are computed.
    """
    stats = crop_statistics(dynamic_world_collection(aoi, fire_date), aoi)
    cover = worldcover_masks(aoi)
    score = agriculture_score(cover['wcCrop'], stats['cropProbability'], stats['cropFrequency'])
    return {
        **stats,
        'agricultureScore': score,
        **agriculture_thresholds(score),
        'waterMask': cover['waterMask'],
        'builtMask': cover['builtMask'],
    }
