# Exposure & Impact – methodology

> **Exposure estimates are preliminary. Intersecting buildings, roads or population with a satellite-derived affected area does not confirm physical damage, casualties or displacement.**
> (ES: *Las estimaciones de exposición son preliminares. La intersección de edificios, vías o población con un área potencialmente afectada no confirma daños físicos, víctimas ni desplazamientos.*)

## 1. Vocabulary (kept distinct in API and UI)
| Term | Meaning |
|---|---|
| Study area (AOI) | Municipality or user-drawn polygon given to the V7.6 analysis |
| Affected area | Pixels of the V7.6 probability map ≥ threshold (default 0.72), keeping the V7.6 post-processing |
| Exposure geometry | Polygon rebuilt from those pixels (raster-first, 20 m, UTM) – the only geometry used for intersections |
| Exposed features | OSM buildings/roads/facilities intersecting the exposure geometry (and, separately, a proximity buffer) |
| Population | WorldPop estimate inside the exposure geometry – never the whole AOI |

The module runs **only** when the user presses "Analyze Exposure". It never uses the whole AOI as hazard.

## 2. Algorithm V7.6 and AOI dependency
V7.6 is unchanged. A drawn polygon only changes the geometry fed to it. The algorithm is AOI-dependent:
training samples (`sample(region=aoi, seed)`) and the Random Forest are fitted per AOI; area statistics are
reduced over the AOI; `connectedPixelCount` has edge effects at the AOI boundary; VIIRS seeds are restricted to
the AOI. Per-pixel composites (Sentinel-2, Dynamic World) are AOI-independent.
**Therefore a drawn polygon is not numerically equivalent to the municipality that contains it**, and no such
equivalence is claimed. Results must be reported together with the AOI that produced them.

## 3. Footprint
`analysis_ref` (HMAC-signed, expiring, issued by `/wildfire/analyze`) lets the backend re-run the deterministic
V7.6 graph, download the burn mask with `getDownloadURL` (GeoTIFF, 20 m, UTM), vectorise it with rasterio (8-connected,
no `reduceToVectors`), and report area consistency against the analysis area (warning if >2 % apart). Simplification
is applied only for display and WorldPop payloads and is always reported (vertices before/after, tolerance, area change).
Large areas are downloaded as tiles (`EXPOSURE_TILE_PX`, default 640 px + 12 px margin, cropped and stitched on the 20 m grid; the first tile runs alone so Earth Engine can cache the trained Random Forest, tiles outside the study area are skipped, and `EXPOSURE_MAX_SECONDS` bounds the total) because Earth Engine evaluates a download in memory (`User memory limit exceeded` otherwise); the margin is twice the 6-pixel minimum component size of the V7.6 cleaning, so components that cross a tile border are measured exactly. Resolutions: analysis/vectorisation 20 m; display geometry may be simplified; WorldPop 100 m or 1 km grid.

## 4. OpenStreetMap (Overpass)
POST with bbox, `out count` pre-check against `OVERPASS_MAX_ELEMENTS`, `out tags geom`, descriptive User-Agent,
no rapid retries (429/5xx → source error), local exact intersection with shapely. Tag sets: `building=*`;
`highway=*` (motorway…track, `_link` merged into parent class); `amenity=hospital|clinic|doctors`, `healthcare=*`;
`amenity=school|kindergarten|college|university`. Relations are skipped and counted (warning `osm_relations_skipped`).
Roads: length of the union of geometries clipped to the footprint (no double counting). Facilities: a node inside a
polygon of the same class is dropped. A category with zero OSM features in the study area is
`null / coverage="no_osm_data"` – **never 0**. OSM completeness varies; absence of data is not absence of assets.
Buffer (default 500 m) is a proximity indicator, not a damage zone.

## 5. WorldPop
Asynchronous: `POST /v2/population` then `GET /v2/tasks/{id}` (bounded polling). Real polygon, not bbox. Year comes from
`WORLDPOP_YEAR` (default 2020), not from the event date. Failure/timeout → `sources.worldpop.status="error"`,
population `null` (never 0); other sources still returned (`status="partial"`). Key only in backend env.
**Caveat:** the publicly documented WorldPop service is v1 (`/v1/services/stats`); the v2 contract used here follows the
project specification and is unverified against the live service from this workspace. `WORLDPOP_API_VERSION=v1`
selects the documented API. Run `smoke_test_exposure.py` to see raw responses.

## 6. Sensitivity
Metrics are recomputed at thresholds 0.35/0.50/0.60/0.72/0.85 (when `include_sensitivity`), so the effect of the
threshold choice is visible.

## 7. Limits of interpretation
Satellite-derived burn areas have omission/commission error; OSM is incomplete and heterogeneous; WorldPop is a modelled
gridded surface (year-specific, not a census). None of these confirm damage, casualties or displacement.
