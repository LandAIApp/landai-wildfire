# Deployment guide

## Architecture (what runs where)

| Part | Where | Why |
|---|---|---|
| Frontend (React, static files) | **GitHub Pages** (or Vercel / Netlify / Cloudflare Pages) | Static hosting is enough |
| Backend (FastAPI + Earth Engine) | **Google Cloud Run** | It is a Python server; **GitHub Pages cannot run it** |
| Processing | Google Earth Engine | Server-side, billed against your EE project quota |

The browser talks directly to the backend URL, so the backend must allow the frontend origin via
`CORS_ORIGINS` (origin only, no path: `https://landaiapp.github.io`).

## 1. Local run (Windows / PowerShell)
See the root README. Short version:

```powershell
conda activate landai
pip install -r backend\requirements-dev.txt
pytest
cd backend ; uvicorn app.main:app --reload        # terminal 1
cd frontend ; npm install ; npm run dev            # terminal 2  -> http://localhost:5173
```

## 2. Publish the code on GitHub
```powershell
git status                       # .env and credentials\*.json must NOT appear
git add -A
git commit -m "Frontend productization: ES/EN, Land AI design system, layer groups"
git push origin main
```
If `git status` lists `.env` or any key file, stop and fix `.gitignore` first.

## 3. Deploy the backend to Cloud Run

Prerequisites: `gcloud` CLI installed and logged in, billing enabled on the project.

```powershell
$PROJECT = "ee-maikolzaraza07"        # Cloud project that is registered for Earth Engine
$REGION  = "us-central1"

gcloud config set project $PROJECT
gcloud services enable run.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com artifactregistry.googleapis.com earthengine.googleapis.com

# 3a. Service account for the backend (needs Earth Engine access)
gcloud iam service-accounts create landai-backend
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:landai-backend@$PROJECT.iam.gserviceaccount.com" --role="roles/earthengine.viewer"
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:landai-backend@$PROJECT.iam.gserviceaccount.com" --role="roles/serviceusage.serviceUsageConsumer"
#   Also share the asset users/maikolzaraza07/mpios (Reader) with landai-backend@<project>.iam.gserviceaccount.com

# 3b. Create a NEW key (never reuse the one that was exposed) and store it as a secret
gcloud iam service-accounts keys create ee-key.json --iam-account="landai-backend@$PROJECT.iam.gserviceaccount.com"
gcloud secrets create landai-ee-key --data-file=ee-key.json
Remove-Item ee-key.json            # do not keep the key on disk or in the repo
gcloud secrets add-iam-policy-binding landai-ee-key --member="serviceAccount:landai-backend@$PROJECT.iam.gserviceaccount.com" --role="roles/secretmanager.secretAccessor"

# 3c. Build and deploy
gcloud run deploy landai-wildfire-api `
  --source backend `
  --region $REGION `
  --port 8000 `
  --service-account "landai-backend@$PROJECT.iam.gserviceaccount.com" `
  --allow-unauthenticated `
  --timeout 1200 --memory 2Gi --cpu 1 `
  --max-instances 3 `
  --set-secrets "/secrets/ee-key.json=landai-ee-key:latest" `
  --set-env-vars "EE_PROJECT=$PROJECT,EE_PRIVATE_KEY_PATH=/secrets/ee-key.json,CORS_ORIGINS=https://landaiapp.github.io,TRUST_FORWARDED_FOR=true,ANALYSIS_REF_SECRET=<long random>,WORLDPOP_YEAR=2020"
```
The command prints the service URL (`https://landai-wildfire-api-xxxx.a.run.app`). Check
`<URL>/health?check_ee=true` and `<URL>/api/v1/administrative/departments`.

Notes
- `--timeout 1200` matters: an analysis is one long request (several minutes); `--memory 2Gi` is needed in v2 for the
  raster download and vectorisation of the Exposure module (`EXPOSURE_MAX_PIXELS` bounds it).
- `--max-instances 3` caps cost and concurrent Earth Engine load.
- Add every frontend origin to `CORS_ORIGINS`, comma-separated (e.g. a custom domain too).
  Update later with `gcloud run services update landai-wildfire-api --update-env-vars CORS_ORIGINS=...`.
  Use `^@^` as delimiter if a value contains commas (see `gcloud topic escaping`).

## 4. Deploy the frontend to GitHub Pages
1. Repository **Settings → Pages → Source: GitHub Actions**.
2. **Settings → Secrets and variables → Actions → Variables** → add
   - `VITE_API_BASE_URL` = the Cloud Run URL (no trailing slash)
   - `VITE_LANDAI_CONTACT_URL` = your contact page (optional)
