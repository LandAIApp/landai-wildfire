# Upgrade v1 → v2: Custom AOI + Exposure & Impact

## 1. Technical audit of v1 (concise)
- Solid base: FastAPI + EE, structured errors, preflight, 114 tests. V7.6 pipeline left untouched.
- Findings: (a) `backend/app/services/analysis.py` HEAD contained a stray `from backend.tests.conftest import req` import
  (pre-existing defect; removed). (b) README referenced a root `.env.example` that did not exist (added). (c) Only municipality AOIs;
  limits hard-coded in the UI. (d) Rate limiting existed but limits were not env-configurable.

## 2. Existing architecture (summary)
React/Vite on GitHub Pages → FastAPI on Cloud Run → Google Earth Engine (V7.6, tile URLs). No database, no accounts. See `docs/architecture.md` (diagram).

## 3. Changes introduced
1. **Mode B drawn polygon**: Leaflet draw/edit/delete, ha + km², limits from `GET /api/v1/config`, backend + browser validation, conflicting modes rejected, nothing silently truncated. Mode A unchanged.
2. **Exposure & Impact** (`POST /api/v1/exposure/analyze`), explicit button only: real affected footprint (raster-first), OSM via Overpass, WorldPop async, per-source partial status, sensitivity, buffer, exports (GeoJSON/CSV/JSON), ES/EN dashboard tab with the verbatim notice.
3. Signed stateless `analysis_ref`; env-configurable rate limits, concurrency gates, TTL caches; no wildcard CORS; no DB.
4. V7.6 is **unchanged**; it is AOI-dependent, so drawn polygons are not numerically equivalent to municipalities (`docs/exposure-methodology.md`).

## 4. Files — modified (26)
- `README.md`
- `backend/app/api/wildfire.py`
- `backend/app/core/config.py`
- `backend/app/core/errors.py`
- `backend/app/core/rate_limit.py`
- `backend/app/main.py`
- `backend/app/schemas/wildfire.py`
- `backend/app/services/analysis.py`
- `backend/app/services/preflight.py`
- `backend/requirements.txt`
- `docs/deployment.md`
- `frontend/package-lock.json`
- `frontend/package.json`
- `frontend/src/components/ControlPanel.tsx`
- `frontend/src/components/LayerPanel.tsx`
- `frontend/src/components/MapView.tsx`
- `frontend/src/components/ResultsPanel.tsx`
- `frontend/src/components/components.test.tsx`
- `frontend/src/i18n/translations.ts`
- `frontend/src/pages/HomePage.tsx`
- `frontend/src/services/api.ts`
- `frontend/src/services/format.ts`
- `frontend/src/services/issues.ts`
- `frontend/src/styles.css`
- `frontend/src/types/api.ts`
- `frontend/vite.config.ts`

## 5. Files — new (45)
- `.env.example`
- `backend/app/api/config.py`
- `backend/app/api/exposure.py`
- `backend/app/core/cache.py`
- `backend/app/core/gate.py`
- `backend/app/core/geometry.py`
- `backend/app/schemas/config.py`
- `backend/app/schemas/exposure.py`
- `backend/app/services/analysis_ref.py`
- `backend/app/services/aoi.py`
- `backend/app/services/exposure.py`
- `backend/app/services/exposure_export.py`
- `backend/app/services/exposure_metrics.py`
- `backend/app/services/footprint.py`
- `backend/app/services/osm.py`
- `backend/app/services/spatial.py`
- `backend/app/services/worldpop.py`
- `backend/scripts/record_demo.py`
- `backend/scripts/smoke_test_exposure.py`
- `backend/tests/test_analysis_ref.py`
- `backend/tests/test_custom_aoi.py`
- `backend/tests/test_exposure_metrics.py`
- `backend/tests/test_exposure_service.py`
- `backend/tests/test_footprint.py`
- `backend/tests/test_osm_service.py`
- `backend/tests/test_worldpop_service.py`
- `docs/UPGRADE_v2.md`
- `docs/api.md`
- `docs/architecture.md`
- `docs/conference-checklist.md`
- `docs/exposure-methodology.md`
- `docs/img/architecture.png`
- `docs/img/architecture.svg`
- `frontend/src/components/AreaPanel.tsx`
- `frontend/src/components/DrawBar.tsx`
- `frontend/src/components/ExposureAction.tsx`
- `frontend/src/components/ExposurePanel.tsx`
- `frontend/src/i18n/translations.v2.ts`
- `frontend/src/pages/HomePage.test.tsx`
- `frontend/src/services/config.ts`
- `frontend/src/services/exposure.test.ts`
- `frontend/src/services/exposure.ts`
- `frontend/src/services/geometry.test.ts`
- `frontend/src/services/geometry.ts`
- `frontend/src/test/fixtures.ts`

