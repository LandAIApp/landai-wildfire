# Performance and cost control (controlled public deployment)

Scope: reduce unnecessary computation, external calls and cloud usage **without touching the scientific algorithm**
(V7.6, thresholds, 20 m raster footprint, cleaning, exposure definitions) and **without new paid or persistent
infrastructure** (no database, Redis, Cloud SQL/Tasks, storage buckets). Nothing here can guarantee zero cost.

## 1. Diagnosis (measured, not guessed)

Source: the backend logs of a real run on a drawn area of ~19,700 ha (before this release), exposure request = 460 s
(the wildfire analysis of the same event took 40.8 s in that run, ~80 s in an earlier one).

| Stage | Measured | Share | Evidence |
|---|---:|---:|---|
| Earth Engine footprint download (4 tiles) | 58 s | 13 % | `footprint_tile 1/4 … 36.7 s`, the other three 4.7–20.8 s |
| Preparation (OSM region) | 35 s | 8 % | `exposure_prepared seconds=34.9` |
| Sources, in parallel (Overpass 9 cells + WorldPop) | 139.5 s | 30 % | `exposure_sources_done seconds=139.5`; Overpass 429 twice (waits of 10–36 s), cells 7–9 ≈ 23 s each; WorldPop finished early |
| **Local spatial stage after the sources** | **222 s** | **48 %** | time between `exposure_sources_done` and `exposure_completed`; it had no log of its own |

Top three bottlenecks: (1) the local spatial stage, (2) Overpass, (3) preparation + Earth Engine download.

**Cause of the largest one.** The proximity buffer of the raw 20 m raster outline (hundreds of fragments, tens of
thousands of stair-step vertices) was built **7 times** per request: once for the selected threshold, once for each of the
five rows of the sensitivity table and once for the display layer. The sensitivity table only reports what *intersects*,
so five of those buffers were never used.

**Reproduction (offline, deterministic, `backend/scripts/bench_exposure.py`).** Synthetic fragmented footprints for the
5 thresholds (1,131 parts at 0.85, 28k vertices, 3,145 ha), 200 buildings, 450 road segments, instant fake sources:

| Version | `build_response` (local work only) | area | buildings (inside / ≤500 m) | roads km (inside / ≤500 m) | sensitivity rows |
|---|---:|---:|---|---|---|
| before (commit `ab370e3`) | **83.9 s** | 3,145.0 ha | 41 / 200 | 102.2854 / 660.6998 | identical |
| after | **11.3 s** | 3,145.0 ha | 41 / 200 | 102.2854 / 660.6998 | identical |

All numbers are identical, so the speed-up is not a simplification of the geometry. The remaining 11 s are mostly the one
exact buffer (~8 s) and the intersections (~2 s). The real run was 222 s, so the real footprint is heavier than the synthetic
one; expect a large reduction, not a specific number. Real-service timings (Earth Engine, Overpass, WorldPop) cannot be
benchmarked offline: compare the `exposure_timing` log line of a new run with the table above.

## 2. What was changed (file by file)

| File | Change | Reason |
|---|---|---|
| `backend/app/services/exposure.py` | proximity zone built once and reused (metrics + display layer); stage timings (`analysis.processing.timings_s`, log `exposure_timing`); footprint cache; result cache; single-flight; live stages; OSM region uses only the thresholds the request needs; kill switch | bottleneck 1; repeated work; visibility |
| `backend/app/services/exposure_metrics.py` | `compute(..., zone=None)` accepts a pre-built zone | avoid rebuilding it |
| `backend/app/services/osm.py` | `fetch(..., on_progress)` reports cells done/total | real stage detail |
| `backend/app/services/analysis.py` | guarded entry point: kill switch, `analysis` concurrency gate, single-flight for identical concurrent requests, live stages | protect the instance; no duplicate EE work |
| `backend/app/core/memo.py` (new) | bounded TTL cache + single-flight, `fingerprint()` | cache keys that contain everything |
| `backend/app/core/progress.py` (new) | in-memory stage registry (stage names, states, seconds, counters only) | honest progress without background jobs |
| `backend/app/api/progress.py` (new), `main.py`, `api/config.py`, `core/rate_limit.py`, `core/config.py`, `core/errors.py`, `schemas/*.py` | progress endpoint, `service` block in `/config`, new settings, `service_paused`, optional `progress_id`; `httpx`/`httpcore` logs set to WARNING | operations; security |
| `backend/scripts/bench_exposure.py` (new) | offline benchmark | before/after evidence |
| `frontend/src/**` | real stages list (analysis + exposure), double-click guards, limitations text, paused notice, cached-result notice (ES/EN) | UX; abuse prevention |

