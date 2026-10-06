# Agricultural context: V7.6

Module: `backend/app/wildfire/agricultural_context.py`, Python 3.11.
Source of truth: `wildfire_gee_reference.js` section 11 (Dynamic World,
WorldCover and agriculture blocks), plus the supplied V7.6 specification.

`build_agricultural_context(aoi, fire_date)` returns a dictionary of seven
deferred ee.Image objects. Initialize EE in the caller. AOI must be ee.Geometry;
fire_date is YYYY-MM-DD or ee.Date, validated through the unchanged historical
module. The historical interval is [fireDate - 6 months, fireDate - 15 days).

| Output key | Image band | Calculation |
| --- | --- | --- |
| cropProbability | cropProbability | median of historical Dynamic World crops |
| cropFrequency | cropFrequency | mean of per-image crops >= 0.40 |
| agricultureScore | AgricultureScore | clamp(0.50*wcCrop + 0.20*cropProbability + 0.30*cropFrequency, 0, 1) |
| agricultureStrong | agricultureStrong | AgricultureScore >= 0.55 |
| agricultureVeryStrong | agricultureVeryStrong | AgricultureScore >= 0.70 |
| waterMask | waterMask | WorldCover Map == 80 |
| builtMask | builtMask | WorldCover Map == 50 |

Dynamic World uses `GOOGLE/DYNAMICWORLD/V1`, filtered by bounds/date, with only
the `crops` band. Flags are formed per image before the mean. Each temporal
reduction is followed by unmask(0), clip(aoi), rename, in that order. Masked
observations are not zero-filled before the reductions. No cloud filter,
reflectance scaling, or synthetic empty-collection fallback is added.

WorldCover uses `ee.ImageCollection('ESA/WorldCover/v200').first().select('Map')`,
then clip(aoi). The separate `worldcover_masks(aoi)` helper also exposes `wcCrop`
(class 40, band wcCrop) for later model feature assembly. WorldCover is neither
date-filtered nor unmasked. Class masks and score thresholds retain zero values
outside the matching class; they are not self-masked.

The score band retains the exact V7.6 name `AgricultureScore`, already expected
by the validated feature assembler. Strong/very-strong and water/built bands
receive explicit API names instead of inheriting AgricultureScore or Map as in
JavaScript; this changes labels only, not pixel values, masks, or thresholds.

Public helpers: dynamic_world_collection, crop_flag, crop_statistics,
worldcover_masks, agriculture_score, agriculture_thresholds,
build_agricultural_context. Dataset IDs, weights, class codes and thresholds are
fixed V7.6 constants, not user-tunable configuration.

```python
from backend.app.wildfire.agricultural_context import build_agricultural_context

context = build_agricultural_context(aoi, '2026-08-05')
score = context['agricultureScore']  # ee.Image, band AgricultureScore
```

Agriculture is continuous contextual evidence plus derived flags, not a binary
exclusion of all crops. No penalties, training seeds, agricultural burn exception,
likelihood, classification, tiles, or remote evaluation are included.

Run `python -m pytest backend/tests -v` from the repository root. Tests cover
configuration, input validation, graph parity for datasets/reducers/masks/score,
and numerical score/threshold boundaries. Offline checks do not establish live
asset access or raster equivalence against an executed Earth Engine analysis.
