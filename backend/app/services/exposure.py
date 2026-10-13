"""Exposure & Impact orchestration.

Flow (all triggered by an explicit user action, never automatically after the wildfire analysis):

1. Resolve the affected footprint
   * ``analysis_ref`` (default): verify the signed reference, re-run the UNCHANGED V7.6 graph with the
     parameters the backend recorded, rasterise the cleaned burn masks once and vectorise locally.
   * ``hazard_geometry`` (separate mode): an external polygon supplied by the caller, validated here.
2. Fetch OpenStreetMap (bbox of the footprint + buffer) and WorldPop (real footprint polygon) in parallel.
   A failing source degrades the result to ``partial``; it never turns into a zero.
3. Compute indicators, sensitivity table, map layers and exports.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable

from shapely.geometry import MultiPolygon, Polygon, box, shape
from shapely.geometry.base import BaseGeometry
from shapely.validation import explain_validity

from ..core.config import Settings, get_settings
from ..core.errors import (
    ExposureAreaTooLargeError, ExternalSourceError, InvalidRequestError, NoAffectedAreaError,
    WildfireError,
)
from ..core.gate import slot
from ..core.geometry import validate_polygon
from ..schemas.exposure import ExposureRequest, ExposureResponse
from ..wildfire.config import THRESHOLD_SPECS
from . import analysis_ref, exposure_export, exposure_metrics, footprint, osm, spatial, worldpop
from .footprint import Footprint

logger = logging.getLogger('landai.exposure')

THRESHOLD_LABELS = {'wf035': 'Possible', 'wf050': 'Probable', 'wf060': 'Moderate-high',
                    'wf072': 'High confidence', 'wf085': 'Very high confidence'}
UNCERTAINTY_NOTE = ('Gridded model estimate (not a census count); it carries modelling uncertainty and '
                    'refers to the dataset year, not to the event date.')
WARNING_TEXT = {
    'osm_no_data': 'OpenStreetMap has no {category} mapped in the query area; this is unknown, not zero.',
    'osm_relations_skipped': '{count} OpenStreetMap multipolygon relations could not be assembled and were skipped.',
    'layer_truncated': 'Map layer "{layer}" shows {shown} of {total} features; indicators use all features.',
    'footprint_display_simplified': 'The affected-area layer was simplified for display only '
                                    '({before} to {after} vertices, area change {change}%). Indicators use the exact footprint.',
    'footprint_area_mismatch': 'The vectorised footprint ({vector_ha} ha) differs from the analysis-time area '
                               '({analysis_ha} ha) by {diff_pct}%.',
    'worldpop_simplified': 'The footprint was simplified before sending it to WorldPop '
                           '({before} to {after} vertices, area change {change}%).',
    'hazard_clipped_to_aoi': 'The supplied hazard polygon extends outside the study area; {pct}% of it was ignored.',
    'source_failed': 'The {source} source failed: {message}',
}
TOKEN_FIELDS = ('kind', 'fire_date', 'analysis_end', 'aoi_hectares', 'model_version', 'area_ha')


# ------------------------------------------------------------------------------------------------
# 1. Footprint resolution
# ------------------------------------------------------------------------------------------------
def threshold_key(threshold: float) -> tuple[str, str]:
    for value, key, area_key, _band in THRESHOLD_SPECS:
        if abs(value - threshold) < 1e-6:
            return key, area_key
    allowed = ', '.join(str(t[0]) for t in THRESHOLD_SPECS)
    raise InvalidRequestError(f'threshold must be one of: {allowed}.', details={'allowed': [t[0] for t in THRESHOLD_SPECS]})


def _resolve_earth_engine(ctx: dict, mask_keys: list[str], settings: Settings) -> Footprint:
    """Re-run the deterministic V7.6 graph for the recorded parameters and extract the masks."""
    import ee

    from ..wildfire.model import run_burn_model
    from . import administrative, aoi as aoi_service

    aoi_wgs84 = None
    if ctx['kind'] == 'drawn':
        drawn = aoi_service.build_drawn(ctx['ring'], ctx['aoi_hectares'])
        geometry, bounds_ll = drawn.geometry, ctx['ring_bounds']
        aoi_metric = None
        aoi_wgs84 = Polygon(ctx['ring'])
    else:
        collection = administrative.select_municipality(ctx['department'], ctx['municipality'])
        geometry = collection.geometry()
        bounds_ll = None            # read from Earth Engine below (exact extent of the municipal geometry)
        aoi_metric = None
        try:                         # municipal outline: only used to skip download tiles outside the municipality
            aoi_wgs84 = shape(administrative.boundary_geojson(collection)['geometry'])
        except Exception:  # noqa: BLE001 - an optimisation only; fall back to downloading every tile
            aoi_wgs84 = None
    result = run_burn_model(geometry, ee.Date(ctx['fire_date']), ee.Date(ctx['analysis_end']))
    if bounds_ll is None:
        from ..core.earth_engine import evaluate
        ring = evaluate(geometry.bounds(), 'reading the study-area extent')['coordinates'][0]
        xs, ys = [p[0] for p in ring], [p[1] for p in ring]
        bounds_ll = (min(xs), min(ys), max(xs), max(ys))
    fp = footprint.extract_from_earth_engine(result, geometry, tuple(bounds_ll), mask_keys, settings,
                                             aoi_metric=aoi_metric, aoi_wgs84=aoi_wgs84)
    if ctx['kind'] == 'drawn':
        fp.aoi = spatial.to_metric(Polygon(ctx['ring']), fp.crs)    # exact drawn ring, same CRS as raster
        fp.aoi_from_raster = False
    return fp


def _context_from_token(req: ExposureRequest, settings: Settings) -> dict:
    payload = analysis_ref.verify(req.analysis_ref or '')
    if any(k not in payload for k in TOKEN_FIELDS):
        raise InvalidRequestError('The analysis reference is incomplete. Run the wildfire analysis again.')
    hectares = float(payload['aoi_hectares'] or 0)
    if hectares > settings.max_exposure_aoi_hectares:
        raise ExposureAreaTooLargeError(
            f'The study area covers {hectares:,.0f} ha; the Exposure module accepts up to '
            f'{settings.max_exposure_aoi_hectares:,.0f} ha. Draw a smaller area.',
            details={'aoi_hectares': hectares, 'max_hectares': settings.max_exposure_aoi_hectares})
    ctx = {'mode': 'wildfire_analysis', 'kind': payload['kind'], 'aoi_hectares': hectares,
           'fire_date': payload['fire_date'], 'analysis_end': payload['analysis_end'],
           'model_version': payload['model_version'], 'analysis_area_ha': payload['area_ha'],
           'date_windows': payload.get('date_windows'),
           'department': payload.get('department'), 'municipality': payload.get('municipality')}
    if payload['kind'] == 'drawn':
        ring = payload['ring']
        xs, ys = [p[0] for p in ring], [p[1] for p in ring]
        ctx.update(ring=ring, ring_bounds=(min(xs), min(ys), max(xs), max(ys)))
    return ctx


def _external_footprint(req: ExposureRequest, settings: Settings) -> tuple[dict, Footprint, list[dict]]:
    """Validate a user-supplied hazard polygon (separate mode)."""
    check = validate_polygon(req.aoi_geometry.coordinates, settings.max_polygon_vertices)  # type: ignore[union-attr]
    if check.ring is None:
        raise InvalidRequestError('The study area polygon is not valid.',
                                  details=[{'code': c, 'params': p} for c, p in check.issues])
    hectares = float(check.hectares or 0)
    if hectares > settings.max_exposure_aoi_hectares:
        raise ExposureAreaTooLargeError(
            f'The study area covers {hectares:,.0f} ha; the Exposure module accepts up to '
            f'{settings.max_exposure_aoi_hectares:,.0f} ha.',
            details={'aoi_hectares': hectares, 'max_hectares': settings.max_exposure_aoi_hectares})
    try:
        hazard = shape(req.hazard_geometry.model_dump())  # type: ignore[union-attr]
    except Exception as exc:  # noqa: BLE001
        raise InvalidRequestError('The hazard polygon is not valid GeoJSON.') from exc
    if hazard.is_empty or not hazard.is_valid:
        raise InvalidRequestError(f'The hazard polygon is invalid: {explain_validity(hazard)}.')
    if spatial.count_vertices(hazard) > settings.exposure_max_hazard_vertices:
        raise InvalidRequestError('The hazard polygon has too many vertices.',
                                  details={'max_vertices': settings.exposure_max_hazard_vertices})
    minx, miny, maxx, maxy = hazard.bounds
    if not (-180 <= minx <= maxx <= 180 and -90 <= miny <= maxy <= 90):
        raise InvalidRequestError('The hazard polygon has coordinates outside valid longitude/latitude ranges.')
    aoi = Polygon(check.ring)
    warnings: list[dict] = []
    inside = hazard.intersection(aoi)
    if inside.is_empty:
        raise NoAffectedAreaError('The hazard polygon does not intersect the study area.')
    lost = 1 - inside.area / hazard.area if hazard.area else 0
    if lost > 0.01:
        warnings.append({'code': 'hazard_clipped_to_aoi', 'params': {'pct': round(lost * 100, 1)}})
        hazard = inside
    fp = footprint.from_geometries(hazard, aoi, key='user')
    ctx = {'mode': 'external_polygon', 'kind': 'drawn', 'aoi_hectares': hectares, 'fire_date': None,
           'analysis_end': None, 'model_version': None, 'analysis_area_ha': None, 'date_windows': None,
           'department': None, 'municipality': None, 'ring': check.ring}
    return ctx, fp, warnings


# ------------------------------------------------------------------------------------------------
# 2-3. Sources + indicators
# ------------------------------------------------------------------------------------------------
def _warning(code: str, **params) -> dict:
    text = WARNING_TEXT.get(code, code)
    try:
        message = text.format(**params)
    except (KeyError, IndexError):
        message = text
    return {'code': code, 'message': message, 'params': params}


def _source_error(exc: Exception, source: str) -> dict:
    if isinstance(exc, WildfireError):
        return {'code': exc.code, 'message': exc.message, 'details': getattr(exc, 'details', None)}
    logger.exception('exposure_source_failed source=%s', source)
    return {'code': 'internal_error', 'message': 'Unexpected error while contacting this source.', 'details': None}


def _fc(items: list[tuple[BaseGeometry, dict]], limit: int, extra: dict | None = None) -> dict:
    features = [spatial.feature(geom, props) for geom, props in items[:limit]]
    return {'type': 'FeatureCollection', 'features': features,
            'metadata': {'total': len(items), 'shown': len(features), **(extra or {})}}


def _display_footprint(metric_geom: BaseGeometry, crs: str, pixel_m: float, settings: Settings) -> tuple[BaseGeometry, dict]:
    before = spatial.count_vertices(metric_geom)
    info = {'vertices_before': before, 'vertices_after': before, 'simplified': False, 'area_change_pct': 0.0}
    geom = metric_geom
    if before > settings.exposure_max_display_vertices:
        tolerance = max(pixel_m / 2, 5.0)
        for _ in range(8):
            candidate = metric_geom.simplify(tolerance, preserve_topology=True)
            geom = candidate
            if spatial.count_vertices(candidate) <= settings.exposure_max_display_vertices:
                break
            tolerance *= 2
        change = (geom.area - metric_geom.area) / metric_geom.area * 100 if metric_geom.area else 0.0
        info.update(vertices_after=spatial.count_vertices(geom), simplified=True,
                    tolerance_m=tolerance, area_change_pct=round(change, 3))
    return spatial.to_wgs84(geom, crs), info


def build_response(req: ExposureRequest, ctx: dict, fp: Footprint, settings: Settings, *,
                   extra_warnings: list[dict] | None = None,
                   osm_fetch: Callable[..., osm.OsmData] | None = None,
                   pop_estimate: Callable[..., worldpop.PopulationResult] | None = None) -> dict:
    default_osm = osm_fetch is None
    osm_fetch = osm_fetch or osm.fetch                 # resolved at call time (patchable in tests)
    pop_estimate = pop_estimate or worldpop.estimate
    sel_key, area_key = threshold_key(req.threshold) if ctx['mode'] == 'wildfire_analysis' else ('user', '')
    hazard = fp.footprints[sel_key]
    if hazard.is_empty or hazard.area <= 0:
        raise NoAffectedAreaError(
            'No area reached the selected likelihood threshold, so there is no footprint to analyse. '
            'Try a lower threshold.', details={'threshold': req.threshold})
    buffer_m = settings.exposure_default_buffer_m if req.buffer_m is None else req.buffer_m
    if buffer_m > settings.exposure_max_buffer_m:
        raise InvalidRequestError(f'buffer_m must be at most {settings.exposure_max_buffer_m:g} m.',
                                  details={'max_buffer_m': settings.exposure_max_buffer_m})
    warnings: list[dict] = [_warning(w['code'], **w.get('params', {})) for w in (extra_warnings or [])]

    # Footprint bbox (largest footprint kept for the sensitivity table) + buffer -> OSM query box
    largest = max(fp.footprints.values(), key=lambda g: g.area)
    query_geom = spatial.to_wgs84(box(*largest.buffer(buffer_m + 50, quad_segs=1).bounds), fp.crs)
    bounds = query_geom.bounds
    # cells that cannot touch the (buffered) footprint are not requested from Overpass
    osm_region = spatial.to_wgs84(largest.buffer(buffer_m + 50, quad_segs=1), fp.crs)

    started = time.perf_counter()
    osm_result: dict[str, Any] = {}
    pop_result: dict[str, Any] = {}

    def run_osm():
        try:
            osm_result['data'] = (osm_fetch(bounds, settings, region=osm_region) if default_osm
                                  else osm_fetch(bounds, settings))
        except Exception as exc:  # noqa: BLE001
            osm_result['error'] = _source_error(exc, 'openstreetmap')

    def run_pop():
        try:
            pop_result['data'] = pop_estimate(hazard, fp.crs, settings)
        except Exception as exc:  # noqa: BLE001
            pop_result['error'] = _source_error(exc, 'worldpop')

    jobs = [run_osm] + ([run_pop] if req.include_population else [])
    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in [pool.submit(job) for job in jobs]:
            future.result()
    logger.info('exposure_sources_done seconds=%.1f osm=%s pop=%s', time.perf_counter() - started,
                'ok' if 'data' in osm_result else 'error',
                'skipped' if not req.include_population else ('ok' if 'data' in pop_result else 'error'))

    area_ha = round(spatial.area_ha(hazard), 2)
    metrics: dict[str, Any] = {
        'affected_area_ha': area_ha, 'affected_area_km2': round(area_ha / 100, 3), 'aoi_ha': round(float(ctx['aoi_hectares']), 2),
        'affected_pct_of_aoi': round(area_ha / float(ctx['aoi_hectares']) * 100, 2) if ctx['aoi_hectares'] else None}
    details: dict[str, Any] = {}
    layers: dict[str, Any] = {}
    sources: dict[str, Any] = {}
    sensitivity: list[dict] = []

    # --- Earth observation provenance + consistency check ------------------------------------------
    eo = {'status': 'success', 'details': {
        'method': 'cleaned burn masks of the validated V7.6 graph, rasterised at 20 m and vectorised locally'
        if ctx['mode'] == 'wildfire_analysis' else 'user-supplied polygon',
        'crs': fp.crs, 'pixel_size_m': fp.pixel_size_m, 'footprint_pixels': fp.pixel_counts.get(sel_key),
        'footprint_area_ha': area_ha, 'aoi_from_raster': fp.aoi_from_raster, 'grid': fp.grid}}
    recorded = (ctx.get('analysis_area_ha') or {}).get(area_key)
    if recorded:
        diff = abs(area_ha - recorded) / recorded * 100
        eo['details']['analysis_area_ha'] = recorded
        eo['details']['area_difference_pct'] = round(diff, 2)
        if diff > 2.0:
            warnings.append(_warning('footprint_area_mismatch', vector_ha=area_ha, analysis_ha=round(recorded, 2),
                                     diff_pct=round(diff, 1)))
    sources['earth_observation'] = eo

    # --- OpenStreetMap ----------------------------------------------------------------------------------
    if 'data' in osm_result:
        data: osm.OsmData = osm_result['data']
        em = exposure_metrics.compute(data, hazard, fp.crs, buffer_m=buffer_m,
                                      max_layer_features=settings.exposure_max_layer_features)
        metrics.update(em.metrics)
        details.update(em.details)
        for w in em.warnings:
            warnings.append(_warning(w['code'], **{k: v for k, v in w.items() if k != 'code'}))
        limit = settings.exposure_max_layer_features
        for name in ('buildings', 'roads', 'health', 'education'):
            layers[name] = _fc(em.layers.get(name, []), limit)
        sources['openstreetmap'] = {'status': 'success', 'details': {
            'endpoint': data.endpoint, 'retrieved_at': data.retrieved_at, 'bbox': list(data.bbox),
            'elements': data.element_count, 'from_cache': data.from_cache,
            'license': 'ODbL 1.0 - © OpenStreetMap contributors',
            'completeness': 'OpenStreetMap coverage varies by place; absence of features is not evidence of absence.'}}
        if req.include_sensitivity and ctx['mode'] == 'wildfire_analysis':
            for value, key, akey, _band in THRESHOLD_SPECS:
                geom = fp.footprints.get(key)
                if geom is None:
                    continue
                sm = exposure_metrics.compute(data, geom, fp.crs, buffer_m=buffer_m, with_layers=False,
                                              max_layer_features=settings.exposure_max_layer_features)
                sensitivity.append({
                    'threshold': value, 'key': akey, 'label': THRESHOLD_LABELS[akey],
                    'area_ha': round(spatial.area_ha(geom), 2),
                    'buildings_intersecting': sm.metrics['buildings_intersecting']['value'],
                    'roads_km_intersecting': sm.metrics['roads_km_intersecting']['value'],
                    'health_intersecting': sm.metrics['health_intersecting']['value'],
                    'education_intersecting': sm.metrics['education_intersecting']['value'],
                    'selected': key == sel_key})
    else:
        err = osm_result['error']
        sources['openstreetmap'] = {'status': 'error', 'details': {}, 'error': err}
        warnings.append(_warning('source_failed', source='OpenStreetMap', message=err['message']))
        for key, unit in (('buildings_intersecting', 'count'), ('buildings_within_buffer', 'count'),
                          ('roads_km_intersecting', 'km'), ('roads_km_within_buffer', 'km'),
                          ('health_intersecting', 'count'), ('health_within_buffer', 'count'),
                          ('education_intersecting', 'count'), ('education_within_buffer', 'count')):
            metrics[key] = {'value': None, 'coverage': 'unavailable', 'unit': unit}
        for name in ('buildings', 'roads', 'health', 'education'):
            layers[name] = _fc([], 0)

    # --- WorldPop ------------------------------------------------------------------------------------------
    if not req.include_population:
        sources['worldpop'] = {'status': 'skipped', 'details': {}}
        metrics['population'] = {'value': None, 'status': 'skipped', 'unit': 'people'}
    elif 'data' in pop_result:
        p: worldpop.PopulationResult = pop_result['data']
        sources['worldpop'] = {'status': 'success', 'details': {
            'api_version': p.api_version, 'task_id': p.task_id, 'retrieved_at': p.retrieved_at,
            'from_cache': p.from_cache, 'license': 'CC BY 4.0 - WorldPop'}}
        metrics['population'] = {
            'value': p.estimate, 'status': 'ok', 'unit': 'people', 'year': p.year, 'resolution': p.resolution,
            'dataset': p.dataset, 'api_version': p.api_version, 'analysis_area_ha': p.analysis_area_ha,
            'simplification': p.simplification, 'uncertainty_note': UNCERTAINTY_NOTE}
        if p.simplification.get('applied'):
            warnings.append(_warning('worldpop_simplified', before=p.simplification['vertices_before'],
                                     after=p.simplification['vertices_after'],
                                     change=p.simplification['area_change_pct']))
    else:
        err = pop_result['error']
        sources['worldpop'] = {'status': 'error', 'details': {}, 'error': err}
        metrics['population'] = {'value': None, 'status': 'unavailable', 'unit': 'people',
                                 'year': settings.worldpop_year, 'resolution': settings.worldpop_resolution,
                                 'reason': err['code']}
        warnings.append(_warning('source_failed', source='WorldPop', message=err['message']))

    # --- Layers (display only) ------------------------------------------------------------------------------------
    display, dinfo = _display_footprint(hazard, fp.crs, fp.pixel_size_m, settings)
    if dinfo['simplified']:
        warnings.append(_warning('footprint_display_simplified', before=dinfo['vertices_before'],
                                 after=dinfo['vertices_after'], change=dinfo['area_change_pct']))
    layers['footprint'] = {'type': 'FeatureCollection', 'features': [spatial.feature(display, {
        'role': 'affected_footprint', 'threshold': req.threshold if ctx['mode'] == 'wildfire_analysis' else None,
        'area_ha': area_ha})], 'metadata': {'display': dinfo}}
    aoi_display, _ = _display_footprint(fp.aoi, fp.crs, max(fp.pixel_size_m, 20), settings)
    layers['aoi'] = {'type': 'FeatureCollection', 'features': [spatial.feature(aoi_display, {
        'role': 'study_area', 'area_ha': round(float(ctx['aoi_hectares']), 2)})], 'metadata': {}}
    buf_geom = hazard.buffer(buffer_m, quad_segs=2).simplify(max(fp.pixel_size_m, 20), preserve_topology=True) \
        if buffer_m > 0 else hazard
    layers['buffer'] = {'type': 'FeatureCollection', 'features': [spatial.feature(
        spatial.to_wgs84(buf_geom, fp.crs), {'role': 'proximity_buffer', 'buffer_m': buffer_m})], 'metadata': {}}

    # --- Assemble --------------------------------------------------------------------------------------------------------
    failed = [name for name, s in sources.items() if s['status'] == 'error']
    analysis = {
        'mode': ctx['mode'], 'aoi_kind': ctx['kind'], 'aoi_hectares': round(float(ctx['aoi_hectares']), 2),
        'department': ctx.get('department'), 'municipality': ctx.get('municipality'),
        'threshold': req.threshold if ctx['mode'] == 'wildfire_analysis' else None,
        'threshold_label': THRESHOLD_LABELS.get(area_key), 'event_date': ctx.get('fire_date'),
        'analysis_end': ctx.get('analysis_end'), 'date_windows': ctx.get('date_windows'),
        'model_version': ctx.get('model_version'), 'buffer_m': buffer_m,
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'definitions': {
            'study_area': 'Area analysed by the wildfire model (municipality or drawn polygon).',
            'affected_area': 'Satellite-derived potentially affected area (footprint) at the selected threshold.',
            'exposure_geometry': 'Footprint used to intersect OpenStreetMap features and population.',
            'buffer': f'Proximity indicator of {buffer_m:g} m around the footprint; not a damage zone.'},
        'custom_aoi_note': ('Custom polygons run the same V7.6 algorithm, but sampling, cleaning and VIIRS seeds '
                            'depend on the study area, so results are not numerically equivalent to the '
                            'municipality run.' if ctx['kind'] == 'drawn' else None),
    }
    response = {
        'status': 'partial' if failed else 'success', 'hazard_type': 'wildfire', 'mode': ctx['mode'],
        'analysis': analysis, 'metrics': metrics, 'details': details, 'sensitivity': sensitivity,
        'sources': sources, 'warnings': warnings, 'layers': layers,
        'notice': {'en': exposure_export.NOTICE_EN, 'es': exposure_export.NOTICE_ES}}
    response['exports'] = {
        'csv': exposure_export.build_csv(metrics, analysis, sources),
        'report': exposure_export.build_report(response)}
    return response


# ------------------------------------------------------------------------------------------------
def analyze(req: ExposureRequest, settings: Settings | None = None) -> ExposureResponse:
    settings = settings or get_settings()
    started = time.perf_counter()
    with slot('exposure', settings.exposure_max_concurrent,
              busy_message='Another exposure analysis is running. Please retry in a minute.'):
        if req.analysis_ref:
            ctx = _context_from_token(req, settings)
            keys = [k for _t, k, _a, _b in THRESHOLD_SPECS] if req.include_sensitivity \
                else [threshold_key(req.threshold)[0]]
            sel = threshold_key(req.threshold)[0]
            if sel not in keys:
                keys.append(sel)
            fp = _resolve_earth_engine(ctx, keys, settings)
            extra = []
        else:
            ctx, fp, extra = _external_footprint(req, settings)
        payload = build_response(req, ctx, fp, settings, extra_warnings=extra)
    logger.info('exposure_completed mode=%s status=%s seconds=%.1f', ctx['mode'], payload['status'],
                time.perf_counter() - started)
    return ExposureResponse(**payload)