Not changed: the V7.6 graph and its tests, thresholds, 20 m scale, cleaning, footprint vectorisation, OSM categories and
tag sets, WorldPop request, definition of every metric, exports, visual design.

## 3. What can and cannot be reused from the wildfire analysis

* **The Earth Engine result cannot be reused.** Earth Engine keeps no result between requests, and materialising the final
  mask (Export to Asset/Drive/Cloud Storage) is persistent storage, which is out of scope. The Exposure request therefore
  re-evaluates the *same deterministic* V7.6 graph (fixed seeds) and downloads the cleaned masks; the footprint matches the
  analysis-time area within 0.3 % (see `area_difference_pct`). Earth Engine's own short-lived cache explains why the first
  tile can take 37 s right after the analysis and 98 s later.
* **What is reused now** (in this process only): the footprint already downloaded and vectorised for the *same* analysis
  (AOI, dates, model version, tile size). Changing the threshold or buffer, or retrying after a failed source, does not touch
  Earth Engine again. The footprint of every threshold is downloaded in one request, so a cached footprint serves all of them.
* The footprint is never replaced by its bounding box; area, intersections and population still use the exact polygons.

## 4. Caches (ephemeral, bounded)

| Cache | Key (hash of) | Items / TTL | Notes |
|---|---|---|---|
| Footprint (`exposure._footprint_cache`) | analysis identity (AOI ring or department+municipality, dates, model version, hectares) + tile size | 3 / 30 min | superset logic: a request for more thresholds re-downloads and extends the entry |
| Exposure result (`Memo`) | analysis identity + threshold + buffer + population/sensitivity flags + WorldPop version/year/resolution + Overpass endpoints/cell size + layer limits | 3 / 30 min | **only `success` results** are cached; a partial result is never cached |
| Overpass cells (`osm._cache`) | rounded cell bounds | 32 cells / 6 h | existing; finished cells survive a failed attempt |
| WorldPop (`worldpop._cache`) | geometry hash + API version/year/resolution | 32 / 24 h | existing |
| Progress | random client id | 64 / 1 h | stage names and numbers only |

* Cached values contain only public data; nothing user-specific, so sharing across users cannot leak anything, and a
  different AOI, date, threshold, buffer or source setting always produces a different key (tested).
* Memory: items × payload. A result is bounded by the layer/vertex limits and is refused by the cache above
  `CACHE_MAX_ITEM_BYTES` (25 MB); worst case ≈ 3 × 25 MB + the footprints, far below the 2 GiB recommended.
* **The caches are ephemeral**: they disappear when the Cloud Run instance restarts or scales to zero, and each instance has its own.
* Identical concurrent requests are computed once (single-flight): the second caller waits and shares the result (exposure) or
  the computation (wildfire analysis; its result is *not* cached because it carries Earth Engine tile links that expire).
* A cached answer is labelled in the UI and in `analysis.processing.served_from_cache`; `generated_at` stays the original time.

## 5. OpenStreetMap and WorldPop

* OSM queries are restricted to the cells touching the (buffered, simplified) footprint region of the thresholds the request
  needs; only buildings, highways of the listed classes, health and education features are requested; the element cap
  (`OVERPASS_MAX_ELEMENTS`) and the cell cap (`OVERPASS_MAX_CELLS`) are enforced before more requests are made.
* One Overpass request at a time (`OVERPASS_MAX_CONCURRENT=1`), 1 s between cells, 429 → bounded wait on the same server, then
  each mirror once. OSM and WorldPop run concurrently with each other (2 threads); nothing else was parallelised.
* One WorldPop task per distinct footprint geometry (cached 24 h); polling is bounded (`WORLDPOP_MAX_WAIT_S`).
* A failing source never hides a successful one: the response is `partial` and the missing source is shown as unavailable, not zero.
* Optional saving, not enabled by default (it changes what the response contains): `include_sensitivity=false` makes OSM cover only the
  selected footprint and downloads one mask instead of five.

## 6. Recommended Cloud Run settings (first public phase)

```
--min-instances 0 --max-instances 1 --concurrency 8 --cpu 1 --memory 2Gi --timeout 1200
request-based billing (the default; do NOT use --no-cpu-throttling)
```

