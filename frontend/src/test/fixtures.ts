import type { AnalyzeResponse, ExposureResponse, PublicConfig } from '../types/api';

export const CONFIG: PublicConfig = {
  status: 'ok', version: '2.0.0',
  aoi: {
    municipality: { max_hectares: 500000, warn_hectares: 100000 },
    custom: { max_hectares: 100000, warn_hectares: 50000, min_hectares: 10, max_vertices: 300 },
    min_fire_date: '2018-08-01',
  },
  exposure: {
    max_aoi_hectares: 50000, default_buffer_m: 500, max_buffer_m: 2000, max_layer_features: 5000,
    thresholds: [0.35, 0.5, 0.6, 0.72, 0.85], default_threshold: 0.72, population_year: 2020,
    population_resolution: '100m',
  },
  rate_limits: { analyze: [{ count: 5, per: 'HOUR' }], exposure: [{ count: 10, per: 'HOUR' }], enabled: true },
  sources: {},
};

export const ANALYSIS: AnalyzeResponse = {
  status: 'ok',
  metadata: { model_version: 'V7.6', equivalence_validated: false, aoi_kind: 'municipality', department: 'Tolima',
    municipality: 'San Luis', fire_date: '2026-08-05', analysis_end: '2026-08-15', aoi_hectares: 28000,
    generated_at: '2026-10-01T10:00:00+00:00', disclaimer: '' },
  image_counts: { pre: 5, post: 2, history: 9 },
  date_windows: { pre: { start: '2026-05-07', end: '2026-07-28' }, post: { start: '2026-08-05', end: '2026-08-15' },
    history: { start: null, end: null } },
  training: { positive_samples: 800, negative_samples: 2000, note: '' },
  area_statistics: { wf072: 400 },
  area_hectares: [
    { threshold: 0.35, key: 'wf035', label: 'Possible', hectares: 520 },
    { threshold: 0.5, key: 'wf050', label: 'Probable', hectares: 480 },
    { threshold: 0.6, key: 'wf060', label: 'Moderate-high', hectares: 440 },
    { threshold: 0.72, key: 'wf072', label: 'High confidence', hectares: 400 },
    { threshold: 0.85, key: 'wf085', label: 'Very high confidence', hectares: 300 },
  ],
  layers: [{ id: 'post', label: 'POST', group: 'Imagery', description: 'd', tile_url: 'https://x/{z}/{x}/{y}',
    visible_by_default: true, legend: null }],
  boundary: { type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [0, 0] } },
  bounds: [[0, 0], [1, 1]], warnings: [], analysis_ref: 'signed-ref.abc',
  aoi: { kind: 'municipality', hectares: 28000, department: 'Tolima', municipality: 'San Luis' },
};

const metric = (value: number | null, unit = 'count', coverage: 'mapped' | 'no_osm_data' | 'unavailable' = 'mapped') =>
  ({ value, unit, coverage });
const square = (x: number, y: number, d: number): GeoJSON.Polygon =>
  ({ type: 'Polygon', coordinates: [[[x, y], [x + d, y], [x + d, y + d], [x, y + d], [x, y]]] });

