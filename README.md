# Land AI Wildfire Intelligence

Web MVP that runs the **FIRE FOREST COLOMBIA V7.6** wildfire analysis (Sentinel-2 + VIIRS +
pseudo-supervised Random Forest + agricultural filter) through the **Earth Engine Python API**,
exposes it with **FastAPI**, and visualizes it in a **React + Leaflet** app.

> **Scientific source of truth:** [`wildfire_gee_reference.js`](wildfire_gee_reference.js).
> The algorithm has been ported without changing formulas, thresholds, windows, weights,
> Random Forest configuration, agricultural logic, VIIRS logic or connectivity filtering.
> Runtime equivalence with the JavaScript script is **not yet demonstrated**; see
> [docs/equivalence.md](docs/equivalence.md).

> **Disclaimer.** Automated preliminary Earth Observation estimate. This result is not an
> officially validated wildfire perimeter.

## Requirements

| Tool | Version |
|---|---|
| Python | 3.11+ |
| Node.js | 18+ (22 recommended) |
| Google Earth Engine | Cloud project registered for Earth Engine, and read access to `users/maikolzaraza07/mpios` |
| Docker (optional) | Docker Desktop / Engine with Compose v2 |

## 1. Earth Engine authentication

The backend needs Earth Engine credentials. Choose **one**:

**A. Local login (easiest for development)**
```bash
pip install earthengine-api
earthengine authenticate
```
Then set `EE_PROJECT=<your-cloud-project>` in `.env`.

**B. Service account (needed for Docker/servers)**
1. Create a service account, register it for Earth Engine, and download a JSON key.
2. **Share the private asset `users/maikolzaraza07/mpios` with the service account** (reader).
3. Put the key in `credentials/` (git-ignored) and set in `.env`:
   ```
   EE_PROJECT=your-project-id
   EE_PRIVATE_KEY_PATH=credentials/your-key.json
   ```
   `EE_SERVICE_ACCOUNT` is optional (read from the key file).

> Never commit `.env` or anything in `credentials/`. Both are in `.gitignore`.

## 2. Backend

```bash
cp .env.example .env           # then edit EE_PROJECT / credentials
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r backend/requirements-dev.txt

cd backend
uvicorn app.main:app --reload
```
API docs: <http://localhost:8000/docs> · Health: <http://localhost:8000/health?check_ee=true>

Tests (no Earth Engine access needed) from the repo root:
```bash
pytest
```

Smoke test against the running backend with real Earth Engine:
```bash
python backend/scripts/smoke_test.py
```

## 3. Frontend

```bash
cd frontend
npm install
npm run dev
```
Open <http://localhost:5173>.

Optional `frontend/.env` (see `frontend/.env.example`):

| Variable | Purpose |
|---|---|
| `VITE_API_BASE_URL` | Backend URL as seen from the browser (default `http://localhost:8000`) |
| `VITE_LANDAI_CONTACT_URL` | Destination of the "Habla con Land AI / Talk to Land AI" link shown after a result (hidden if empty) |
| `VITE_BASE_PATH` | Only for GitHub Pages project sites, e.g. `/landai-wildfire/` |

Features: Spanish (default) / English switch persisted in `localStorage` (`landai.lang`), Land AI design
system (Poppins, dark teal, turquoise accent), "Cargar ejemplo / Try example" button (fills the form with
Tolima · San Luis · 2026-08-05 → 2026-08-15 without running anything), main/advanced layer groups.
Translations live in `frontend/src/i18n/translations.ts` (one dictionary per language, type-checked for
parity). Logos are in `frontend/public/assets/brand/`.

Workflow: select department → municipality → dates → **Verificar datos / Check Data** →
**Analizar incendio / Analyze Wildfire**. An analysis can take **several minutes**.

Frontend checks: `npm test`, `npm run typecheck`, `npm run build`.

## 4. Docker

