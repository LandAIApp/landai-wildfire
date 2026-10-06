"""Connectivity cleaning, threshold masks and area statistics (V7.6)."""
from __future__ import annotations

import ee

from .config import (
    AREA_MAX_PIXELS, AREA_SCALE, AREA_TILE_SCALE, MIN_CONNECTED_PIXELS, THRESHOLD_SPECS,
)


def clean_probability_mask(probability: ee.Image, threshold: float,
                           min_pixels: int = MIN_CONNECTED_PIXELS) -> ee.Image:
    """likelihood >= threshold, selfMask, 8-connected components >= min_pixels."""
    binary = probability.gte(threshold).selfMask()
    connected = binary.connectedPixelCount(100, True)
    return binary.updateMask(connected.gte(min_pixels))


def create_threshold_masks(wildfire: ee.Image) -> dict[str, ee.Image]:
    """Return burn035, burn050, burn060, burn072, burn085."""
    return {
        key: clean_probability_mask(wildfire, threshold, MIN_CONNECTED_PIXELS).rename(band)
        for threshold, key, _area_key, band in THRESHOLD_SPECS
    }


def calculate_area_statistics(masks: dict[str, ee.Image], aoi: ee.Geometry) -> ee.Dictionary:
    """Hectares per threshold; keys wf035, wf050, wf060, wf072, wf085.

    Canonical area numbers: computed at scale=20 (tile renderings are not
    pixel-identical because connectedPixelCount depends on render resolution).
    """
    pixel_ha = ee.Image.pixelArea().divide(10000)
    stack = ee.Image.cat([
        pixel_ha.updateMask(masks[key]).rename(area_key)
        for _t, key, area_key, _band in THRESHOLD_SPECS
    ])
    return stack.reduceRegion(reducer=ee.Reducer.sum(), geometry=aoi, scale=AREA_SCALE,
                              maxPixels=AREA_MAX_PIXELS, tileScale=AREA_TILE_SCALE)
