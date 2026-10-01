# Spectral indices (V7.6)

Module: `backend/app/wildfire/spectral_indices.py`. Python target: 3.11.
Source of truth: root `wildfire_gee_reference.js`, sections 4, 5 and 11.

Initialize Earth Engine in the caller. Supply masked Sentinel-2 reflectance already
divided by 10000, exactly as `maskS2` does. This module neither rescales nor fills
masked pixels. Do not supply raw integer S2 bands.

## Processing order

```python
from backend.app.wildfire.spectral_indices import (
    add_burn_indices, build_model_features, temporal_differences,
    visualization_layers,
)

# pre_collection/post_collection: already filtered, masked and scaled ee collections.
pre = pre_collection.map(add_burn_indices).median().clip(aoi)
post = post_collection.map(add_burn_indices).qualityMosaic('BurnNBR').clip(aoi)
changes = temporal_differences(pre, post)
# context: eight named bands supplied by later workflow modules.
# observed: (preCount > 0) AND (postCount > 0), computed upstream.
features = build_model_features(pre, post, context, observed, aoi)
layers = visualization_layers(pre, post)
```

Indices are computed per scene before compositing. In particular, the median of
an index is not generally the index of median reflectance. The module does not
implement acquisition, cloud masking, historical reducers, agricultural evidence,
classification, or tiles.

## Formulas

| Band | Formula |
| --- | --- |
| NBR | (B8A - B12) / (B8A + B12) |
| BurnNBR | (B12 - B8A) / (B12 + B8A) |
| NBR2 | (B12 - B11) / (B12 + B11) |
| MIRBI | 10 B12 - 9.8 B11 + 2 |
| NDVI | (B8 - B4) / (B8 + B4) |
| BAIS2 | (1 - sqrt(max(B6 B7 B8A / max(B4, 0.0001), 0))) (1 + (B12 - B8A) / sqrt(max(B12 + B8A, 0.0001))) |

PRE/POST use explicit arithmetic, without new denominator guards outside BAIS2.
The historical helper uses normalizedDifference and copies system:time_start,
as in the reference. This distinction preserves its negative-input masking
behavior ([Earth Engine documentation](https://developers.google.com/earth-engine/apidocs/ee-image-normalizeddifference)).

dNBR and dNDVI are PRE minus POST. dNBR2, dMIRBI, dBAIS2 and the five reflectance
differences (B4, B5, B8A, B11, B12) are POST minus PRE.

## Output contract

`build_model_features` returns exactly 30 ordered bands, with the reference mask
and AOI clip:

1. pre_B4, pre_B5, pre_B8A, pre_B11, pre_B12, pre_NBR.
2. post_B4, post_B5, post_B8A, post_B11, post_B12, post_NBR.
3. dB4, dB5, dB8A, dB11, dB12, dNBR, dNBR2, dMIRBI, dNDVI, dBAIS2.
4. NBR_std, NDVI_std, NBR_change_z, cropProbability, cropFrequency, wcCrop,
   AgricultureScore, EnhancedEvidence (required context input).

All six indices remain available in each indexed composite; only NBR and the
listed differences enter the reference predictor stack. Missing server-side
bands are reported by EE at evaluation time; local validation checks object types.
No getInfo, reproject, classification or remote evaluation is performed here.

The visualization helper returns three RGB ee.Images: pre_NBR, post_NBR and dNBR.
dNBR uses the original limits/palette. NBR has a new display-only style (-1 to 1,
dark red/white/dark green), since the reference does not display NBR itself.
Index enrichment preserves existing bands and uses Earth Engine's default suffixes
for name collisions, exactly as the reference addBands call does.

## Tests

From the repository root, with its requirements installed:

```powershell
python -m pytest backend/tests/test_spectral_indices.py
```

Offline scalar tests cover formulas, scaling, BAIS2 guards and change directions.
Real EE graph tests use the API package's bundled test signatures to check lazy
construction without credentials. These do not replace live raster equivalence
validation against the GEE reference.
