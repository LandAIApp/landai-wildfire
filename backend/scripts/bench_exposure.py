"""Local, offline benchmark of the CPU-bound part of the Exposure module (no Earth Engine / Overpass / WorldPop).

It builds a synthetic but realistic input (fragmented 20 m raster footprints for the five thresholds, a few hundred
OSM-like features) and times ``exposure.build_response`` with the external sources replaced by instant fakes.
It measures ONLY the local spatial work; network time is not simulated.

    cd backend && python scripts/bench_exposure.py [--hectares 20000] [--runs 2]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
from rasterio.transform import from_origin  # noqa: E402
from scipy.ndimage import gaussian_filter  # noqa: E402
from shapely.geometry import LineString, Point, Polygon, box  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.schemas.exposure import ExposureRequest  # noqa: E402
from app.services import exposure, footprint, spatial, worldpop  # noqa: E402
from app.services.osm import OsmData, OsmFeature  # noqa: E402

SHARE = {'burn035': 0.45, 'burn050': 0.32, 'burn060': 0.26, 'burn072': 0.21, 'burn085': 0.16}


def synthetic(hectares: float, seed: int = 7):
    side_px = int((hectares * 10_000) ** 0.5 / 20)
    rng = np.random.default_rng(seed)
    field = gaussian_filter(rng.random((side_px, side_px)), 3)
    transform = from_origin(484_100, 462_860, 20, 20)
    footprints = {}
    for key, share in SHARE.items():
        mask = (field >= np.quantile(field, 1 - share)).astype('uint8')
        footprints[key] = footprint.vectorize(mask, transform)
    crs = 'EPSG:32618'
    aoi = box(484_100, 462_860 - side_px * 20, 484_100 + side_px * 20, 462_860)
    fp = footprint.Footprint(crs=crs, pixel_size_m=20, aoi=aoi, footprints=footprints,
                             pixel_counts={k: int(g.area / 400) for k, g in footprints.items()})
    osm = OsmData(retrieved_at='2026-10-01T00:00:00+00:00', endpoint='bench', element_count=650)
    for i in range(200):
        x, y = rng.uniform(aoi.bounds[0], aoi.bounds[2]), rng.uniform(aoi.bounds[1], aoi.bounds[3])
        osm.buildings.append(OsmFeature(('way', i), spatial.to_wgs84(box(x, y, x + 8, y + 8), crs),
                                        {'building': 'house'}))
    for i in range(450):
        x, y = rng.uniform(aoi.bounds[0], aoi.bounds[2]), rng.uniform(aoi.bounds[1], aoi.bounds[3])
        line = LineString([(x, y), (x + rng.uniform(-600, 600), y + rng.uniform(-600, 600)), (x + 900, y + 300)])
        osm.roads.append(OsmFeature(('way', 1000 + i), spatial.to_wgs84(line, crs), {'highway': 'tertiary'}))
    osm.health = [OsmFeature(('way', 5000), spatial.to_wgs84(box(487_000, 459_000, 487_040, 459_040), crs),
                             {'amenity': 'hospital', 'name': 'H'})]
    return fp, osm, aoi


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--hectares', type=float, default=19_700)
    parser.add_argument('--runs', type=int, default=2)
    args = parser.parse_args()
    fp, osm, aoi = synthetic(args.hectares)
    parts = {k: len(getattr(g, 'geoms', [g])) for k, g in fp.footprints.items()}
    print('footprint parts per threshold:', parts, '| 0.85 area ha:', round(fp.footprints['burn085'].area / 1e4))
    settings = Settings(_env_file=None)
    ctx = {'mode': 'wildfire_analysis', 'kind': 'drawn', 'aoi_hectares': args.hectares, 'fire_date': '2026-08-05',
           'analysis_end': '2026-09-01', 'model_version': 'bench', 'analysis_area_ha': None, 'date_windows': None,
           'department': None, 'municipality': None, 'ring': [list(p) for p in spatial.to_wgs84(aoi, fp.crs).exterior.coords]}
    pop = worldpop.PopulationResult(
        estimate=1.0, year=2020, resolution='100m', dataset='bench', api_version='v2', task_id='t',
        analysis_area_ha=1.0, simplification={'applied': False, 'vertices_before': 0, 'vertices_after': 0,
                                              'tolerance_m': 0, 'area_change_pct': 0})
    for run in range(args.runs):
        started = time.perf_counter()
        out = exposure.build_response(
            ExposureRequest(analysis_ref='x' * 30, threshold=0.85), ctx, fp, settings,
            osm_fetch=lambda b, s, **kw: osm, pop_estimate=lambda *a, **k: pop)
        elapsed = time.perf_counter() - started
        m = out['metrics']
        print(f'run {run + 1}: build_response {elapsed:6.1f} s | area {m["affected_area_ha"]} ha | '
              f'buildings {m["buildings_intersecting"]["value"]}/{m["buildings_within_buffer"]["value"]} | '
              f'roads {m["roads_km_intersecting"]["value"]}/{m["roads_km_within_buffer"]["value"]} km | '
              f'sens {[r["buildings_intersecting"] for r in out["sensitivity"]]} '
              f'{[r["roads_km_intersecting"] for r in out["sensitivity"]]}')


if __name__ == '__main__':
    main()
