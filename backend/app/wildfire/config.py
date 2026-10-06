"""Scientific parameters of V7.6 that are not owned by another module.

These values are copied from wildfire_gee_reference.js and must not be tuned
during equivalence work.
"""
from __future__ import annotations

# Scene-level cloud filters (CLOUDY_PIXEL_PERCENTAGE < value)
PRE_MAX_CLOUD = 85
POST_MAX_CLOUD = 90
HISTORY_MAX_CLOUD = 85

# Random Forest
N_TREES = 150
RF_VARIABLES_PER_SPLIT = None  # JS null
RF_MIN_LEAF_POPULATION = 3
RF_BAG_FRACTION = 0.65
RF_SEED = 2026

# Training samples (numPixels is an APPROXIMATE request in Earth Engine)
N_POSITIVE_SAMPLES = 3000
N_NEGATIVE_SAMPLES = 5000
POSITIVE_SAMPLE_SEED = 2026
NEGATIVE_SAMPLE_SEED = 2027
SAMPLE_SCALE = 20
SAMPLE_TILE_SCALE = 4

# Spatial cleaning
MIN_CONNECTED_PIXELS = 6

# Area statistics
AREA_SCALE = 20
AREA_MAX_PIXELS = 1e9
AREA_TILE_SCALE = 8

# Final delimitation thresholds: (threshold, mask key, area key, band name).
# V7.6 writes these literally; the keys wf035..wf085 are part of the contract.
THRESHOLD_SPECS = (
    (0.35, 'burn035', 'wf035', 'Burn035'),
    (0.50, 'burn050', 'wf050', 'Burn050'),
    (0.60, 'burn060', 'wf060', 'Burn060'),
    (0.72, 'burn072', 'wf072', 'Burn072'),
    (0.85, 'burn085', 'wf085', 'Burn085'),
)
