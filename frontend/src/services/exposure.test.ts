// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { EXPOSURE, noOsmExposure } from '../test/fixtures';
import { DEFAULT_CONFIG, mergeConfig } from './config';
import { buildCsv, buildGeoJson, displayMetric, exportFileName, sourceState } from './exposure';
import { translateOptional } from '../i18n';
import { popupFor } from '../components/MapView';

describe('exposure helpers', () => {
  it('missing metrics are "unavailable", never a zero', () => {
    expect(displayMetric({ value: null, unit: 'count', coverage: 'unavailable' }, 'en'))
      .toEqual({ kind: 'missing', reason: 'unavailable' });
    expect(displayMetric({ value: null, unit: 'count', coverage: 'no_osm_data' }, 'en'))
      .toEqual({ kind: 'missing', reason: 'no_osm_data' });
    expect(displayMetric({ value: 0, unit: 'count', coverage: 'mapped' }, 'en')).toEqual({ kind: 'value', text: '0' });
    expect(displayMetric(undefined, 'es').kind).toBe('missing');
    expect(noOsmExposure().metrics.buildings_intersecting.value).toBeNull();
  });
  it('formats decimals per language', () => {
    expect(displayMetric({ value: 7.55, unit: 'km', coverage: 'mapped' }, 'en', 1)).toEqual({ kind: 'value', text: '7.6' });
    expect(displayMetric({ value: 7.55, unit: 'km', coverage: 'mapped' }, 'es', 1)).toEqual({ kind: 'value', text: '7,6' });
  });
  it('GeoJSON export keeps the AOI and the footprint as separate layers', () => {
    const geo = buildGeoJson(EXPOSURE);
    const layers = new Set(geo.features.map((f) => f.properties?.layer));
    expect(layers).toEqual(new Set(['aoi', 'footprint', 'roads', 'buildings', 'health']));
    const aoi = geo.features.find((f) => f.properties?.layer === 'aoi')!;
    const footprint = geo.features.find((f) => f.properties?.layer === 'footprint')!;
    expect(aoi.geometry).not.toEqual(footprint.geometry);
  });
  it('CSV comes from the backend and file names are stable', () => {
    expect(buildCsv(EXPOSURE)).toContain('indicator,value,unit,status,source,notes');
    expect(exportFileName(EXPOSURE, 'csv')).toBe('landai-exposure-san-luis-2026-08-05.csv');
  });
  it('derives per-source state', () => {
    expect(sourceState(null, 'worldpop', true)).toBe('loading');
    expect(sourceState(null, 'worldpop', false)).toBe('idle');
    expect(sourceState(EXPOSURE, 'openstreetmap', false)).toBe('success');
  });
});

describe('config', () => {
  it('falls back to defaults for old/partial backends and merges newer ones', () => {
    expect(mergeConfig(null)).toBe(DEFAULT_CONFIG);
    const merged = mergeConfig({ aoi: { custom: { max_hectares: 1234 } } } as never);
    expect(merged.aoi.custom.max_hectares).toBe(1234);
    expect(merged.aoi.custom.max_vertices).toBe(DEFAULT_CONFIG.aoi.custom.max_vertices);
  });
});

describe('popup', () => {
  it('renders untrusted OSM text as text, never as HTML', () => {
    const tr = (key: string) => translateOptional('en', key);
    const el = popupFor('health', { type: 'Feature', geometry: { type: 'Point', coordinates: [0, 0] },
      properties: { name: '<img src=x onerror=alert(1)>', class: 'clinic', distance_m: 12 } }, 'en', tr);
    expect(el.querySelector('img')).toBeNull();
    expect(el.textContent).toContain('<img src=x onerror=alert(1)>');
  });
});

describe('i18n coverage of v2 codes', () => {
  const codes = {
    issues: ['aoi_too_small', 'geometry_holes', 'geometry_out_of_range', 'geometry_too_few_points',
      'geometry_too_many_points', 'geometry_self_intersecting', 'geometry_degenerate', 'aoi_too_large'],
    errors: ['rate_limit_exceeded', 'server_busy', 'invalid_analysis_ref', 'exposure_aoi_too_large',
      'footprint_extraction_failed', 'no_affected_area', 'osm_unavailable', 'osm_timeout', 'osm_rate_limited',
      'osm_too_many_elements', 'osm_incomplete', 'worldpop_timeout', 'worldpop_unreachable', 'worldpop_task_failed',
      'worldpop_bad_response', 'worldpop_http_error', 'worldpop_rate_limited', 'worldpop_geometry_too_complex'],
    'exposure.warn': ['osm_no_data', 'osm_relations_skipped', 'layer_truncated', 'footprint_display_simplified',
      'footprint_area_mismatch', 'worldpop_simplified', 'hazard_clipped_to_aoi', 'source_failed'],
    'exposure.building': ['residential', 'commercial', 'industrial', 'public', 'agricultural', 'other'],
    'exposure.road': ['motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'unclassified', 'residential',
      'service', 'living_street', 'track', 'road'],
  } as const;
  for (const [prefix, list] of Object.entries(codes)) {
    it(`translates every ${prefix} code in ES and EN`, () => {
      for (const code of list) for (const lang of ['es', 'en'] as const) {
        expect(translateOptional(lang, `${prefix}.${code}`), `${lang} ${prefix}.${code}`).toBeTruthy();
      }
    });
  }
});
