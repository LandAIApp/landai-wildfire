# Historical variability and anomaly: V7.6

Implementation: `backend/app/wildfire/historical_variability.py` (Python 3.11).
Source: `wildfire_gee_reference.js`, sections 2, 3, 5, 6, 8 and the historical
and anomaly blocks in section 11. The historical index helper in
`spectral_indices.py` is reused unchanged.

The collection uses `COPERNICUS/S2_SR_HARMONIZED` linked to
`GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED` for `cs_cdf`. Filters apply to AOI,
the interval [fireDate - 6 calendar months, fireDate - 15 days), and
`CLOUDY_PIXEL_PERCENTAGE < 85`.

Masking requires `cs_cdf >= 0.55` and excludes SCL 1, 3, 7, 8, 9, 10, 11.
The entire raw image is divided by 10000 after masking, preserving acquisition
time. Historical NBR uses normalizedDifference(B8A, B12); NDVI uses
normalizedDifference(B8, B4), including the reference's masking behavior.

Per-scene output bands: **NBR, NDVI**.

The combined output is one ee.Image, in this exact order:

| Band | Calculation |
| --- | --- |
| NBR_std | NBR collection reduced with ee.Reducer.stdDev(), then unmask(0) |
| NDVI_std | NDVI collection reduced with ee.Reducer.stdDev(), then unmask(0) |
| NBR_change_z | clamp(dNBR / (NBR_std + 0.03), -10, 10) |
| AnomalyEvidence | clamp((NBR_change_z - 1) / (5 - 1), 0, 1) |

`NBR_change_z` is a variability-normalized change, not a conventional z-score.
No extra clipping, resampling, reprojection, filling of dNBR, or synthetic scene
is added. The default footprint behavior of unmask(0) is preserved.

```python
from backend.app.wildfire.historical_variability import build_historical_features

# Caller initializes EE. aoi is ee.Geometry; changes contains upstream dNBR.
historical = build_historical_features(aoi, '2026-08-05', changes)
```

Dates may also be ee.Date objects. ISO strings are checked locally for valid
YYYY-MM-DD dates; EE dates, image bands and pixel values remain server-side.
The caller must retain V7.6's availability gate of at least two historical scenes
before evaluating the full workflow. This module does not introduce a new fallback
for missing data or perform a synchronous count request.

Public functions: validate_fire_date, historical_window, mask_historical_s2,
historical_collection, temporal_variability, nbr_change_anomaly, anomaly_evidence,
build_historical_features. Initialization and credentials are caller-owned.
No training, agriculture processing, VIIRS, classification or tiles are included.

Run `python -m pytest backend/tests -v` from the repository root. Tests cover
local validation, exact EE graph structure for dates/masks/filters/reducers/formulas,
output assembly and prohibited calls. Offline graph checks do not validate live
data availability, asset access or raster equivalence against the running GEE app.