## 6. Endpoints / env vars
See `docs/api.md` and `.env.example`.

## 7. Tests executed (this workspace)
- Backend: `pytest` → **197 passed** (114 original + 83 new; all external HTTP mocked via httpx MockTransport; EE mocked / synthetic GeoTIFF).
- Frontend: `npm test` → **80 passed**; `npm run typecheck` clean; `npm run build` OK.
- Playwright screenshots with a mocked API for visual QA.
- **Not executed here**: live Overpass/WorldPop/Earth Engine (sandbox network allow-list). The real smoke test `backend/scripts/smoke_test_exposure.py` is provided; integration with live services is therefore **unverified**.

## 8. Remaining limitations
- WorldPop v2 contract unverified (documented public API is v1; set `WORLDPOP_API_VERSION=v1` if v2 fails).
- `getDownloadURL` behaviour against real EE only tested with mocks.
- Rate limits/caches are per instance and reset on scale-to-zero; `ANALYSIS_REF_SECRET` must be set for refs to survive restarts.
- Municipality area is known only after preflight (no preview endpoint). Overpass public instance is shared and may throttle.
- Recorded demo cannot be produced here (needs real services): none is shipped.
- Exposure ≠ damage; OSM incomplete; WorldPop modelled.

## 9. Test it locally when you already have v1 (Windows / PowerShell)
```powershell
# 0) Backup your v1 config and keys (never commit them)
copy backend\.env $env:TEMP\v1.env.bak          # or the .env at the repo root
# 1) Put v2 in a NEW folder next to v1 (safest), or apply the patch on a branch of v1:
#    Option A: unzip landai-wildfire-v2.zip to C:\dev\landai-wildfire-v2 and copy your .env into it
#    Option B: cd <your v1 repo>; git switch -c feature/custom-aoi-exposure; git apply --3way landai-wildfire-v2.patch
copy $env:TEMP\v1.env.bak C:\dev\landai-wildfire-v2\.env
# 2) Backend (conda env landai active; new deps: shapely, pyproj, rasterio, numpy, httpx)
cd C:\dev\landai-wildfire-v2
pip install -r backend\requirements-dev.txt
pytest                                   # expect 197 passed
cd backend ; uvicorn app.main:app --reload     # terminal 1  (http://localhost:8000/api/v1/config)
# 3) Frontend (terminal 2)
cd C:\dev\landai-wildfire-v2\frontend ; npm install ; npm run dev     # http://localhost:5173
# 4) Real smoke test of OSM + WorldPop (needs internet; run once)
cd C:\dev\landai-wildfire-v2 ; python backend\scripts\smoke_test_exposure.py
```
Manual checks in the browser: (1) Mode A municipality gives the same flow as v1; (2) Mode B → draw a polygon, see ha/km², try one
over the limit and one self-intersecting; (3) run an analysis, then press **Analyze Exposure**; (4) switch ES/EN, check the notice;
(5) download GeoJSON/CSV/JSON. Optional demo: `python backend\scripts\record_demo.py --department X --municipality Y --fire-date ... --end-date ...`.
If `earthengine authenticate` was already done in v1, keep `EE_PROJECT` in `.env` and leave key paths empty.

## 10. Deploy
See `docs/deployment.md` §3, §4 and §6 (GitHub Pages + Cloud Run). **Nothing was deployed.**
