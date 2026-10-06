"""V7.6 probability construction: base, agricultural penalties and exception."""
from __future__ import annotations

import ee


def observation_quality(pre_count: ee.Image, post_count: ee.Image) -> ee.Image:
    """sqrt(min(pre,3)/3 * min(post,3)/3)."""
    return (pre_count.min(3).divide(3)
            .multiply(post_count.min(3).divide(3))
            .sqrt().rename('ObservationQuality'))


def base_likelihood(rf: ee.Image, enhanced: ee.Image, viirs_prior_zone: ee.Image,
                    water: ee.Image, built: ee.Image, quality: ee.Image) -> ee.Image:
    viirs_bonus = viirs_prior_zone.eq(1).multiply(0.08)
    surface_penalty = water.Or(built).multiply(0.40)
    return (rf.multiply(0.72)
            .add(enhanced.multiply(0.28))
            .add(viirs_bonus)
            .subtract(surface_penalty)
            .multiply(quality.multiply(0.15).add(0.85))
            .clamp(0, 1)
            .rename('BaseLikelihood'))


def cleaned_likelihood(base: ee.Image, agri_score: ee.Image, crop_frequency: ee.Image,
                       enhanced: ee.Image, anomaly: ee.Image,
                       nbr_std: ee.Image, ndvi_std: ee.Image) -> ee.Image:
    """BaseLikelihood minus the three agricultural penalties (clamped 0-1)."""
    agriculture_penalty = agri_score.multiply(0.45).multiply(ee.Image(1).subtract(enhanced))
    crop_frequency_penalty = crop_frequency.multiply(0.20).multiply(ee.Image(1).subtract(anomaly))
    temporal_variability = nbr_std.add(ndvi_std).divide(2).clamp(0, 0.30).divide(0.30)
    variability_penalty = temporal_variability.multiply(agri_score).multiply(0.15)
    return (base.subtract(agriculture_penalty)
            .subtract(crop_frequency_penalty)
            .subtract(variability_penalty)
            .clamp(0, 1).rename('CleanedBurnLikelihood'))


def apply_agricultural_exception(cleaned: ee.Image, base: ee.Image, enhanced: ee.Image,
                                 nbr_change_z: ee.Image, agri_strong: ee.Image,
                                 agri_very_strong: ee.Image,
                                 viirs_prior_zone: ee.Image) -> tuple[ee.Image, ee.Image]:
    """Return (WildfireLikelihood, AgriculturalBurnAccepted).

    Accepted pixels get max(BaseLikelihood, 0.72) (a no-op in practice because
    acceptance already requires Base > 0.78, kept for fidelity). Very strong
    agriculture is masked unless the exception accepted the pixel.
    """
    accepted = (agri_strong
                .And(base.gt(0.78))
                .And(enhanced.gt(0.72))
                .And(nbr_change_z.gt(2.5))
                .And(viirs_prior_zone.eq(1).Or(enhanced.gt(0.87)))
                .rename('AgriculturalBurnAccepted'))
    cleaned = (cleaned.where(accepted, base.max(ee.Image.constant(0.72)))
               .rename('CleanedBurnLikelihood'))
    valid_surface = agri_very_strong.Not().Or(accepted)
    wildfire = cleaned.updateMask(valid_surface).rename('WildfireLikelihood')
    return wildfire, accepted
