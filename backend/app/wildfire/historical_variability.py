"""V7.6 historical Sentinel-2 variability and anomaly, evaluated by Earth Engine.

Python 3.11. The caller initializes EE. No authentication or remote evaluation
occurs here. Constants preserve the reference rather than expose new tuning.
"""

from __future__ import annotations

from datetime import date
import re

import ee

from .spectral_indices import add_history_indices

S2_COLLECTION = 'COPERNICUS/S2_SR_HARMONIZED'
CLOUD_SCORE_COLLECTION = 'GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED'
CLEAR_THRESHOLD = 0.55
EXCLUDED_SCL_CLASSES = (1, 3, 7, 8, 9, 10, 11)
OUTPUT_BANDS = ('NBR_std', 'NDVI_std', 'NBR_change_z', 'AnomalyEvidence')


def validate_fire_date(fire_date: str | ee.Date) -> str | ee.Date:
    """Return a valid YYYY-MM-DD string or an unevaluated ee.Date unchanged.

    Invalid local dates raise ValueError; unsupported types raise TypeError.
    Server-side dates are left to Earth Engine for validation.
    """
    if isinstance(fire_date, ee.Date):
        return fire_date
    if not isinstance(fire_date, str):
        raise TypeError('fire_date must be a YYYY-MM-DD string or ee.Date')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', fire_date):
        raise ValueError('fire_date must use YYYY-MM-DD')
    date.fromisoformat(fire_date)
    return fire_date


def historical_window(fire_date: str | ee.Date) -> tuple[ee.Date, ee.Date]:
    """Return (start, exclusive end) as ee.Dates: -6 months and -15 days.

    Input is an ISO date string or ee.Date. Calendar arithmetic remains in EE;
    six months is not approximated as a fixed number of days.
    """
    fire = ee.Date(validate_fire_date(fire_date))
    return fire.advance(-6, 'month'), fire.advance(-15, 'day')


def mask_historical_s2(image: ee.Image) -> ee.Image:
    """Mask and scale one RAW S2 image linked to the cs_cdf cloud-score band.

    Output retains original bands, applies cs_cdf >= .55 and excludes SCL
    1/3/7/8/9/10/11, divides the entire image by 10000, and copies acquisition
    time. Do not pass an already scaled image. Missing bands remain EE errors.
    """
    if not isinstance(image, ee.Image):
        raise TypeError('image must be an ee.Image')
    clear = image.select('cs_cdf').gte(CLEAR_THRESHOLD)
    scl = image.select('SCL')
    valid = scl.neq(EXCLUDED_SCL_CLASSES[0])
    for excluded in EXCLUDED_SCL_CLASSES[1:]:
        valid = valid.And(scl.neq(excluded))
    return (image.updateMask(clear).updateMask(valid).divide(10000)
            .copyProperties(image, ['system:time_start']))


def historical_collection(aoi: ee.Geometry, fire_date: str | ee.Date) -> ee.ImageCollection:
    """Return a filtered historical collection containing NBR and NDVI per scene.

    Inputs: AOI ee.Geometry and fire date. Links S2 SR Harmonized to Cloud Score+,
    filters bounds, the exclusive historical window and scene cloudiness <85,
    then applies V7.6 masking/scaling and the existing historical index helper.
    No clipping, fallback scene, or minimum-count substitution is introduced.
    """
    if not isinstance(aoi, ee.Geometry):
        raise TypeError('aoi must be an ee.Geometry')
    start, end = historical_window(fire_date)
    linked = ee.ImageCollection(S2_COLLECTION).linkCollection(
        ee.ImageCollection(CLOUD_SCORE_COLLECTION), ['cs_cdf']
    )
    return (linked.filterBounds(aoi).filterDate(start, end)
            .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 85))
            .map(mask_historical_s2).map(add_history_indices))


def temporal_variability(history: ee.ImageCollection) -> ee.Image:
    """Reduce historical NBR/NDVI to NBR_std and NDVI_std in one ee.Image.

    Input: indexed historical collection. Uses ee.Reducer.stdDev(), followed by
    rename and unmask(0) on each band, exactly as V7.6. Empty collection errors
    are not replaced with synthetic images; no new footprint or clip is applied.
    """
    if not isinstance(history, ee.ImageCollection):
        raise TypeError('history must be an ee.ImageCollection')
    return ee.Image.cat(*[
        history.select(band).reduce(ee.Reducer.stdDev()).rename(f'{band}_std').unmask(0)
        for band in ('NBR', 'NDVI')
    ])


def nbr_change_anomaly(dnbr: ee.Image, variability: ee.Image) -> ee.Image:
    """Return NBR_change_z = clamp(dNBR / (NBR_std + .03), -10, 10).

    Inputs: ee.Image containing dNBR (PRE minus POST), and an ee.Image containing
    NBR_std. Extra bands are ignored. Output is a single-band ee.Image, preserving
    EE arithmetic masks; the dNBR input is neither unmasked nor rescaled.
    """
    if not isinstance(dnbr, ee.Image) or not isinstance(variability, ee.Image):
        raise TypeError('dnbr and variability must be ee.Image objects')
    return (dnbr.select('dNBR').divide(variability.select('NBR_std').add(0.03))
            .clamp(-10, 10).rename('NBR_change_z'))


def anomaly_evidence(anomaly: ee.Image) -> ee.Image:
    """Return AnomalyEvidence = clamp((NBR_change_z - 1) / (5 - 1), 0, 1).

    Input: ee.Image containing NBR_change_z. Output: single-band ee.Image using
    V7.6 scale01 normalization. This is evidence, not a calibrated probability.
    """
    if not isinstance(anomaly, ee.Image):
        raise TypeError('anomaly must be an ee.Image')
    return (anomaly.select('NBR_change_z').subtract(1).divide(ee.Number(5).subtract(1))
            .clamp(0, 1).rename('AnomalyEvidence'))


def build_historical_features(aoi: ee.Geometry, fire_date: str | ee.Date, dnbr: ee.Image) -> ee.Image:
    """Return one ee.Image with OUTPUT_BANDS in order, from AOI/date/dNBR.

    dNBR must come from indexed PRE/POST composites. The caller remains responsible
    for the reference availability check (at least two historical scenes) before
    executing the full workflow. This helper only constructs the deferred graph.
    """
    if not isinstance(dnbr, ee.Image):
        raise TypeError('dnbr must be an ee.Image')
    variability = temporal_variability(historical_collection(aoi, fire_date))
    anomaly = nbr_change_anomaly(dnbr, variability)
    return ee.Image.cat(variability, anomaly, anomaly_evidence(anomaly))
