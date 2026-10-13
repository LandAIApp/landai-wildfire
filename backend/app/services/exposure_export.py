"""Export builders for the Exposure module: CSV summary, metadata report and combined GeoJSON.

The study area (AOI) is exported as its own feature (``layer='aoi'``) and is NEVER used as the footprint.
"""
from __future__ import annotations

import csv
import io
from typing import Any

NOTICE_EN = ('Exposure estimates are preliminary. Intersecting buildings, roads or population with a '
             'satellite-derived affected area does not confirm physical damage, casualties or displacement.')
NOTICE_ES = ('Las estimaciones de exposición son preliminares. La intersección de edificios, vías o '
             'población con un área potencialmente afectada no confirma daños físicos, víctimas ni '
             'desplazamientos.')

CSV_HEADER = ['indicator', 'value', 'unit', 'status', 'source', 'notes']


def _row(indicator: str, metric: dict | None, source: str, notes: str = '') -> list:
    if metric is None:
        return [indicator, '', '', 'unavailable', source, notes]
    value = metric.get('value')
    status = 'ok' if value is not None else (metric.get('coverage') or metric.get('status') or 'unavailable')
    return [indicator, '' if value is None else value, metric.get('unit', ''), status, source, notes]


def build_csv(metrics: dict[str, Any], analysis: dict[str, Any], sources: dict[str, Any]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator='\n')
    writer.writerow(CSV_HEADER)
    eo = 'Land AI wildfire analysis (Sentinel-2 / VIIRS, V7.6)' if analysis.get('mode') == 'wildfire_analysis' \
        else 'User-supplied hazard polygon'
    writer.writerow(['affected_area_ha', metrics.get('affected_area_ha'), 'ha', 'ok', eo,
                     f"threshold={analysis.get('threshold')}"])
    writer.writerow(['affected_area_km2', metrics.get('affected_area_km2'), 'km2', 'ok', eo, ''])
    writer.writerow(['study_area_ha', metrics.get('aoi_ha'), 'ha', 'ok', 'AOI', ''])
    writer.writerow(['affected_pct_of_study_area', metrics.get('affected_pct_of_aoi'), '%', 'ok', eo, ''])
    pop = metrics.get('population') or {}
    writer.writerow([
        'population_estimate', '' if pop.get('value') is None else pop.get('value'), 'people',
        'ok' if pop.get('value') is not None else pop.get('status', 'unavailable'),
        f"WorldPop {pop.get('api_version', '')} year={pop.get('year')} resolution={pop.get('resolution')}",
        'Gridded model estimate, not a census count'])
    osm = 'OpenStreetMap contributors (ODbL), via Overpass'
    for key in ('buildings_intersecting', 'buildings_within_buffer', 'roads_km_intersecting',
                'roads_km_within_buffer', 'health_intersecting', 'health_within_buffer',
                'education_intersecting', 'education_within_buffer'):
        writer.writerow(_row(key, metrics.get(key), osm,
                             f"buffer_m={analysis.get('buffer_m')}" if 'buffer' in key else ''))
    for name, src in sources.items():
        writer.writerow([f'source_{name}_status', src.get('status'), '', src.get('status'), name, ''])
    return out.getvalue()


def build_report(response: dict[str, Any]) -> dict[str, Any]:
    """Metadata JSON report: everything needed to reproduce / interpret the numbers (no geometries)."""
    return {
        'report_type': 'landai_exposure_report',
        'version': 1,
        'status': response['status'],
        'hazard_type': response['hazard_type'],
        'mode': response['mode'],
        'analysis': response['analysis'],
        'metrics': response['metrics'],
        'details': response['details'],
        'sensitivity': response.get('sensitivity', []),
        'sources': response['sources'],
        'warnings': response['warnings'],
        'notice': {'en': NOTICE_EN, 'es': NOTICE_ES},
        'attribution': ['OpenStreetMap contributors (ODbL)', 'WorldPop (CC BY 4.0)',
                        'Contains modified Copernicus Sentinel data; NASA VIIRS (via Google Earth Engine)'],
    }


def build_geojson(layers: dict[str, Any]) -> dict[str, Any]:
    """One FeatureCollection with a ``layer`` property per feature (aoi, footprint, buildings, ...)."""
    features = []
    for name in ('aoi', 'footprint', 'buffer', 'buildings', 'roads', 'health', 'education'):
        collection = layers.get(name)
        if not collection:
            continue
        for feature in collection.get('features', []):
            copy = {**feature, 'properties': {**(feature.get('properties') or {}), 'layer': name}}
            features.append(copy)
    return {'type': 'FeatureCollection', 'features': features}
