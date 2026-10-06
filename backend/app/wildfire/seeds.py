"""V7.6 pseudo-supervised training seeds (positive and negative)."""
from __future__ import annotations

import ee


def positive_seed(*, viirs_seed_zone: ee.Image, viirs_prior_zone: ee.Image,
                  enhanced: ee.Image, dnbr: ee.Image, dmirbi: ee.Image,
                  nbr_change_z: ee.Image, agri_strong: ee.Image,
                  agri_very_strong: ee.Image, water: ee.Image, built: ee.Image,
                  observed: ee.Image) -> ee.Image:
    """positiveSeed = fireSeed OR spectralSeed OR agriculturalFireSeed."""
    fire_seed = (viirs_seed_zone.eq(1)
                 .And(enhanced.gt(0.40))
                 .And(dnbr.gt(0.08))
                 .And(observed))
    spectral_seed = (enhanced.gt(0.72)
                     .And(nbr_change_z.gt(2.3))
                     .And(dnbr.gt(0.22))
                     .And(dmirbi.gt(0.06))
                     .And(agri_very_strong.Not())
                     .And(water.Not())
                     .And(built.Not())
                     .And(observed))
    agricultural_fire_seed = (agri_strong
                              .And(viirs_prior_zone.eq(1))
                              .And(enhanced.gt(0.80))
                              .And(nbr_change_z.gt(3.0))
                              .And(dnbr.gt(0.30))
                              .And(dmirbi.gt(0.10))
                              .And(observed))
    return (fire_seed.Or(spectral_seed).Or(agricultural_fire_seed)
            .selfMask().rename('PositiveSeed'))


def negative_seed(*, dnbr: ee.Image, dmirbi: ee.Image, agri_strong: ee.Image,
                  agri_very_strong: ee.Image, crop_frequency: ee.Image,
                  nbr_change_z: ee.Image, enhanced: ee.Image,
                  viirs_seed_zone: ee.Image, viirs_prior_zone: ee.Image,
                  nbr_std: ee.Image, ndvi_std: ee.Image, water: ee.Image,
                  built: ee.Image, observed: ee.Image) -> ee.Image:
    """negativeSeed = union of the five V7.6 negative rules."""
    stable = dnbr.lt(0.03).And(dmirbi.lt(0.03)).And(observed)
    crop_hard = (agri_strong
                 .And(crop_frequency.gt(0.30))
                 .And(nbr_change_z.lt(2.0))
                 .And(viirs_prior_zone.eq(0))
                 .And(observed))
    very_strong_crop = (agri_very_strong
                        .And(enhanced.lt(0.72))
                        .And(viirs_seed_zone.eq(0))
                        .And(observed))
    seasonal_crop = (agri_strong
                     .And(nbr_std.gt(0.14))
                     .And(ndvi_std.gt(0.14))
                     .And(enhanced.lt(0.65))
                     .And(viirs_prior_zone.eq(0))
                     .And(observed))
    surface = water.Or(built).And(observed)
    return (stable.Or(crop_hard).Or(very_strong_crop).Or(seasonal_crop).Or(surface)
            .selfMask().rename('NegativeSeed'))