| Setting | Suggested start | Why |
|---|---|---|
| min instances | 0 | no idle cost |
| max instances | 1 | bounds parallel compute and Earth Engine load; raise only with evidence (caches, rate limits and gates are per instance) |
| concurrency | 8 | requests share one instance; the gates below limit the heavy ones |
| CPU / memory | 1 vCPU / 2 GiB | not increased: raise memory only if Cloud Run shows OOM kills in real runs (not measured here) |
| `MAX_CUSTOM_AOI_HECTARES` / `WARN_` | 50,000 / 25,000 | wildfire analysis cost grows with area |
| `MAX_EXPOSURE_AOI_HECTARES` | 30,000 | beyond ~40,000 ha the exposure time is unmeasured |
| `EXPOSURE_MAX_PIXELS` | 1,000,000 (≈ 40,000 ha at 20 m) | raster size |
| `EXPOSURE_MAX_HAZARD_VERTICES` | 200,000 (default) | geometry size |
| `OVERPASS_MAX_ELEMENTS` / `OVERPASS_MAX_CELLS` | 40,000 / 16 | OSM objects and requests |
| `EXPOSURE_MAX_CONCURRENT` / `ANALYSIS_MAX_CONCURRENT` | 1 / 2 | simultaneous heavy analyses per instance |
| `RATE_LIMIT_ANALYZE` / `RATE_LIMIT_EXPOSURE` | 5/hour;20/day / 10/hour;40/day (defaults) | per-client limits |
| `TRUST_FORWARDED_FOR` | true on Cloud Run | otherwise every user shares Google's proxy IP and one limit |
| request timeouts | Cloud Run 1200 s; `EXPOSURE_MAX_SECONDS` 1000; Overpass 60 s per request; WorldPop 90 s | bounded waiting |

All limits are enforced by the backend (the UI only reads them from `/config`).

**Why exposure is not a background job.** With request-based billing Cloud Run gives CPU only while a request is being
served, so work continued after the response is throttled and may be killed when the instance is recycled. A "start then poll
for the result" design would need persistent coordination (Cloud Tasks, a queue or a database), which is excluded. The analysis
therefore stays one request; the browser polls only the lightweight progress endpoint while it runs.

## 7. Limits of this protection (be explicit)

* **There is no hard spending cap.** `--max-instances` limits parallelism, not monthly cost, and a billing alert only notifies.
  The only immediate stop is the manual kill switch (`ANALYSIS_ENABLED=false` / `EXPOSURE_ENABLED=false`, then redeploy);
  disabling billing automatically needs extra Google services (Pub/Sub + a function) that are out of scope.
* **Rate limits and the daily quota are per instance and in memory.** They reset when the instance restarts or scales to zero and
  are not shared between instances, so they reduce abuse and accidental repeats but are not a reliable *global* daily quota. A
  global per-day quota needs persistent shared state; none was invented here.
* Users behind the same NAT share a limit. CORS is not authentication: it only restricts browsers. The API has no login, so a
  determined caller can reach it directly within the rate limits; add Cloud Armor or an API key only if abuse appears.
* Earth Engine quota (Community tier: 150 EECU-hours/month, reduced performance beyond it) is outside this application.

## 8. Production-safety review

* CORS: explicit allow-list from `CORS_ORIGINS`, no wildcard in code; methods GET/POST/OPTIONS.
* Credentials: the Earth Engine key and the WorldPop key exist only in backend environment/secret files; WorldPop sends its key in a
  header, never in a URL. `httpx`/`httpcore` request logging (which printed Earth Engine and WorldPop task URLs) is now WARNING.
  Application logs contain stage names, counts and durations, not tokens, keys or geometries.
* Abuse: per-IP limits, concurrency gates (`exposure`, `analysis`, `overpass`), size limits, signed `analysis_ref` (no client polygon
  accepted in the default mode), progress ids validated by regex and bounded in number.
* Duplicate clicks: ignored in the UI (in-flight guard) and, if they reach the server, identical requests share one computation.

## 9. Acceptance checklist

* Backend: 237 tests (new: `test_performance.py`, equality guard in `test_exposure_metrics.py`); frontend: 85 tests, `tsc` clean.
* Geospatial equality of the optimisation: see the benchmark table (identical area, counts, lengths, sensitivity rows) and
  `test_shared_proximity_zone_and_skipped_buffer_do_not_change_the_numbers`.
* To benchmark the **same real event** before/after: run the analysis and "Analyze Exposure" once; copy the `exposure_timing`
  log line; click again with the same parameters (served from cache) and with another threshold (footprint reused, Earth
  Engine not called); compare with the table in section 1. Count of Earth Engine evaluations per exposure run: one
  `getDownloadURL` per tile (+1 extent read for a municipality) on the first run, 0 on a footprint cache hit; Overpass requests:
  one per cell (0 when the cells are cached); WorldPop: one task + polling (0 when cached).