export const EXPOSURE: ExposureResponse = {
  status: 'success', hazard_type: 'wildfire', mode: 'wildfire_analysis',
  analysis: { mode: 'wildfire_analysis', aoi_kind: 'municipality', aoi_hectares: 28000, department: 'Tolima',
    municipality: 'San Luis', threshold: 0.72, threshold_label: 'High confidence', event_date: '2026-08-05',
    analysis_end: '2026-08-15', date_windows: ANALYSIS.date_windows, model_version: 'V7.6', buffer_m: 500,
    generated_at: '2026-10-02T12:00:00+00:00', custom_aoi_note: null },
  metrics: {
    affected_area_ha: 400, affected_area_km2: 4, aoi_ha: 28000, affected_pct_of_aoi: 1.43,
    population: { value: 1234, status: 'ok', unit: 'people', year: 2020, resolution: '100m', dataset: 'WorldPop',
      api_version: 'v2', uncertainty_note: 'x', simplification: { applied: false, vertices_before: 10, vertices_after: 10, tolerance_m: 0, area_change_pct: 0 } },
    buildings_intersecting: metric(42), buildings_within_buffer: metric(60),
    roads_km_intersecting: metric(7.5, 'km'), roads_km_within_buffer: metric(9.1, 'km'),
    health_intersecting: metric(1), health_within_buffer: metric(2),
    education_intersecting: metric(0), education_within_buffer: metric(1),
  },
  details: {
    buildings_by_category: { residential: { intersecting: 40, within_buffer: 55 }, commercial: { intersecting: 2, within_buffer: 5 } },
    roads_km_by_class: { primary: 4.2, residential: 3.3 },
    health_facilities: [{ osm: 'node/1', name: 'Clínica Central', class: 'clinic', distance_m: 0, status: 'intersecting' }],
    education_facilities: [{ osm: 'way/2', name: 'Escuela Rural', class: 'school', distance_m: 310, status: 'within_buffer' }],
  },
  sensitivity: [
    { threshold: 0.35, key: 'wf035', label: 'Possible', area_ha: 520, buildings_intersecting: 50, roads_km_intersecting: 9, health_intersecting: 1, education_intersecting: 0, selected: false },
    { threshold: 0.72, key: 'wf072', label: 'High confidence', area_ha: 400, buildings_intersecting: 42, roads_km_intersecting: 7.5, health_intersecting: 1, education_intersecting: 0, selected: true },
  ],
  sources: {
    earth_observation: { status: 'success', details: {} },
    openstreetmap: { status: 'success', details: { retrieved_at: '2026-10-02T11:59:00+00:00' } },
    worldpop: { status: 'success', details: {} },
  },
  warnings: [],
  layers: {
    aoi: { type: 'FeatureCollection', features: [{ type: 'Feature', properties: { role: 'study_area' }, geometry: square(-75.3, 4.0, 0.3) }] },
    footprint: { type: 'FeatureCollection', features: [{ type: 'Feature', properties: { role: 'affected_footprint', area_ha: 400 }, geometry: square(-75.2, 4.1, 0.02) }] },
    buildings: { type: 'FeatureCollection', features: [{ type: 'Feature', properties: { category: 'residential', osm: 'way/9' }, geometry: square(-75.19, 4.11, 0.0005) }], metadata: { total: 42, shown: 1 } },
    roads: { type: 'FeatureCollection', features: [{ type: 'Feature', properties: { class: 'primary' }, geometry: { type: 'LineString', coordinates: [[-75.2, 4.1], [-75.18, 4.12]] } }] },
    health: { type: 'FeatureCollection', features: [{ type: 'Feature', properties: { name: 'Clínica Central' }, geometry: { type: 'Point', coordinates: [-75.19, 4.11] } }] },
  },
  exports: { csv: 'indicator,value,unit,status,source,notes\naffected_area_ha,400,ha,ok,x,\n', report: { report_type: 'landai_exposure_report' } },
  notice: { en: '', es: '' },
};

export function partialExposure(): ExposureResponse {
  const e = structuredClone(EXPOSURE);
  e.status = 'partial';
  e.metrics.population = { value: null, status: 'unavailable', unit: 'people', year: 2020, resolution: '100m', reason: 'worldpop_timeout' };
  e.sources.worldpop = { status: 'error', details: {}, error: { code: 'worldpop_timeout', message: 'WorldPop did not answer in time.' } };
  e.warnings = [{ code: 'source_failed', message: 'The WorldPop source failed: WorldPop did not answer in time.', params: { source: 'WorldPop', message: 'WorldPop did not answer in time.' } }];
  return e;
}

export function noOsmExposure(): ExposureResponse {
  const e = structuredClone(EXPOSURE);
  for (const k of ['buildings_intersecting', 'buildings_within_buffer', 'roads_km_intersecting', 'roads_km_within_buffer',
    'health_intersecting', 'health_within_buffer', 'education_intersecting', 'education_within_buffer'] as const) {
    e.metrics[k] = { value: null, unit: 'count', coverage: 'unavailable' };
  }
  e.details = {};
  e.sensitivity = [];
  e.sources.openstreetmap = { status: 'error', details: {}, error: { code: 'osm_unavailable', message: 'down' } };
  e.status = 'partial';
  return e;
}
