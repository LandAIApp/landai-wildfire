import { describe, expect, it } from 'vitest';
import { layerDescription, layerLabel, splitLayers, MAIN_LAYER_IDS } from './layers';
import type { LayerInfo } from '../types/api';

export const ALL_IDS = ['post', 'pre', 'dnbr', 'spectral_evidence', 'wildfire_likelihood', 'burn_050',
  'burn_072', 'viirs', 'agriculture_score', 'observation_quality', 'burn_035', 'burn_060', 'burn_085'];

export const stubLayers = (ids: string[] = ALL_IDS): LayerInfo[] => ids.map((id) => ({
  id, label: `server ${id}`, group: 'x', description: 'server desc', tile_url: `https://t/${id}/{z}/{x}/{y}`,
  visible_by_default: id === 'post' || id === 'burn_050', legend: null,
}));

describe('splitLayers', () => {
  it('puts POST, Burn 0.50, Burn 0.72 and VIIRS in the main group', () => {
    const { main } = splitLayers(stubLayers());
    expect(main.map((l) => l.id)).toEqual(['post', 'burn_050', 'burn_072', 'viirs']);
    expect([...MAIN_LAYER_IDS]).toEqual(['post', 'burn_050', 'burn_072', 'viirs']);
  });
  it('keeps every other layer in advanced and drops nothing', () => {
    const { main, advanced } = splitLayers(stubLayers());
    expect(advanced.map((l) => l.id).sort()).toEqual(
      ['pre', 'dnbr', 'spectral_evidence', 'wildfire_likelihood', 'agriculture_score',
        'observation_quality', 'burn_035', 'burn_060', 'burn_085'].sort());
    expect(main.length + advanced.length).toBe(ALL_IDS.length);
  });
  it('sends unknown future layers to advanced', () => {
    expect(splitLayers(stubLayers(['post', 'new_layer'])).advanced.map((l) => l.id)).toEqual(['new_layer']);
  });
});

describe('layer text', () => {
  const [post] = stubLayers(['post']);
  it('is localized by layer id', () => {
    expect(layerLabel('es', post)).toBe('Imagen POST (posterior)');
    expect(layerLabel('en', post)).toBe('POST image');
    expect(layerDescription('es', post)).toContain('posterior al incendio');
  });
  it('falls back to the server text for unknown ids', () => {
    const [x] = stubLayers(['mystery']);
    expect(layerLabel('es', x)).toBe('server mystery');
    expect(layerDescription('en', x)).toBe('server desc');
  });
});
