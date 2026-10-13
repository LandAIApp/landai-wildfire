"""Hazard footprint extraction for the Exposure module.

Method (chosen after comparing the alternatives, see docs/exposure-methodology.md):

* The footprint is the EXACT final cleaned burn mask (burn035..burn085 from the unchanged V7.6 graph),
  rasterised ONCE at the analysis scale (20 m) on a UTM grid with ``getDownloadURL`` (single multi-band
  GeoTIFF, bounded by EXPOSURE_MAX_PIXELS) and vectorised locally with rasterio (pixel-exact, 8-connected,
  no simplification). ``reduceToVectors`` is never used: it is unbounded for fragmented masks.
* The AOI polygon used to filter OSM is the exact drawn polygon, or, for a municipality, the 20 m
  raster of the municipal geometry (boundary deviates by less than one pixel from the vector).
* Lengths/areas are computed in the same UTM CRS as the raster.
"""
from __future__ import annotations

import io
import logging
import zipfile
from dataclasses import dataclass, field

import ee
import httpx
import numpy as np
import rasterio
import rasterio.features
from rasterio.io import MemoryFile
from shapely.geometry import Polygon, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from ..core.config import Settings
from ..core.earth_engine import ensure_initialized, map_ee_error
from ..core.errors import ExposureAreaTooLargeError, FootprintError, WildfireError
from ..wildfire.config import AREA_SCALE, THRESHOLD_SPECS
from . import spatial

logger = logging.getLogger('landai.exposure')

AOI_BAND = 'AOI'
# mask key (burn050) -> (threshold, area key wf050, band name Burn050)
THRESHOLD_BY_KEY = {key: (t, area_key, band) for t, key, area_key, band in THRESHOLD_SPECS}


@dataclass
class Footprint:
    """Footprints and AOI in a metric CRS (``crs``), plus raster provenance."""

    crs: str
    pixel_size_m: float
    aoi: BaseGeometry
    footprints: dict[str, BaseGeometry]            # mask key -> geometry (metric CRS)
    pixel_counts: dict[str, int] = field(default_factory=dict)
    source: str = 'wildfire_analysis'              # | user_supplied
    grid: dict = field(default_factory=dict)       # provenance: transform, shape, crs
    aoi_from_raster: bool = False

    def area_ha(self, key: str) -> float:
        return spatial.area_ha(self.footprints[key])


def estimate_pixels(bounds: tuple[float, float, float, float], crs: str, scale: float = AREA_SCALE) -> int:
    width, height = spatial.projected_bbox_size(bounds, crs)
    return int(np.ceil(width / scale) * np.ceil(height / scale))


def vectorize(array: np.ndarray, transform) -> BaseGeometry:
    """Union of the connected components of a 0/1 raster (pixel-exact, 8-connected, no simplification)."""
    mask = (array > 0).astype('uint8')
    if not mask.any():
        return Polygon()
    parts = [shape(geom) for geom, value in rasterio.features.shapes(mask, mask=mask.astype(bool),
                                                                      transform=transform, connectivity=8)
             if value == 1]
    return unary_union(parts) if len(parts) > 1 else parts[0]


def read_download(content: bytes, band_names: list[str]) -> tuple[dict[str, np.ndarray], object, str]:
    """Parse the Earth Engine download: a multi-band GeoTIFF, or a zip with one GeoTIFF per band."""
    if content[:2] == b'PK':
        arrays: dict[str, np.ndarray] = {}
        transform, crs = None, ''
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            for member in archive.namelist():
                if not member.lower().endswith(('.tif', '.tiff')):
                    continue
                name = next((b for b in band_names if f'.{b}.' in member or member.endswith(f'{b}.tif')), None)
                if name is None:
                    continue
                with MemoryFile(archive.read(member)) as mem, mem.open() as src:
                    arrays[name] = src.read(1)
                    transform, crs = src.transform, str(src.crs)
        missing = [b for b in band_names if b not in arrays]
        if missing:
            raise FootprintError('The Earth Engine download did not contain all requested bands.',
                                 details={'missing': missing})
        return arrays, transform, crs
    with MemoryFile(content) as mem, mem.open() as src:
        if src.count != len(band_names):
            raise FootprintError('The Earth Engine download has an unexpected number of bands.',
                                 details={'expected': len(band_names), 'found': src.count})
        data = src.read()
        return ({name: data[i] for i, name in enumerate(band_names)}, src.transform, str(src.crs))


