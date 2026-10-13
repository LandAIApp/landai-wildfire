import { translate, translateOptional, type Language, type Params } from '../i18n';
import { formatNumber } from './format';
import type { Issue } from '../types/api';

export interface IssueContext {
  department?: string;
  municipality?: string;
  aoiHectares?: number | null;
  positiveSamples?: number | null;
  /** Fallback limit when the issue carries no `max` (municipality issues). */
  maxHectares?: number | null;
}

/** Translate an API warning/blocking issue by its `code`; fall back to the server message. */
export function describeIssue(lang: Language, issue: Issue, ctx: IssueContext = {}): string {
  const params: Params = {
    department: ctx.department ?? '',
    municipality: ctx.municipality ?? '',
    hectares: ctx.aoiHectares != null ? formatNumber(ctx.aoiHectares, lang) : '',
    n: ctx.positiveSamples ?? '',
    max: ctx.maxHectares != null ? formatNumber(ctx.maxHectares, lang) : '',
  };
  // Parameters sent by the API (drawn-area issues) win over the context.
  for (const [key, value] of Object.entries(issue.params ?? {})) {
    params[key] = typeof value === 'number' && ['hectares', 'max', 'min'].includes(key)
      ? formatNumber(value, lang) : value;
  }
  return translateOptional(lang, `issues.${issue.code}`, params) ?? issue.message;
}

interface ErrorLike { code?: unknown; message?: unknown; details?: unknown }

/** Translate an API/network error by its technical `code` (the code itself is never altered). */
export function describeError(lang: Language, error: unknown, apiBase: string): string {
  const e: ErrorLike = typeof error === 'object' && error !== null ? (error as ErrorLike) : {};
  const code = typeof e.code === 'string' ? e.code : '';
  const fallback = typeof e.message === 'string' && e.message ? e.message : translate(lang, 'errors.unknown');

  let text: string | undefined;
  if (code.startsWith('http_')) {
    text = translate(lang, 'errors.http', { status: code.slice(5) });
  } else if (code) {
    text = translateOptional(lang, `errors.${code}`, { base: apiBase });
  }
  text = text ?? fallback;

  if (code === 'preflight_failed' && Array.isArray(e.details)) {
    const extra = (e.details as Issue[])
      .filter((d) => d && typeof d.code === 'string')
      .map((d) => describeIssue(lang, d));
    if (extra.length) text = `${extra.join(' ')}`;
  }
  if (code === 'rate_limit_exceeded' && e.details && typeof e.details === 'object') {
    const seconds = Number((e.details as { retry_after_seconds?: unknown }).retry_after_seconds);
    if (Number.isFinite(seconds) && seconds > 0) {
      text = `${text} ${translate(lang, 'errors.retryAfter', { minutes: Math.max(1, Math.ceil(seconds / 60)) })}`;
    }
  }
  return text;
}
