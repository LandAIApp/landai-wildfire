"""Footprint extraction: synthetic GeoTIFFs (no Earth Engine)."""
import io
import zipfile

import numpy as np
import pytest
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from app.core.config import Settings
from app.core.errors import ExposureAreaTooLargeError, FootprintError
from app.services import footprint

CRS = 'EPSG:32618'
TRANSFORM = from_origin(600000, 501000, 20, 20)       # 20 m pixels, 50 x 50


def tif(arrays):
    data = np.stack(arrays).astype('uint8')
    with MemoryFile() as mem:
        with mem.open(driver='GTiff', height=data.shape[1], width=data.shape[2], count=data.shape[0],
                      dtype='uint8', crs=CRS, transform=TRANSFORM) as dst:
            dst.write(data)
        return mem.read()


def blank():
    return np.zeros((50, 50), dtype='uint8')


def test_vectorize_is_pixel_exact_and_eight_connected():
    a = blank()
    a[10:14, 10:14] = 1           # 16 px = 6400 m2
    a[14, 14] = 1                 # touches diagonally -> same component
    geom = footprint.vectorize(a, TRANSFORM)
    assert geom.area == pytest.approx(17 * 400)
    assert geom.geom_type == 'Polygon'


def test_vectorize_empty_returns_empty():
    assert footprint.vectorize(blank(), TRANSFORM).is_empty


def test_read_single_multiband_tiff():
    a, b = blank(), blank()
    a[0:5, 0:5] = 1
    arrays, transform, crs = footprint.read_download(tif([a, b]), ['Burn072', 'AOI'])
    assert arrays['Burn072'].sum() == 25 and crs == CRS and transform.a == 20


def test_read_zip_with_one_tiff_per_band():
    a = blank(); a[0:2, 0:2] = 1
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('img.Burn072.tif', tif([a]))
        z.writestr('img.AOI.tif', tif([np.ones((50, 50), dtype='uint8')]))
    arrays, _t, crs = footprint.read_download(buf.getvalue(), ['Burn072', 'AOI'])
    assert arrays['Burn072'].sum() == 4 and arrays['AOI'].sum() == 2500


def test_wrong_band_count_is_error():
    with pytest.raises(FootprintError):
        footprint.read_download(tif([blank()]), ['Burn072', 'AOI'])


def test_zip_missing_band_is_error():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('img.AOI.tif', tif([blank()]))
    with pytest.raises(FootprintError):
        footprint.read_download(buf.getvalue(), ['Burn072', 'AOI'])


def test_pixel_limit_rejects_before_download():
    called = []
    s = Settings(_env_file=None, exposure_max_pixels=1000)
    with pytest.raises(ExposureAreaTooLargeError):
        footprint.extract_from_earth_engine({}, None, (-74.1, 4.5, -74.0, 4.6), ['burn072'], s,
                                            downloader=lambda *a: called.append(1))
    assert not called


def test_from_geometries_external_mode():
    from shapely.geometry import box
    fp = footprint.from_geometries(box(-74.005, 4.601, -74.004, 4.602), box(-74.01, 4.6, -74.0, 4.61))
    assert fp.source == 'user_supplied' and fp.crs.startswith('EPSG:326')
    assert fp.footprints['user'].area < fp.aoi.area / 50          # footprint is NOT the AOI


def test_extract_end_to_end_with_mocked_earth_engine(monkeypatch):
    from unittest.mock import MagicMock
    from shapely.geometry import box
    fake_ee = MagicMock()
    monkeypatch.setattr(footprint, 'ee', fake_ee)
    monkeypatch.setattr(footprint, 'ensure_initialized', lambda: None)
    burn, aoi = blank(), np.ones((50, 50), dtype='uint8')
    burn[10:20, 10:20] = 1                                   # 100 px = 4 ha
    content = tif([burn, aoi])
    s = Settings(_env_file=None)
    fp = footprint.extract_from_earth_engine(
        {'burn072': MagicMock()}, MagicMock(), (-74.01, 4.60, -74.00, 4.61), ['burn072'], s,
        downloader=lambda url, settings: content)
    assert fp.footprints['burn072'].area == pytest.approx(4 * 10_000)
    assert fp.aoi.area == pytest.approx(1000 * 1000) and fp.aoi_from_raster
    assert fp.pixel_counts == {'burn072': 100} and fp.grid['requested_scale_m'] == 20
    region = fake_ee.Image.cat.return_value.getDownloadURL.call_args[0][0]
    assert region['scale'] == 20 and region['format'] == 'GEO_TIFF' and region['crs'].startswith('EPSG:326')


# ---- tiled download (Earth Engine 'User memory limit exceeded' on municipality-sized requests) ----------
BOUNDS = (-74.50, 4.60, -74.48, 4.62)          # ~2.2 km square -> ~110 x 110 px


