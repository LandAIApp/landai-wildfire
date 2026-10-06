import { translateOptional, type Language } from '../i18n';
import type { LayerInfo } from '../types/api';

/** Layers shown by default in the "Main" group. Every other layer is "Advanced". */
export const MAIN_LAYER_IDS: readonly string[] = ['post', 'burn_050', 'burn_072', 'viirs'];

export function splitLayers(layers: LayerInfo[]): { main: LayerInfo[]; advanced: LayerInfo[] } {
  return {
    main: layers.filter((l) => MAIN_LAYER_IDS.includes(l.id)),
    advanced: layers.filter((l) => !MAIN_LAYER_IDS.includes(l.id)),
  };
}

/** Localized name; falls back to the server label for unknown layer ids. */
export function layerLabel(lang: Language, layer: LayerInfo): string {
  return translateOptional(lang, `layers.${layer.id}.label`) ?? layer.label;
}

export function layerDescription(lang: Language, layer: LayerInfo): string {
  return translateOptional(lang, `layers.${layer.id}.desc`) ?? layer.description;
}