```bash
cp .env.example .env           # fill EE_PROJECT, EE_PRIVATE_KEY_PATH=credentials/<key>.json
docker compose up --build
```
Frontend <http://localhost:5173> · Backend <http://localhost:8000/docs>.
Optional: export `VITE_LANDAI_CONTACT_URL` before `docker compose up --build` to enable the contact link.
Docker needs the **service-account** option (the local `earthengine authenticate` login is not
available inside the container).

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness (`?check_ee=true` also verifies Earth Engine) |
| GET | `/api/v1/administrative/departments` | List departments |
| GET | `/api/v1/administrative/municipalities?department=` | Municipalities of a department |
| POST | `/api/v1/wildfire/preflight` | Scene counts, date windows, blocking errors, warnings (does **not** train the RF) |
| POST | `/api/v1/wildfire/analyze` | Full analysis: area per threshold, training counts, EE tile URLs, boundary |

Request body for `preflight` / `analyze`:
```json
{"department": "Tolima", "municipality": "San Luis",
 "fire_date": "2026-08-05", "analysis_end": "2026-08-15"}
```
`analyze` returns `status`, `metadata`, `image_counts`, `date_windows`, `training`
(actual positive/negative sample counts), `area_statistics` (`wf035…wf085`, hectares),
`area_hectares`, `layers` (Earth Engine `tile_url`s), `boundary`, `bounds`, `warnings`.

Errors always use `{"status":"error","code":"…","message":"…","details":…}`:
`invalid_request` (422), `department_not_found`/`municipality_not_found` (404),
`preflight_failed` (422), `no_training_samples` (422), `earth_engine_not_available` (503),
`earth_engine_error` (502), `earth_engine_timeout` (504), `earth_engine_computation_limit` (422),
`earth_engine_quota` (429), `tile_generation_failed` (502).

Map pixels are served directly by Earth Engine tiles; FastAPI only returns tile URL templates.

## Project structure

```
backend/
  app/
    main.py                FastAPI app, error handlers, CORS
    api/                   health, administrative, wildfire routers
    core/                  settings, errors, Earth Engine init + evaluate()
    schemas/               Pydantic models
    services/              administrative, preflight, analysis, tiles
    wildfire/              V7.6 scientific engine (server-side EE only)
      windows.py  sentinel2.py  spectral_indices.py  historical_variability.py
      agricultural_context.py  viirs.py  evidence.py  seeds.py  training.py
      probability.py  postprocessing.py  model.py (run_burn_model)
  tests/                   pytest (EE mocked / offline graph tests)
  scripts/smoke_test.py    end-to-end check against a running backend
frontend/src/              components, pages, services, types, i18n (no science in the UI)
docs/                      module notes, equivalence plan, deployment guide
.github/workflows/         CI (tests) + GitHub Pages deploy for the frontend
wildfire_gee_reference.js  V7.6 reference (unchanged)
docker-compose.yml
```

## Deployment

See [docs/deployment.md](docs/deployment.md): frontend on GitHub Pages, backend on Google Cloud Run.
GitHub Pages alone cannot host the backend (it needs Python + Earth Engine).

## Limitations

- **Equivalence not yet demonstrated at runtime.** The graph is structurally verified offline and
  the numeric parameters are unit-tested, but nobody has compared Python vs JS outputs on real data.
  Follow [docs/equivalence.md](docs/equivalence.md) before relying on results.
- The Random Forest is retrained on every run; its sample counts are approximate and can differ
  from the JS run. RF output is therefore compared **statistically**, not bit-for-bit.
- `WildfireLikelihood` is a relative score, not a calibrated probability.
- Map tiles apply the small-patch filter at display resolution; the **reported hectares
  (`reduceRegion`, 20 m) are canonical**, tiles are illustrative.
- Analysis is synchronous (one HTTP request, up to ~15 min in the UI). Large municipalities may hit
  Earth Engine limits (reported as `earth_engine_computation_limit`).
- Application-layer guards that do **not** exist in V7.6: max municipality area
  (`MAX_AOI_HECTARES`, default 500,000 ha), minimum fire date (2018-08-01), future-date rejection.
- Known V7.6 behavior preserved: Sentinel-2 scenes without a matching Cloud Score+ image lack
  `cs_cdf` and can make the mask step fail; `ADM2_PCODE` is unused; VIIRS `confidence >= 1` counts any
  non-zero confidence; the municipality is selected by (department, municipality) name and all
  matches are merged.
- No authentication, persistence, exports, or PostGIS (out of MVP scope).
- Not validated against the independent 278-polygon dataset; it must **not** be used for training.

## Scientific disclaimer

Automated preliminary Earth Observation estimate. This result is not an officially validated
wildfire perimeter.