def test_plan_tiles_single_for_small_and_grid_for_large():
    assert footprint.plan_tiles(BOUNDS, CRS, 640).single
    plan = footprint.plan_tiles(BOUNDS, CRS, 40)
    assert not plan.single and len(plan.tiles) == 9 and plan.width > 100 and plan.height > 100
    covered = sum((c1 - c0) * (r1 - r0) for c0, c1, r0, r1 in plan.tiles)
    assert covered == plan.width * plan.height                      # cores partition the canvas exactly
    assert plan.x0 % 20 == 0 and plan.y1 % 20 == 0                  # anchored on the 20 m grid


def _tiled_extract(monkeypatch, aoi_metric=None, shift=0.0):
    from unittest.mock import MagicMock
    plan = footprint.plan_tiles(BOUNDS, CRS, 40)
    rng = np.random.default_rng(1)
    glob = np.zeros((plan.height, plan.width), dtype='uint8')
    glob[30:80, 30:50] = 1                                           # crosses tile borders at 40 and 80
    glob[5:12, 90:104] = 1
    glob = np.where(rng.random(glob.shape) < 0.0, 1, glob).astype('uint8')
    fake_ee = MagicMock()
    monkeypatch.setattr(footprint, 'ee', fake_ee)
    monkeypatch.setattr(footprint, 'ensure_initialized', lambda: None)
    monkeypatch.setattr(footprint, '_tile_region', lambda plan_, tile, crs, scale=20: (
        plan_.x0 + (tile[0] - footprint.TILE_MARGIN_PX) * 20 + shift,
        plan_.y1 - (tile[3] + footprint.TILE_MARGIN_PX) * 20,
        plan_.x0 + (tile[1] + footprint.TILE_MARGIN_PX) * 20,
        plan_.y1 - (tile[2] - footprint.TILE_MARGIN_PX) * 20))
    fake_ee.Image.cat.return_value.getDownloadURL.side_effect = lambda params: params['region']
    calls = []

    def downloader(region, settings):
        calls.append(region)
        xmin, ymin, xmax, ymax = region
        c0, r0 = round((xmin - plan.x0 - shift) / 20), round((plan.y1 - ymax) / 20)
        w, h = round((xmax - xmin) / 20), round((ymax - ymin) / 20)
        win = np.zeros((h, w), dtype='uint8')
        sr0, sr1, sc0, sc1 = max(r0, 0), min(r0 + h, plan.height), max(c0, 0), min(c0 + w, plan.width)
        win[sr0 - r0:sr1 - r0, sc0 - c0:sc1 - c0] = glob[sr0:sr1, sc0:sc1]
        aoi = np.ones_like(win)
        data = np.stack([win, aoi])
        with MemoryFile() as mem:
            with mem.open(driver='GTiff', height=h, width=w, count=2, dtype='uint8', crs=CRS,
                          transform=from_origin(xmin, ymax, 20, 20)) as dst:
                dst.write(data)
            return mem.read()

    s = Settings(_env_file=None, exposure_tile_px=40, exposure_tile_workers=3)
    fp = footprint.extract_from_earth_engine({'burn072': MagicMock()}, MagicMock(), BOUNDS, ['burn072'], s,
                                             aoi_metric=aoi_metric, downloader=downloader)
    return fp, glob, calls


def test_tiled_extract_stitches_tiles_without_seams(monkeypatch):
    fp, glob, calls = _tiled_extract(monkeypatch)
    assert len(calls) == 9
    assert fp.pixel_counts == {'burn072': int(glob.sum())}
    assert fp.footprints['burn072'].area == pytest.approx(int(glob.sum()) * 400)
    assert fp.footprints['burn072'].geom_type == 'MultiPolygon' and len(fp.footprints['burn072'].geoms) == 2
    # the blob that crosses two tile borders is ONE polygon: no seam
    areas = sorted(g.area for g in fp.footprints['burn072'].geoms)
    assert areas[-1] == pytest.approx(50 * 20 * 400)


def test_tiled_extract_skips_tiles_outside_known_aoi(monkeypatch):
    from shapely.geometry import box
    plan = footprint.plan_tiles(BOUNDS, CRS, 40)
    corner = box(plan.x0, plan.y1 - 30 * 20, plan.x0 + 30 * 20, plan.y1)      # inside the first tile only
    fp, _glob, calls = _tiled_extract(monkeypatch, aoi_metric=corner)
    assert len(calls) == 1 and fp.aoi_from_raster is False


def test_misaligned_tile_grid_is_an_error(monkeypatch):
    with pytest.raises(FootprintError, match='unexpected pixel grid'):
        _tiled_extract(monkeypatch, shift=7.0)                       # tiles offset by 7 m: not on the 20 m grid
