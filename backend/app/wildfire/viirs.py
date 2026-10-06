"""Exact V7.6 VIIRS evidence pipeline; Python 3.11, deferred EE operations."""
from __future__ import annotations

import ee

from .historical_variability import validate_fire_date

SNPP_COLLECTION = 'NASA/LANCE/SNPP_VIIRS/C2'
NOAA20_COLLECTION = 'NASA/LANCE/NOAA20_VIIRS/C2'
SEED_BUFFER_METERS = 700
PRIOR_BUFFER_METERS = 3000


def _validate_aoi(aoi: ee.Geometry) -> None:
    if not isinstance(aoi, ee.Geometry):
        raise TypeError('aoi must be an ee.Geometry')


def viirs_window(fire_date: str | ee.Date, analysis_end: str | ee.Date) -> tuple[ee.Date, ee.Date]:
    """Return EE start/end dates for [fireDate - 10 days, analysisEnd + 1 day).

    Inputs are ISO YYYY-MM-DD strings or ee.Date objects. Local strings receive
    date and chronological validation. For EE dates, the caller must validate
    analysisEnd >= fireDate before evaluation, as in the V7.6 UI; no server
    values are fetched here. analysisEnd is an inclusive calendar date.
    """
    for name, value in (('fire_date', fire_date), ('analysis_end', analysis_end)):
        try:
            validate_fire_date(value)
        except (ValueError, TypeError) as error:
            raise type(error)(f'{name}: {error}') from error
    if isinstance(fire_date, str) and isinstance(analysis_end, str) and analysis_end < fire_date:
        raise ValueError('analysis_end must be on or after fire_date')
    return ee.Date(fire_date).advance(-10, 'day'), ee.Date(analysis_end).advance(1, 'day')


def normalize_viirs_confidence(image: ee.Image) -> ee.Image:
    """Return confidence-only ee.Image: unmask(0), toByte, rename, copy time.

    Input is one raw VIIRS image with confidence. Default unmask footprint is
    preserved; neither scaling nor confidence category filtering is introduced.
    """
    if not isinstance(image, ee.Image):
        raise TypeError('image must be an ee.Image')
    return (image.select('confidence').unmask(0).toByte().rename('confidence')
            .copyProperties(image, ['system:time_start']))


def viirs_collection(aoi: ee.Geometry, fire_date: str | ee.Date,
                     analysis_end: str | ee.Date) -> ee.ImageCollection:
    """Return normalized SNPP merged with NOAA20, filtered by AOI and window.

    Input AOI is ee.Geometry; dates follow viirs_window. Output scenes each have
    one byte confidence band. Filtering precedes normalization in both sources.
    """
    _validate_aoi(aoi)
    start, end = viirs_window(fire_date, analysis_end)
    snpp = (ee.ImageCollection(SNPP_COLLECTION).filterBounds(aoi).filterDate(start, end)
            .map(normalize_viirs_confidence))
    noaa20 = (ee.ImageCollection(NOAA20_COLLECTION).filterBounds(aoi).filterDate(start, end)
              .map(normalize_viirs_confidence))
    return snpp.merge(noaa20)


def maximum_confidence(collection: ee.ImageCollection, aoi: ee.Geometry) -> ee.Image:
    """Return temporal max confidence (byte), with V7.6's zero-image fallback.

    Input collection must contain normalized confidence images. A zero byte
    confidence image clipped to AOI is ALWAYS prepended before max(), matching
    the reference also for nonempty collections and masked pixels. No conditional
    empty-collection check, extra clipping or reprojection is introduced.
    """
    if not isinstance(collection, ee.ImageCollection):
        raise TypeError('collection must be an ee.ImageCollection')
    _validate_aoi(aoi)
    fallback = ee.Image.constant(0).toByte().rename('confidence').clip(aoi)
    return (ee.ImageCollection([fallback]).merge(collection).max()
            .toByte().rename('confidence'))


def viirs_fire(confidence: ee.Image) -> ee.Image:
    """Return VIIRS band: confidence >= 1, selfMask(), toByte(), rename.

    Input is the single-band image from maximum_confidence. Non-fire pixels
    become masked, exactly as in V7.6, rather than retained as observed zeros.
    """
    if not isinstance(confidence, ee.Image):
        raise TypeError('confidence must be an ee.Image')
    return confidence.gte(1).selfMask().toByte().rename('VIIRS')


def viirs_points(fire: ee.Image, aoi: ee.Geometry) -> ee.FeatureCollection:
    """Vectorize the byte fire image to centroids using exact V7.6 parameters.

    Inputs: single-band VIIRS image and AOI geometry. Returns ee.FeatureCollection
    with scale=375, centroid geometry, eightConnected=True, maxPixels=1e7,
    tileScale=4; all other reducer/projection options remain EE defaults.
    """
    if not isinstance(fire, ee.Image):
        raise TypeError('fire must be an ee.Image')
    _validate_aoi(aoi)
    return fire.reduceToVectors(geometry=aoi, scale=375, geometryType='centroid',
                                eightConnected=True, maxPixels=1e7, tileScale=4)


def viirs_zones(points: ee.FeatureCollection, aoi: ee.Geometry) -> dict[str, ee.Image]:
    """Return seed/prior zones painted from 700 m / 3000 m centroid buffers.

    Inputs: VIIRS centroid features and AOI. Outputs are zero byte images painted
    with 1 inside buffered features and clipped to AOI. Both retain the reference
    band name constant. These zones are contextual evidence, not training seeds.
    """
    if not isinstance(points, ee.FeatureCollection):
        raise TypeError('points must be an ee.FeatureCollection')
    _validate_aoi(aoi)
    seed = points.map(lambda feature: feature.buffer(SEED_BUFFER_METERS))
    prior = points.map(lambda feature: feature.buffer(PRIOR_BUFFER_METERS))
    return {
        'viirsSeedZone': ee.Image(0).byte().paint(seed, 1).clip(aoi),
        'viirsPriorZone': ee.Image(0).byte().paint(prior, 1).clip(aoi),
    }


def build_viirs_context(aoi: ee.Geometry, fire_date: str | ee.Date,
                        analysis_end: str | ee.Date) -> dict[str, ee.Image | ee.FeatureCollection]:
    """Return viirs, viirsFire, viirsPoints, viirsSeedZone and viirsPriorZone.

    viirs and viirsFire refer to the same VIIRS-band image, matching the reference
    return object's viirs alias. viirsPoints is an ee.FeatureCollection; zones
    are ee.Images. Caller initializes EE; this function only builds the graph.
    """
    confidence = maximum_confidence(viirs_collection(aoi, fire_date, analysis_end), aoi)
    fire = viirs_fire(confidence)
    points = viirs_points(fire, aoi)
    return {'viirs': fire, 'viirsFire': fire, 'viirsPoints': points,
            **viirs_zones(points, aoi)}
