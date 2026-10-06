# V7.6 equivalence: JavaScript vs Python

**Status: structural equivalence verified offline; numerical/spatial/statistical equivalence NOT yet run.**
No claim of runtime equivalence is made until the procedures below are executed with Earth Engine access.

## What is already covered by tests (no Earth Engine needed)
- Exact 30-band predictor stack and order (`test_model_graph.py`).
- All scientific constants: thresholds, RF config, sample counts/seeds, 6-pixel rule.
- Time windows as EE expressions; full `run_burn_model` graph builds and serializes with all 19 contract keys.
- Per-module graph parity tests (indices, history, agriculture, VIIRS).

## A. Structural
Run `pytest`. Optionally diff `ee.Image.serialize()` of each layer against the graph produced by
the JS script (Code Editor: `print(image.serialize())`) for a small AOI.

## B. Numerical (continuous layers)
Same AOI, dates, scale. For `pre, post, dNBR, spectralEvidence, enhancedEvidence,
agricultureScore, observationQuality, viirs`: compare `reduceRegion` (mean, stdDev, min, max, count)
at scale 20. Expect agreement to floating-point tolerance. Deterministic layers should match
exactly; any difference is a discrepancy to fix.

## C. Spatial (masks and areas)
Compare `areaStatistics` (`wf035…wf085`) and `Burn*` masks via `reduceRegion` at scale=20.
Do **not** compare tile renderings: `connectedPixelCount` depends on render resolution.

## D. Statistical (Random Forest)
`sample()` is approximate and the RF is retrained per run, so bit-exact `RFLikelihood` is not
expected. Compare actual positive/negative training counts (API `training`), the `RFLikelihood`
histogram, and downstream area differences across several AOIs and dates. Define an acceptance
tolerance (e.g. relative area difference) BEFORE running.

## Discrepancy policy
If Python differs from JS, fix Python. Scientific improvements go on a separate branch
(e.g. `feature/wildfire-v7.6-plus`). Once validated, tag `wildfire-v7.6-python-equivalent`.

## External validation (separate from equivalence)
The 278 independent polygons (133 burned / 145 unburned) are validation data only and must not be
used for training. Planned metrics: confusion matrix, precision, recall, specificity, F1, balanced
accuracy, ROC/AUC on `WildfireLikelihood`, at thresholds 0.35/0.50/0.60/0.72/0.85, with spatial
leakage control. Not implemented in this MVP.

## Backlog (not implemented)
Threshold calibration, temporal persistence, fewer agricultural false positives, VIIRS vectorization
optimization, caching of S2/Dynamic World history, repeated `connectedPixelCount`, async jobs,
GeoJSON/CSV/GeoTIFF export, PDF reports, persistence, auth, PostGIS, foundation models.