def _download_error_details(response: httpx.Response) -> dict:
    """HTTP status plus Earth Engine's own explanation (the download endpoint answers 4xx with a JSON/text
    body such as 'Computation timed out.' or 'Total request size ... must be less than ...')."""
    details: dict = {'http_status': response.status_code}
    try:
        body = response.read()[:2000].decode('utf-8', errors='replace')
    except httpx.HTTPError:
        body = ''
    message = body.strip()
    try:
        import json
        payload = json.loads(body)
        if isinstance(payload, dict):
            err = payload.get('error')
            message = (err.get('message') if isinstance(err, dict) else err) or message
    except ValueError:
        pass
    if message:
        details['earth_engine_message'] = str(message)[:500]
    logger.warning('footprint_download_rejected status=%s message=%s', response.status_code, message[:500])
    return details


def _download(url: str, settings: Settings) -> bytes:
    limit = 60_000_000
    chunks, size = [], 0
    try:
        with httpx.stream('GET', url, timeout=settings.exposure_download_timeout_s,
                          follow_redirects=True) as response:
            if response.status_code != 200:
                raise FootprintError('Earth Engine could not deliver the footprint raster.',
                                     details=_download_error_details(response))
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > limit:
                    raise FootprintError('The footprint raster is larger than the allowed size. Use a smaller area.')
                chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise FootprintError('The footprint raster download failed.', details=type(exc).__name__) from exc
    return b''.join(chunks)


def extract_from_earth_engine(result: dict, aoi: ee.Geometry, bounds: tuple[float, float, float, float],
                              mask_keys: list[str], settings: Settings,
                              aoi_metric: BaseGeometry | None = None,
                              downloader=_download) -> Footprint:
    """Rasterise the requested cleaned burn masks (and the AOI) once and vectorise them.

    ``result`` is the dictionary returned by run_burn_model (unchanged scientific graph).
    ``bounds`` = (west, south, east, north) of the AOI. ``aoi_metric`` is the exact AOI in the UTM CRS
    when it is known locally (drawn polygons); otherwise it is reconstructed from the AOI raster band.
    """
    west, south, east, north = bounds
    crs = spatial.utm_epsg((west + east) / 2, (south + north) / 2)
    pixels = estimate_pixels(bounds, crs)
    if pixels > settings.exposure_max_pixels:
        raise ExposureAreaTooLargeError(
            f'The analysis area spans {pixels:,} pixels at {AREA_SCALE} m, above the exposure limit of '
            f'{settings.exposure_max_pixels:,}. Use a smaller area.',
            details={'pixels': pixels, 'max_pixels': settings.exposure_max_pixels})

    names = [THRESHOLD_BY_KEY[k][2] for k in mask_keys]
    bands = [result[k].unmask(0).toByte().rename(THRESHOLD_BY_KEY[k][2]) for k in mask_keys]
    bands.append(ee.Image.constant(1).clip(aoi).unmask(0).toByte().rename(AOI_BAND))
    image = ee.Image.cat(bands)
    ensure_initialized()
    try:
        url = image.getDownloadURL({
            'region': ee.Geometry.Rectangle([west, south, east, north], None, False),
            'crs': crs, 'scale': AREA_SCALE, 'format': 'GEO_TIFF', 'filePerBand': False})
    except ee.EEException as exc:
        raise map_ee_error(exc, 'preparing the affected-area raster') from exc
    except WildfireError:
        raise
    content = downloader(url, settings)
    arrays, transform, file_crs = read_download(content, names + [AOI_BAND])
    if file_crs and file_crs.upper() != crs.upper():
        # keep the raster's own CRS as the metric CRS (it is projected); never assume
        crs = file_crs
    footprints, counts = {}, {}
    for key, band in zip(mask_keys, names):
        footprints[key] = vectorize(arrays[band], transform)
        counts[key] = int((arrays[band] > 0).sum())
    from_raster = aoi_metric is None
    aoi_geom = aoi_metric if aoi_metric is not None else vectorize(arrays[AOI_BAND], transform)
    return Footprint(
        crs=crs, pixel_size_m=float(abs(transform.a)), aoi=aoi_geom, footprints=footprints,
        pixel_counts=counts, aoi_from_raster=from_raster,
        grid={'crs': crs, 'transform': [float(v) for v in tuple(transform)[:6]],
              'shape': list(next(iter(arrays.values())).shape), 'requested_scale_m': AREA_SCALE})


def from_geometries(hazard_wgs84: BaseGeometry, aoi_wgs84: BaseGeometry, key: str = 'user') -> Footprint:
    """Externally supplied hazard polygon (separate input mode, NOT the validated wildfire workflow)."""
    c = aoi_wgs84.centroid
    crs = spatial.utm_epsg(c.x, c.y)
    return Footprint(crs=crs, pixel_size_m=0.0, aoi=spatial.to_metric(aoi_wgs84, crs),
                     footprints={key: spatial.to_metric(hazard_wgs84, crs)}, source='user_supplied')
