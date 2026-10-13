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
