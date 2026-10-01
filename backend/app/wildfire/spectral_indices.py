"""Server-side spectral features from FIRE FOREST COLOMBIA V7.6 (Python 3.11).

Inputs must already have the reference cloud mask and division by 10000 applied.
Initialize Earth Engine in the calling application, never in this module.
"""

from __future__ import annotations

import ee

INDEX_BANDS = ('NBR', 'BurnNBR', 'NBR2', 'MIRBI', 'NDVI', 'BAIS2')
REFLECTANCE_BANDS = ('B4', 'B5', 'B8A', 'B11', 'B12')
PERIOD_BANDS = REFLECTANCE_BANDS + ('NBR',)
DIFFERENCE_BANDS = (
    'dB4', 'dB5', 'dB8A', 'dB11', 'dB12',
    'dNBR', 'dNBR2', 'dMIRBI', 'dNDVI', 'dBAIS2',
)
CONTEXT_BANDS = (
    'NBR_std', 'NDVI_std', 'NBR_change_z', 'cropProbability',
    'cropFrequency', 'wcCrop', 'AgricultureScore', 'EnhancedEvidence',
)
MODEL_BANDS = (
    tuple(f'pre_{band}' for band in PERIOD_BANDS)
    + tuple(f'post_{band}' for band in PERIOD_BANDS)
    + DIFFERENCE_BANDS + CONTEXT_BANDS
)


def _require_image(value: ee.Image, name: str) -> None:
    if not isinstance(value, ee.Image):
        raise TypeError(f'{name} must be an ee.Image')


def add_burn_indices(image: ee.Image) -> ee.Image:
    """Append the six reference indices to one masked, scaled S2 scene.

    Input: ee.Image with B4, B5, B6, B7, B8, B8A, B11 and B12 reflectance
    already divided by 10000. Output: original image plus NBR, BurnNBR, NBR2,
    MIRBI, NDVI and BAIS2. Apply to each scene BEFORE compositing; existing
    index bands are retained, with EE suffixing new collisions as in V7.6.
    Band presence and pixel values remain lazily validated by Earth Engine.
    """
    _require_image(image, 'image')
    b4, b6, b7, b8, b8a, b11, b12 = (
        image.select(band) for band in ('B4', 'B6', 'B7', 'B8', 'B8A', 'B11', 'B12')
    )
    nbr = b8a.subtract(b12).divide(b8a.add(b12)).rename('NBR')
    burn_nbr = b12.subtract(b8a).divide(b12.add(b8a)).rename('BurnNBR')
    nbr2 = b12.subtract(b11).divide(b12.add(b11)).rename('NBR2')
    mirbi = b12.multiply(10).subtract(b11.multiply(9.8)).add(2).rename('MIRBI')
    ndvi = b8.subtract(b4).divide(b8.add(b4)).rename('NDVI')
    eps = ee.Image.constant(0.0001)
    term1 = ee.Image(1).subtract(
        b6.multiply(b7).multiply(b8a).divide(b4.max(eps)).max(0).sqrt()
    )
    term2 = b12.subtract(b8a).divide(b12.add(b8a).max(eps).sqrt()).add(1)
    bais2 = term1.multiply(term2).rename('BAIS2')
    return image.addBands(ee.Image.cat(nbr, burn_nbr, nbr2, mirbi, ndvi, bais2))


def add_history_indices(image: ee.Image) -> ee.Image:
    """Return historical NBR/NDVI only, preserving system:time_start.

    Input: masked, scaled S2 ee.Image. Output: two-band ee.Image. Retains the
    reference's normalizedDifference behavior for history, distinct from PRE/POST.
    """
    _require_image(image, 'image')
    return ee.Image.cat(
        image.normalizedDifference(['B8A', 'B12']).rename('NBR'),
        image.normalizedDifference(['B8', 'B4']).rename('NDVI'),
    ).copyProperties(image, ['system:time_start'])


def temporal_differences(pre: ee.Image, post: ee.Image) -> ee.Image:
    """Return ten reference difference bands from already indexed composites.

    Inputs: PRE median and POST qualityMosaic('BurnNBR') ee.Images built from
    scenes indexed with add_burn_indices. Output: ee.Image with DIFFERENCE_BANDS.
    dNBR/dNDVI use PRE minus POST; all other differences use POST minus PRE.
    No indices are recalculated on composites and masks are not filled.
    """
    _require_image(pre, 'pre')
    _require_image(post, 'post')
    differences = [
        post.select(b).subtract(pre.select(b)).rename(f'd{b}')
        for b in REFLECTANCE_BANDS
    ]
    for band in ('NBR', 'NBR2', 'MIRBI', 'NDVI', 'BAIS2'):
        left, right = (pre, post) if band in ('NBR', 'NDVI') else (post, pre)
        differences.append(left.select(band).subtract(right.select(band)).rename(f'd{band}'))
    return ee.Image.cat(*differences)


def build_model_features(
    pre: ee.Image, post: ee.Image, context: ee.Image,
    observed: ee.Image, aoi: ee.Geometry,
) -> ee.Image:
    """Return one ee.Image with the exact 30 ordered V7.6 model predictors.

    Inputs: indexed PRE/POST composites; context containing CONTEXT_BANDS;
    single-band observed mask (preCount > 0 AND postCount > 0); AOI geometry.
    Context calculations are supplied by callers, not invented here. Output:
    MODEL_BANDS, masked by observed and clipped to AOI. Extra input bands are
    excluded. Missing bands fail when EE evaluates the graph, without getInfo.
    """
    for name, value in (('pre', pre), ('post', post), ('context', context), ('observed', observed)):
        _require_image(value, name)
    if not isinstance(aoi, ee.Geometry):
        raise TypeError('aoi must be an ee.Geometry')
    return ee.Image.cat(
        pre.select(list(PERIOD_BANDS), [f'pre_{b}' for b in PERIOD_BANDS]),
        post.select(list(PERIOD_BANDS), [f'post_{b}' for b in PERIOD_BANDS]),
        temporal_differences(pre, post),
        context.select(list(CONTEXT_BANDS)),
    ).updateMask(observed).clip(aoi)


def visualization_layers(pre: ee.Image, post: ee.Image) -> dict[str, ee.Image]:
    """Return rendered RGB ee.Images: pre_NBR, post_NBR and dNBR.

    Inputs: indexed PRE/POST composites. dNBR uses reference display limits
    (-0.20, 0.70) and palette. NBR uses a new display-only style (-1, 1), since
    the reference has no NBR layer. No tiles, URLs or client-side evaluation.
    """
    _require_image(pre, 'pre')
    _require_image(post, 'post')
    nbr_style = dict(min=-1, max=1, palette=['8B0000', 'FFFFFF', '006400'])
    return {
        'pre_NBR': pre.select('NBR').visualize(**nbr_style),
        'post_NBR': post.select('NBR').visualize(**nbr_style),
        'dNBR': temporal_differences(pre, post).select('dNBR').visualize(
            min=-0.20, max=0.70,
            palette=['2166AC', 'FFFFFF', 'FFFF00', 'FF8C00', '8B0000'],
        ),
    }
