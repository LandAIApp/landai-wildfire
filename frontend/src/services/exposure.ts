import type { Language } from '../i18n';
import { formatDecimal, formatNumber } from './format';
import type {
  ExposureLayerName, ExposureMetric, ExposureResponse, SourceKey, SourceStatus,
} from '../types/api';

/** Layers the user can toggle on the map, in drawing order (bottom → top). */
export const EXPOSURE_LAYERS: readonly ExposureLayerName[] =
  ['aoi', 'buffer', 'footprint', 'roads', 'buildings', 'health', 'education'];

export const DEFAULT_EXPOSURE_VISIBLE: Record<ExposureLayerName, boolean> = {
  aoi: true, buffer: false, footprint: true, roads: true, buildings: true, health: true, education: true,
};

export const LAYER_COLORS: Record<ExposureLayerName, string> = {
  aoi: '#ffffff', buffer: '#f5c451', footprint: '#ff7a45', roads: '#6fd3ff',
  buildings: '#ff4d6d', health: '#ff6bd6', education: '#b69cff',
};

/** What to show for a metric: a number, or "unavailable" – never a silent zero. */
export type MetricDisplay = { kind: 'value'; text: string } | { kind: 'missing'; reason: 'no_osm_data' | 'unavailable' };

export function displayMetric(metric: ExposureMetric | undefined, lang: Language, digits = 0): MetricDisplay {
  if (!metric || metric.value === null || metric.value === undefined) {
    return { kind: 'missing', reason: metric?.coverage === 'no_osm_data' ? 'no_osm_data' : 'unavailable' };
  }
  return { kind: 'value', text: digits ? formatDecimal(metric.value, lang, digits) : formatNumber(metric.value, lang) };
}

export function displayPopulation(res: ExposureResponse, lang: Language): MetricDisplay {
  const p = res.metrics.population;
  if (p.value === null || p.value === undefined) return { kind: 'missing', reason: 'unavailable' };
  return { kind: 'value', text: formatNumber(p.value, lang) };
}

export function sourceState(res: ExposureResponse | null, key: SourceKey, loading: boolean): 'loading' | SourceStatus['status'] | 'idle' {
  if (loading) return 'loading';
  if (!res) return 'idle';
  return res.sources[key]?.status ?? 'idle';
}

// ------------------------------- exports ------------------------------------
/** One FeatureCollection: AOI and exposure geometries, each with a `layer` property. The AOI is its own
 *  feature and is never presented as the affected footprint. */
export function buildGeoJson(res: ExposureResponse): GeoJSON.FeatureCollection {
  const features: GeoJSON.Feature[] = [];
  for (const name of EXPOSURE_LAYERS) {
    for (const f of res.layers[name]?.features ?? []) {
      features.push({ ...f, properties: { ...(f.properties ?? {}), layer: name } });
    }
  }
  return { type: 'FeatureCollection', features };
}

export const buildCsv = (res: ExposureResponse): string => res.exports.csv;

export function buildReport(res: ExposureResponse, extras: Record<string, unknown> = {}): Record<string, unknown> {
  return { ...res.exports.report, ...extras };
}

export function exportFileName(res: ExposureResponse, ext: 'geojson' | 'csv' | 'json'): string {
  const who = (res.analysis.municipality ?? 'custom-area').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  const date = res.analysis.event_date ?? res.analysis.generated_at.slice(0, 10);
  return `landai-exposure-${who}-${date}.${ext}`;
}

export function download(name: string, content: string, mime: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: mime }));
  const a = document.createElement('a');
  a.href = url; a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Warning text by code with the server message as fallback (see i18n keys `exposure.warn.*`). */
export const warningKey = (code: string) => `exposure.warn.${code}`;
