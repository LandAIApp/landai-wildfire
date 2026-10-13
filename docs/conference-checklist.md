# Conference verification checklist (GeoMundus 2026)
Before the demo, on the real stack, tick each item:
- [ ] Old key `ee-maikolzaraza07-e53c21fa44a5.json` revoked in IAM; new key only in Secret Manager.
- [ ] `git status` shows no `.env`/credentials; `.env.example` has no secrets.
- [ ] `pytest` and `npm test && npm run typecheck && npm run build` green on the branch.
- [ ] `python backend/scripts/smoke_test_exposure.py` OK against real Overpass **and** WorldPop; note which WorldPop API version answered (v2 contract is unverified).
- [ ] Cloud Run deployed with `--timeout 1200 --memory 2Gi --max-instances 3`, `CORS_ORIGINS` = Pages origin only, `ANALYSIS_REF_SECRET` set; budget alert active.
- [ ] Mode A municipality run reproduces v1 behaviour; Mode B draw/edit/delete, ha + km² shown, over-limit polygon blocked, bow-tie polygon rejected.
- [ ] Exposure button is the only trigger; a failed WorldPop shows "unavailable", not 0; OSM-empty category shows "no OSM data".
- [ ] ES/EN both show the verbatim methodological notice; exports (GeoJSON/CSV/JSON) open correctly.
- [ ] Optional: recorded demo created with `record_demo.py` from a real run and labelled "recorded"; backup screenshots ready.
- [ ] Earth Engine terms (non-commercial vs commercial) reviewed for the public demo.
- [ ] Talk wording: AOI-dependence of V7.6 stated; exposure ≠ damage.
