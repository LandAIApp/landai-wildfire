# VIIRS context: V7.6

Module: `backend/app/wildfire/viirs.py`. Reference: sections 7 and 11 of
`wildfire_gee_reference.js` and section 18 of the supplied V7.6 specification.
Python target: 3.11. Initialize Earth Engine in the caller.

Both `NASA/LANCE/SNPP_VIIRS/C2` and `NASA/LANCE/NOAA20_VIIRS/C2` are filtered by
AOI and [fireDate - 10 days, analysisEnd + 1 day). Each scene selects confidence,
applies unmask(0), converts to byte, renames confidence and copies
system:time_start. SNPP is merged with NOAA20 in that order.

A constant-zero byte confidence image clipped to AOI is always prepended before
the temporal maximum, not just when empty. This reproduces V7.6's fallback and
mask behavior without querying collection size. The maximum is cast to byte
and named confidence. Fire is confidence >= 1, then selfMask(), toByte(), and
rename('VIIRS'). There is no confidence recoding, rescaling, or optimization.

Vectorization retains scale 375, geometryType centroid, eightConnected true,
maxPixels 1e7, tileScale 4, and all other EE defaults. Centroids represent connected
fire components, not necessarily individual detections. Feature buffers use
700 m and 3000 m, then are painted with value 1 onto ee.Image(0).byte() and clipped
to AOI. Zero-valued zone backgrounds are preserved without selfMask().

| Output key | Type | Band / meaning |
| --- | --- | --- |
| viirs | ee.Image | VIIRS; alias of viirsFire, as in the reference return object |
| viirsFire | ee.Image | VIIRS; masked byte fire evidence |
| viirsPoints | ee.FeatureCollection | Connected-component centroids |
| viirsSeedZone | ee.Image | constant; 700 m buffers, 0/1 |
| viirsPriorZone | ee.Image | constant; 3000 m buffers, 0/1 |

Zone band names intentionally remain `constant`, exactly as in the reference.
The intermediate maximum confidence image is available through maximum_confidence
and retains the band confidence; it is not the viirs output.

```python
from backend.app.wildfire.viirs import build_viirs_context

result = build_viirs_context(aoi, '2026-08-05', '2026-08-15')
```

AOI must be ee.Geometry. Dates accept YYYY-MM-DD or ee.Date; local strings are
checked for valid dates and analysisEnd >= fireDate. Server-side/mixed date
ordering remains the caller's responsibility, as in the reference UI gate.
No getInfo, remote evaluation, tiles, reprojection, seeds or Random Forest is added.

Functions: viirs_window, normalize_viirs_confidence, viirs_collection,
maximum_confidence, viirs_fire, viirs_points, viirs_zones, build_viirs_context.

Tests run offline with `python -m pytest backend/tests -v`. They compare real EE
graphs against the reference operation sequence, including empty collections,
date boundaries, vector parameters, buffer distances and output aliases, and
check invalid inputs. Live GEE asset access and raster results require separate
integration validation.
