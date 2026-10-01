LAND AI WILDFIRE – GEE REFERENCE

Purpose:
Reference implementation before migration to Python/FastAPI.

Current inputs:
- Municipality
- Event date
- Pre period
- Post period

Datasets:
- Sentinel-2
- VIIRS
- Municipality FeatureCollection
- Validation polygons

Current outputs:
- Pre image
- Post image
- Index differences
- VIIRS hotspots
- Burn probability
- Final burn delimitation
- Exportable products

Known limitations:
- Agricultural areas can generate false positives
- Cloud availability affects optical processing
- Sentinel-1 was tested but did not improve discrimination sufficiently