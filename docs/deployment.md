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
  --timeout 900 --memory 1Gi --cpu 1 `
  --max-instances 3 `
  --set-secrets "/secrets/ee-key.json=landai-ee-key:latest" `
  --set-env-vars "EE_PROJECT=$PROJECT,EE_PRIVATE_KEY_PATH=/secrets/ee-key.json,CORS_ORIGINS=https://landaiapp.github.io"
```
The command prints the service URL (`https://landai-wildfire-api-xxxx.a.run.app`). Check
`<URL>/health?check_ee=true` and `<URL>/api/v1/administrative/departments`.

Notes
- `--timeout 900` matters: an analysis is one long request (several minutes).
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
