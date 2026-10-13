"""REAL-SERVICE smoke test for the Exposure module (separate from the mocked unit tests).

Run it from the repository root on a machine with internet access (it calls the public Overpass API and the
WorldPop API using the SAME clients the backend uses):

    python backend/scripts/smoke_test_exposure.py                     # default: small area near Ibagué
    python backend/scripts/smoke_test_exposure.py --lon -75.23 --lat 4.44 --size-m 1500
    python backend/scripts/smoke_test_exposure.py --worldpop-version v1

It prints the RAW WorldPop responses so the API contract can be verified. Exit code is non-zero if a source fails.
Earth Engine is not needed. Be gentle with the public services: run it once, not in a loop.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))

import httpx  # noqa: E402
from shapely.geometry import box  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.services import exposure_metrics, osm, spatial, worldpop  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--lon', type=float, default=-75.2322)
    ap.add_argument('--lat', type=float, default=4.4389)
    ap.add_argument('--size-m', type=float, default=1000, help='side of the square test footprint')
    ap.add_argument('--worldpop-version', choices=['v1', 'v2'], default=None)
    a = ap.parse_args()
    overrides = {'worldpop_api_version': a.worldpop_version} if a.worldpop_version else {}
    settings = Settings(**overrides)

    crs = spatial.utm_epsg(a.lon, a.lat)
    center = spatial.to_metric(box(a.lon, a.lat, a.lon, a.lat).centroid, crs)
    half = a.size_m / 2
    hazard = box(center.x - half, center.y - half, center.x + half, center.y + half)
    wgs = spatial.to_wgs84(hazard, crs)
    failures = 0

    print(f'== Overpass: {settings.overpass_endpoint}')
    try:
        data = osm.fetch(wgs.bounds, settings)
        metrics = exposure_metrics.compute(data, hazard, crs, buffer_m=settings.exposure_default_buffer_m)
        print('  elements:', data.element_count, '| buildings', len(data.buildings), '| roads', len(data.roads),
              '| health', len(data.health), '| education', len(data.education))
        print('  metrics :', json.dumps({k: v['value'] for k, v in metrics.metrics.items()}))
    except Exception as exc:  # noqa: BLE001
        failures += 1
        print('  FAILED:', getattr(exc, 'code', type(exc).__name__), getattr(exc, 'message', exc))

    print(f'== WorldPop {settings.worldpop_api_version}: {settings.worldpop_base_url}')
    try:
        # Show the raw first response: this is how the contract is verified.
        body = {'geojson': {'type': 'Feature', 'properties': {}, 'geometry': json.loads(
            json.dumps(spatial.feature(wgs)['geometry']))}, 'year': settings.worldpop_year,
            'resolution': settings.worldpop_resolution}
        path = '/v2/population' if settings.worldpop_api_version == 'v2' else '/v1/services/stats'
        if settings.worldpop_api_version == 'v2':
            raw = httpx.post(settings.worldpop_base_url.rstrip('/') + path, json=body, timeout=30)
            print('  raw POST', raw.status_code, raw.text[:500])
        result = worldpop.estimate(hazard, crs, settings)
        print('  estimate:', result.estimate, 'people | year', result.year, '| resolution', result.resolution,
              '| task', result.task_id, '| api', result.api_version)
    except Exception as exc:  # noqa: BLE001
        failures += 1
        print('  FAILED:', getattr(exc, 'code', type(exc).__name__), getattr(exc, 'message', exc))
        print('  -> If the code is worldpop_bad_response/http_error, compare the raw response above with the')
        print('     WorldPop API documentation and adjust backend/app/services/worldpop.py (one function).')
    print('RESULT:', 'OK' if not failures else f'{failures} source(s) failed')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
