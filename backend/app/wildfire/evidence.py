"""V7.6 spectral and enhanced evidence."""
from __future__ import annotations

import ee


def scale01(image: ee.Image, low: float, high: float) -> ee.Image:
    """clip((x - low) / (high - low), 0, 1) exactly as V7.6."""
    return image.subtract(low).divide(ee.Number(high).subtract(low)).clamp(0, 1)


def spectral_evidence(differences: ee.Image) -> ee.Image:
    """Weighted combination of five normalized change indices (weights sum to 1)."""
    e_dnbr = scale01(differences.select('dNBR'), 0.08, 0.50)
    e_mirbi = scale01(differences.select('dMIRBI'), 0.03, 0.45)
    e_nbr2 = scale01(differences.select('dNBR2'), 0.01, 0.20)
    e_ndvi = scale01(differences.select('dNDVI'), 0.03, 0.35)
    e_bais2 = scale01(differences.select('dBAIS2'), 0.05, 1.50)
    return (e_dnbr.multiply(0.32)
            .add(e_mirbi.multiply(0.22))
            .add(e_nbr2.multiply(0.14))
            .add(e_ndvi.multiply(0.14))
            .add(e_bais2.multiply(0.18))
            .rename('SpectralEvidence'))


def enhanced_evidence(spectral: ee.Image, anomaly: ee.Image) -> ee.Image:
    """0.75 * SpectralEvidence + 0.25 * AnomalyEvidence."""
    return (spectral.multiply(0.75).add(anomaly.multiply(0.25))
            .rename('EnhancedEvidence'))
