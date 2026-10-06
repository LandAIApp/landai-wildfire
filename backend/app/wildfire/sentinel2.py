"""Sentinel-2 PRE/POST collections, observation counts and composites (V7.6)."""
from __future__ import annotations

import ee

from .config import HISTORY_MAX_CLOUD, POST_MAX_CLOUD, PRE_MAX_CLOUD
from .historical_variability import (
    CLOUD_SCORE_COLLECTION,
    S2_COLLECTION,
    mask_historical_s2 as mask_s2,  # identical to V7.6 maskS2
)
from .spectral_indices import add_burn_indices
from .windows import get_time_windows

__all__ = [
    'mask_s2', 'linked_s2', 'build_pre_collection', 'build_post_collection',
    'observation_counts', 'build_composites', 'get_input_availability',
]


def linked_s2() -> ee.ImageCollection:
    """S2 SR Harmonized linked with Cloud Score+ (cs_cdf)."""
    return ee.ImageCollection(S2_COLLECTION).linkCollection(
        ee.ImageCollection(CLOUD_SCORE_COLLECTION), ['cs_cdf'])


def _scenes(aoi: ee.Geometry, start: ee.Date, end: ee.Date, max_cloud: int) -> ee.ImageCollection:
    return (linked_s2().filterBounds(aoi).filterDate(start, end)
            .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', max_cloud)))


def build_pre_collection(aoi: ee.Geometry, windows: dict[str, ee.Date]) -> ee.ImageCollection:
    return (_scenes(aoi, windows['PRE_START'], windows['PRE_END'], PRE_MAX_CLOUD)
            .map(mask_s2).map(add_burn_indices))


def build_post_collection(aoi: ee.Geometry, windows: dict[str, ee.Date]) -> ee.ImageCollection:
    return (_scenes(aoi, windows['POST_START'], windows['POST_END'], POST_MAX_CLOUD)
            .map(mask_s2).map(add_burn_indices))


def observation_counts(pre_collection: ee.ImageCollection,
                       post_collection: ee.ImageCollection) -> dict[str, ee.Image]:
    """Per-pixel valid observation counts and the `observed` mask."""
    pre_count = pre_collection.select('B8A').count().rename('preCount')
    post_count = post_collection.select('B8A').count().rename('postCount')
    observed = pre_count.gt(0).And(post_count.gt(0))
    return {'preCount': pre_count, 'postCount': post_count, 'observed': observed}


def build_composites(pre_collection: ee.ImageCollection, post_collection: ee.ImageCollection,
                     aoi: ee.Geometry) -> tuple[ee.Image, ee.Image]:
    """PRE = median(); POST = qualityMosaic('BurnNBR'). Both clipped to AOI.

    The asymmetry is intentional in V7.6 and must be preserved.
    """
    pre = pre_collection.median().clip(aoi)
    post = post_collection.qualityMosaic('BurnNBR').clip(aoi)
    return pre, post


def get_input_availability(aoi: ee.Geometry, fire_date: ee.Date,
                           analysis_end: ee.Date) -> ee.Dictionary:
    """Scene counts (scene-level cloud filter only) and inclusive date labels.

    Mirrors getInputAvailability in the reference. Does not train anything.
    """
    t = get_time_windows(fire_date, analysis_end)
    fmt = 'YYYY-MM-dd'
    return ee.Dictionary({
        'preScenes': _scenes(aoi, t['PRE_START'], t['PRE_END'], PRE_MAX_CLOUD).size(),
        'postScenes': _scenes(aoi, t['POST_START'], t['POST_END'], POST_MAX_CLOUD).size(),
        'historyScenes': _scenes(aoi, t['HISTORY_START'], t['HISTORY_END'], HISTORY_MAX_CLOUD).size(),
        'preStart': t['PRE_START'].format(fmt),
        'preEnd': t['PRE_END'].advance(-1, 'day').format(fmt),
        'postStart': t['POST_START'].format(fmt),
        'postEnd': analysis_end.format(fmt),
        'historyStart': t['HISTORY_START'].format(fmt),
        'historyEnd': t['HISTORY_END'].advance(-1, 'day').format(fmt),
    })
