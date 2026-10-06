import { translate, translateOptional, type Language, type Params } from '../i18n';
import { formatNumber } from './format';
import type { Issue } from '../types/api';

export interface IssueContext {
  department?: string;
  municipality?: string;
  aoiHectares?: number | null;
  positiveSamples?: number | null;
}

/** Translate an API warning/blocking issue by its `code`; fall back to the server message. */
export function describeIssue(lang: Language, issue: Issue, ctx: IssueContext = {}): string {
  const params: Params = {
    department: ctx.department ?? '',
    municipality: ctx.municipality ?? '',
    hectares: ctx.aoiHectares != null ? formatNumber(ctx.aoiHectares, lang) : '',
    n: ctx.positiveSamples ?? '',
  };
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
  return text;
}
