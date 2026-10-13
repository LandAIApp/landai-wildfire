import type { PublicConfig } from '../types/api';

/**
 * Used ONLY until GET /api/v1/config answers (or when the backend is unreachable / older).
 * The backend values are authoritative: the UI never enforces these numbers on its own once it has them.
 */
export const DEFAULT_CONFIG: PublicConfig = {
  status: 'default',
  version: 'unknown',
  aoi: {
    municipality: { max_hectares: 500_000, warn_hectares: 100_000 },
    custom: { max_hectares: 100_000, warn_hectares: 50_000, min_hectares: 10, max_vertices: 300 },
    min_fire_date: '2018-08-01',
  },
  exposure: {
    max_aoi_hectares: 50_000, default_buffer_m: 500, max_buffer_m: 2000, max_layer_features: 5000,
    thresholds: [0.35, 0.5, 0.6, 0.72, 0.85], default_threshold: 0.72, population_year: 2020,
    population_resolution: '100m',
  },
  rate_limits: { analyze: [{ count: 5, per: 'HOUR' }], exposure: [{ count: 10, per: 'HOUR' }], enabled: true },
  sources: {},
};

/** Merge a (possibly partial / older) backend answer over the defaults. */
export function mergeConfig(remote: Partial<PublicConfig> | null | undefined): PublicConfig {
  if (!remote || typeof remote !== 'object' || !remote.aoi) return DEFAULT_CONFIG;
  return {
    ...DEFAULT_CONFIG, ...remote,
    aoi: { ...DEFAULT_CONFIG.aoi, ...remote.aoi,
      custom: { ...DEFAULT_CONFIG.aoi.custom, ...remote.aoi.custom },
      municipality: { ...DEFAULT_CONFIG.aoi.municipality, ...remote.aoi.municipality } },
    exposure: { ...DEFAULT_CONFIG.exposure, ...(remote.exposure ?? {}) },
    rate_limits: { ...DEFAULT_CONFIG.rate_limits, ...(remote.rate_limits ?? {}) },
  };
}