3. Push to `main` (or run the workflow manually: **Actions → Deploy frontend to GitHub Pages**).
4. The site appears at `https://<owner>.github.io/<repo>/`
   (for `LandAIApp/landai-wildfire`: `https://landaiapp.github.io/landai-wildfire/`).

Custom domain (e.g. `wildfire.yourdomain.com`): Settings → Pages → Custom domain, add the DNS `CNAME`,
then delete the `VITE_BASE_PATH` line in `.github/workflows/deploy-frontend.yml` and add
`https://wildfire.yourdomain.com` to the backend `CORS_ORIGINS`.

GitHub Pages on a **private** repository requires a paid GitHub plan; public repositories work on the free plan.

## 5. Before opening it to the public — read this

1. **Earth Engine terms.** Your project is registered as *non-commercial* (its eligibility expires 2027-01-02).
   A public tool that also promotes a commercial service may need a *commercial* registration.
   Check Earth Engine's access/terms page and upgrade the registration if it applies to Land AI.
2. **Cost and abuse.** The API has no authentication and every analysis consumes Earth Engine compute.
   CORS does **not** stop someone from calling the API directly. Keep `--max-instances` low, set a
   Google Cloud budget alert, and plan for rate limiting or an API key before promoting the URL widely.
3. **Scientific status.** Runtime equivalence with the original GEE script is still unvalidated
   (see `docs/equivalence.md`). The UI states results are preliminary and not official perimeters; keep it that way.
4. **Secrets.** Never commit `.env` or key files. The key lives only in Secret Manager.

## 6. v2 additions (Custom AOI + Exposure & Impact)
- **New env vars** (all optional, defaults in `.env.example`): `MAX_CUSTOM_AOI_HECTARES`, `MAX_EXPOSURE_AOI_HECTARES`,
  `RATE_LIMIT_ANALYZE/EXPOSURE`, `ANALYSIS_REF_SECRET`, `OVERPASS_*`, `WORLDPOP_*`, `TRUST_FORWARDED_FOR`.
  Put `ANALYSIS_REF_SECRET` (and `WORLDPOP_API_KEY` if you have one) in Secret Manager (`--set-secrets`), never in the repo or the frontend.
- **`ANALYSIS_REF_SECRET`**: if empty the secret is random per process, so a reference issued before a restart/scale-to-zero is rejected
  (`invalid_analysis_ref`) and the user must re-run the analysis. Set it to avoid that.
- **Rate limits and caches are in memory per instance**: with `--max-instances 3` the effective limit is up to 3x, and counters/caches
  reset when an instance scales to zero. Keep `--max-instances` low; add a Cloud Armor / API key only if abuse appears (no paid service is required).
- **Overpass** is a shared public instance: keep the descriptive `OVERPASS_USER_AGENT` (add a contact), do not loop calls.
  For heavy use switch `OVERPASS_ENDPOINT` to your own instance.
- **Demo mode**: record a REAL result with `python backend/scripts/record_demo.py` and place the output at
  `frontend/public/demo/exposure-demo.json`; the UI labels it "recorded". Nothing ships by default.
- Cost target (~USD 5/month): scale-to-zero, `--max-instances 3`, no database, no paid APIs; set a budget alert.
- Frontend deploy is unchanged (GitHub Pages workflow). **Do not deploy from the feature branch before the checklist in `docs/conference-checklist.md`.**

## 7. Cost estimate (Cloud Run, request-based billing)

Prices checked on 2026-10-13 (Tier 1 regions): USD 0.000024 per vCPU-second, 0.00000025 per GiB-second, 0.40 per million requests; free tier per month: 180,000 vCPU-s, 360,000 GiB-s, 2 M requests, 1 GiB egress. Configuration assumed: 1 vCPU, 2 GiB, `--max-instances 3`.

| Study area | Expected duration of one full run (analysis + exposure) | Compute cost per run |
|---|---|---|
| ~20,000 ha (measured: 7.7 min before the speed-ups in this version) | 6–8 min | ≈ USD 0.01–0.015 |
| 50,000–80,000 ha (extrapolated, **not measured**) | 12–20 min | ≈ USD 0.02–0.04 |

* ~1,000 full runs/month at 50–80 k ha ≈ USD 20–40 of compute, minus the free tier (roughly 150–250 runs).
* Per-IP limits (`RATE_LIMIT_ANALYZE`, `RATE_LIMIT_EXPOSURE`) and `--max-instances 3` bound the worst case; set a Google Cloud budget alert (e.g. USD 5 and USD 20).
* Compute is not the main risk. Earth Engine quota (Community tier: 150 EECU-hours/month, reduced performance beyond it), public Overpass fair use and the Cloud Run request timeout (`--timeout 1200`) are. Areas above ~40,000 ha should be treated as unvalidated until measured.
* Overview diagram: `docs/img/architecture-overview.svg` / `.png`.
