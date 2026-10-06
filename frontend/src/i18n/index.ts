import { en, es, type MessageKey } from './translations';

export type { MessageKey };
export type Language = 'es' | 'en';
export type Params = Record<string, string | number>;

export const LANGUAGES: readonly Language[] = ['es', 'en'];
export const DEFAULT_LANGUAGE: Language = 'es';
export const STORAGE_KEY = 'landai.lang';

const dictionaries: Record<Language, Record<string, string>> = { es, en };

export function isLanguage(value: unknown): value is Language {
  return value === 'es' || value === 'en';
}

/** Language saved in storage, or Spanish (default) when absent/invalid/unavailable. */
export function resolveInitialLanguage(storage?: Pick<Storage, 'getItem'> | null): Language {
  try {
    const saved = storage?.getItem(STORAGE_KEY);
    if (isLanguage(saved)) return saved;
  } catch { /* storage blocked (private mode, SSR) */ }
  return DEFAULT_LANGUAGE;
}

export function persistLanguage(lang: Language, storage?: Pick<Storage, 'setItem'> | null): void {
  try { storage?.setItem(STORAGE_KEY, lang); } catch { /* ignore */ }
}

export function interpolate(template: string, params?: Params): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    name in params ? String(params[name]) : match);
}

/** Translate a known key. */
export function translate(lang: Language, key: MessageKey, params?: Params): string {
  return interpolate(dictionaries[lang][key] ?? dictionaries[DEFAULT_LANGUAGE][key], params);
}

/** Translate a dynamic key; returns undefined when the key does not exist. */
export function translateOptional(lang: Language, key: string, params?: Params): string | undefined {
  const template = dictionaries[lang][key];
  return template === undefined ? undefined : interpolate(template, params);
}

export function localeOf(lang: Language): string {
  return lang === 'es' ? 'es-CO' : 'en-US';
}
