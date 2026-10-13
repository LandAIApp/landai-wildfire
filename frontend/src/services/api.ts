import type {
  AnalyzeResponse, ApiErrorBody, ExposureRequest, ExposureResponse, PreflightResponse, PublicConfig,
  ProgressSnapshot, RecordedDemo, WildfireRequest,
} from '../types/api';

export const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://localhost:8000';

export class ApiError extends Error {
  code: string;
  details?: unknown;
  constructor(message: string, code: string, details?: unknown) {
    super(message);
    this.code = code;
    this.details = details;
  }
}

async function request<T>(path: string, init?: RequestInit, timeoutMs = 30_000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE}${path}`, { ...init, signal: controller.signal });
    const text = await res.text();
    let body: unknown = null;
    try { body = text ? JSON.parse(text) : null; } catch { /* non-JSON body */ }
    if (!res.ok) {
      const err = body as Partial<ApiErrorBody> | null;
      throw new ApiError(
        err?.message ?? `The server responded with an error (HTTP ${res.status}).`,
        err?.code ?? `http_${res.status}`,
        err?.details,
      );
    }
    return body as T;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    if (e instanceof DOMException && e.name === 'AbortError') {
      throw new ApiError('The request took too long and was cancelled. Try a smaller area or period.', 'client_timeout');
    }
    throw new ApiError(
      `Cannot reach the analysis server at ${API_BASE}. Is the backend running?`, 'network_error');
  } finally {
    clearTimeout(timer);
  }
}

const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

export const api = {
  config: () => request<PublicConfig>('/api/v1/config', undefined, 20_000),
  /** Exposure & Impact (explicit user action). Re-runs the validated graph server-side: allow minutes. */
  exposure: (body: ExposureRequest) =>
    request<ExposureResponse>('/api/v1/exposure/analyze', json(body), 20 * 60_000),
  /** Real processing stages of a running request (404 = this server instance knows nothing about it). */
  progress: (id: string) =>
    request<ProgressSnapshot>(`/api/v1/progress/${encodeURIComponent(id)}`, undefined, 10_000),
  /** Optional recorded demo shipped with the static site (absent unless recorded). */
  recordedDemo: async (): Promise<RecordedDemo | null> => {
    const base = (import.meta.env.BASE_URL as string | undefined) ?? '/';
    try {
      const res = await fetch(`${base}demo/exposure-demo.json`, { cache: 'no-cache' });
      if (!res.ok || !(res.headers.get('content-type') ?? '').includes('json')) return null;
      const data = (await res.json()) as RecordedDemo;
      return data?.recorded === true && data.recorded_from_live_services === true ? data : null;
    } catch { return null; }
  },
  departments: () =>
    request<{ departments: string[] }>('/api/v1/administrative/departments', undefined, 120_000),
  municipalities: (department: string) =>
    request<{ municipalities: string[] }>(
      `/api/v1/administrative/municipalities?department=${encodeURIComponent(department)}`,
      undefined, 120_000),
  preflight: (body: WildfireRequest) =>
    request<PreflightResponse>('/api/v1/wildfire/preflight', json(body), 180_000),
  // Analysis can take several minutes on Earth Engine.
  analyze: (body: WildfireRequest) =>
    request<AnalyzeResponse>('/api/v1/wildfire/analyze', json(body), 15 * 60_000),
};
