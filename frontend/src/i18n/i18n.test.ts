import { describe, expect, it } from 'vitest';
import {
  DEFAULT_LANGUAGE, STORAGE_KEY, interpolate, persistLanguage, resolveInitialLanguage,
  translate, translateOptional,
} from './index';
import { en, es } from './translations';

describe('language persistence', () => {
  it('defaults to Spanish when nothing is stored', () => {
    expect(DEFAULT_LANGUAGE).toBe('es');
    expect(resolveInitialLanguage(null)).toBe('es');
    expect(resolveInitialLanguage(undefined)).toBe('es');
    expect(resolveInitialLanguage({ getItem: () => null })).toBe('es');
  });
  it('restores a saved language', () => {
    expect(resolveInitialLanguage({ getItem: (k) => (k === STORAGE_KEY ? 'en' : null) })).toBe('en');
  });
  it('ignores invalid stored values and blocked storage', () => {
    expect(resolveInitialLanguage({ getItem: () => 'fr' })).toBe('es');
    expect(resolveInitialLanguage({ getItem: () => { throw new Error('blocked'); } })).toBe('es');
  });
  it('writes the language under the landai.lang key', () => {
    const saved: Record<string, string> = {};
    persistLanguage('en', { setItem: (k, v) => { saved[k] = v; } });
    expect(saved).toEqual({ 'landai.lang': 'en' });
    expect(() => persistLanguage('es', { setItem: () => { throw new Error('x'); } })).not.toThrow();
  });
});

describe('dictionary integrity', () => {
  const esKeys = Object.keys(es).sort();
  const enKeys = Object.keys(en).sort();

  it('Spanish and English define exactly the same keys', () => {
    expect(enKeys).toEqual(esKeys);
  });
  it('has no empty strings', () => {
    for (const [k, v] of Object.entries(es)) expect(v.trim(), `es ${k}`).not.toBe('');
    for (const [k, v] of Object.entries(en)) expect(v.trim(), `en ${k}`).not.toBe('');
  });
  it('uses the same {placeholders} in both languages', () => {
    const names = (s: string) => (s.match(/\{\w+\}/g) ?? []).sort();
    for (const k of esKeys) {
      expect(names(en[k as keyof typeof en]), k).toEqual(names(es[k as keyof typeof es]));
    }
  });
  it('translates every analytical layer id returned by the backend', () => {
    const ids = ['post', 'pre', 'dnbr', 'spectral_evidence', 'wildfire_likelihood', 'burn_050',
      'burn_072', 'viirs', 'agriculture_score', 'observation_quality', 'burn_035', 'burn_060', 'burn_085'];
    for (const id of ids) {
      for (const lang of ['es', 'en'] as const) {
        expect(translateOptional(lang, `layers.${id}.label`), `${lang} ${id} label`).toBeTruthy();
        expect(translateOptional(lang, `layers.${id}.desc`), `${lang} ${id} desc`).toBeTruthy();
      }
    }
  });
  it('translates every result threshold, issue code and error code', () => {
    const keys = [
      ...['wf035', 'wf050', 'wf060', 'wf072', 'wf085'].map((k) => `results.${k}`),
      ...['future_date', 'date_too_early', 'invalid_dates', 'municipality_not_found', 'aoi_too_large',
        'aoi_large', 'no_pre_images', 'no_post_images', 'insufficient_history', 'few_scenes',
        'long_window', 'few_positive_samples', 'no_area_detected', 'layer_unavailable']
        .map((c) => `issues.${c}`),
      ...['invalid_request', 'department_not_found', 'municipality_not_found', 'preflight_failed',
        'no_training_samples', 'earth_engine_not_available', 'earth_engine_error',
        'earth_engine_timeout', 'earth_engine_computation_limit', 'earth_engine_quota',
        'tile_generation_failed', 'internal_error', 'network_error', 'client_timeout']
        .map((c) => `errors.${c}`),
    ];
    for (const k of keys) {
      expect(translateOptional('es', k), `es ${k}`).toBeTruthy();
      expect(translateOptional('en', k), `en ${k}`).toBeTruthy();
    }
  });
});

describe('translate', () => {
  it('returns language-specific text', () => {
    expect(translate('es', 'controls.analyze')).toBe('Analizar incendio');
    expect(translate('en', 'controls.analyze')).toBe('Analyze Wildfire');
    expect(translate('es', 'controls.example')).toBe('Cargar ejemplo');
    expect(translate('en', 'controls.example')).toBe('Try example');
  });
  it('interpolates params and keeps unknown placeholders', () => {
    expect(interpolate('Hola {name}', { name: 'Ana' })).toBe('Hola Ana');
    expect(interpolate('Hola {name}', {})).toBe('Hola {name}');
    expect(translate('en', 'layers.opacity', { name: 'POST' })).toBe('POST opacity');
  });
  it('returns undefined for unknown dynamic keys', () => {
    expect(translateOptional('es', 'layers.nope.label')).toBeUndefined();
  });
  it('keeps the scientific disclaimer in both languages', () => {
    expect(translate('en', 'disclaimer.text')).toContain('not an officially validated wildfire perimeter');
    expect(translate('es', 'disclaimer.text')).toContain('no es un perímetro oficial de incendio validado');
  });
});
