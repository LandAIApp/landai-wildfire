import { localeOf, translate, type Language } from '../i18n';

export function formatNumber(value: number, lang: Language): string {
  return Math.round(value).toLocaleString(localeOf(lang));
}

export function formatHectares(value: number | null | undefined, lang: Language = 'es'): string {
  if (value === null || value === undefined || Number.isNaN(value)) return translate(lang, 'results.noData');
  return `${formatNumber(value, lang)} ha`;
}

/** Hectares with one decimal below 100 ha so small drawn areas do not all read "0 ha". */
export function formatArea(value: number, lang: Language): string {
  const digits = value < 100 ? 1 : 0;
  return `${value.toLocaleString(localeOf(lang), { maximumFractionDigits: digits, minimumFractionDigits: digits })} ha`;
}

/** Square kilometres (1 km² = 100 ha), two decimals below 10 km². */
export function formatKm2(hectares: number, lang: Language): string {
  const km2 = hectares / 100;
  const digits = km2 < 10 ? 2 : km2 < 100 ? 1 : 0;
  return `${km2.toLocaleString(localeOf(lang), { maximumFractionDigits: digits, minimumFractionDigits: digits })} km²`;
}

export function formatDecimal(value: number, lang: Language, digits = 1): string {
  return value.toLocaleString(localeOf(lang), { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

export function formatDateTime(iso: string, lang: Language): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(localeOf(lang));
}
