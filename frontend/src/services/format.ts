import { localeOf, translate, type Language } from '../i18n';

export function formatNumber(value: number, lang: Language): string {
  return Math.round(value).toLocaleString(localeOf(lang));
}

export function formatHectares(value: number | null | undefined, lang: Language = 'es'): string {
  if (value === null || value === undefined || Number.isNaN(value)) return translate(lang, 'results.noData');
  return `${formatNumber(value, lang)} ha`;
}
