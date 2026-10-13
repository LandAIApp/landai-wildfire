# API v2 reference
Errors always: `{"status":"error","code":"…","message":"…","details":…}`; `429` carries `Retry-After`.

## GET /api/v1/config
Public runtime limits (the frontend never hard-codes them). Example response (default settings):
```json
{"status":"ok","version":"2.0.0",
 "aoi":{"municipality":{"max_hectares":500000,"warn_hectares":100000},
        "custom":{"max_hectares":100000,"warn_hectares":50000,"min_hectares":10,"max_vertices":300},
        "min_fire_date":"2018-08-01"},
 "exposure":{"max_aoi_hectares":50000,"default_buffer_m":500,"max_buffer_m":2000,"max_layer_features":5000,
             "thresholds":[0.35,0.5,0.6,0.72,0.85],"default_threshold":0.72,
             "population_year":2020,"population_resolution":"100m"},
 "rate_limits":{"analyze":[{"count":5,"per":"hour"},{"count":20,"per":"day"}],
                "exposure":[{"count":10,"per":"hour"},{"count":40,"per":"day"}],"enabled":true},
 "sources":{"openstreetmap":"Overpass API (ODbL)","worldpop":"WorldPop v2",
            "earth_observation":"Sentinel-2 / VIIRS via Google Earth Engine"}}
```

## POST /api/v1/wildfire/preflight  and  /analyze
Mode A (unchanged): `{"department","municipality","fire_date","analysis_end"}`.
Mode B: `{"geometry":{"type":"Polygon","coordinates":[[[lon,lat],…]]},"fire_date","analysis_end"}`.
Sending both modes → 422 `invalid_request`. Only `Polygon` (no MultiPolygon). Validation: closed ring, ≥4 positions, ≤`max_vertices`,
valid lon/lat range, no self-intersection, no NaN, area between min and max hectares (geodesic/metric). Polygons are
rejected, never silently truncated or repaired. Preflight returns `aoi_hectares`, `aoi_kind` (`municipality|drawn`),
`blocking_errors` (`aoi_too_large`, `aoi_too_small`, `geometry_out_of_range`, `geometry_self_intersecting`, `geometry_degenerate`, `geometry_holes`, `geometry_too_few_points`, `geometry_too_many_points`; warning `aoi_large`), `warnings`.
`analyze` additionally returns `analysis_ref` (signed, expires after `ANALYSIS_REF_TTL_SECONDS`) and `aoi`.

## POST /api/v1/exposure/analyze
Explicit user action only. Exactly one mode:
```json
{"analysis_ref":"<from analyze>","threshold":0.72,"buffer_m":500,"include_population":true,"include_sensitivity":true}
```
or (external polygon – separate, identified mode, not the validated workflow):
```json
{"hazard_geometry":{"type":"Polygon","coordinates":[…]},"aoi_geometry":{"type":"Polygon","coordinates":[…]}}
```
Response: `status` (`success|partial`), `mode` (`wildfire_analysis|external_polygon`), `analysis` (study area, affected area ha,
% of AOI, threshold, simplification report), `metrics` (each `{value,coverage,unit}`; `value:null` = unavailable/no data),
`details`, `sensitivity[]`, `sources{osm,worldpop}` (`success|error|skipped` + error object), `warnings[]`, `layers` (GeoJSON, capped),
`exports` (GeoJSON/CSV/metadata data), `notice` (`en`,`es` methodological notice).
Error codes: `invalid_analysis_ref` (422), `exposure_aoi_too_large` (422), `footprint_extraction_failed` (502), `no_affected_area` (422),
`server_busy` (503, concurrency gate), `rate_limit_exceeded` (429), `earth_engine_*`; per-source (inside `sources.*.error`):
`osm_timeout|osm_unavailable|osm_rate_limited|osm_response_too_large|osm_incomplete|osm_too_many_elements`,
`worldpop_timeout|worldpop_unreachable|worldpop_task_failed|worldpop_bad_response|worldpop_http_error|worldpop_rate_limited|worldpop_geometry_too_complex`.
OSM or WorldPop failure yields `partial` with that source in `error` – never zero values.
