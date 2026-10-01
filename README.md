# Land AI Wildfire Intelligence

Initial project structure for a future Python 3.11 / FastAPI application backed by
the Earth Engine Python API. The [spectral-index module](docs/spectral-indices.md) and [historical-variability module](docs/historical-variability.md) are implemented.
There is no runnable backend, burn classification, React frontend, database,
or authentication system.

## Reference

The authoritative FIRE FOREST COLOMBIA V7.6 implementation is currently located at
[wildfire_gee_reference.js](wildfire_gee_reference.js). The requested location
`reference/wildfire_gee_reference.js` does not exist in this checkout. The existing
file is preserved in place, without editing, moving, or duplicating it.

See [documentation](docs/README.md) for the structure and reference provenance.
The original [reference notes](README_reference.md) are preserved.

## Development environment

Use Python 3.11. From the repository root on Windows:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

These are setup instructions only; dependencies have not been installed by this
scaffolding step. Requirements list only the ten requested direct dependencies,
without optional extras or version pins. A resolved, tested lock is deferred.
Offline spectral-index and historical-variability tests are available under backend/tests. No application entry point exists yet.
