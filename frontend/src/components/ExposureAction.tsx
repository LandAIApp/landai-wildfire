import { useI18n } from '../i18n/LanguageContext';
import { formatNumber } from '../services/format';
import type { AnalyzeResponse, PublicConfig } from '../types/api';

interface Props {
  result: AnalyzeResponse;
  config: PublicConfig;
  threshold: number;
  bufferM: number;
  running: boolean;
  disabled: boolean;
  onThreshold: (v: number) => void;
  onBuffer: (v: number) => void;
  onRun: () => void;
  /** The operator paused the module (kill switch). */
  paused?: boolean;
}

const THRESHOLD_KEYS: Record<string, string> = { '0.35': 'wf035', '0.5': 'wf050', '0.6': 'wf060', '0.72': 'wf072', '0.85': 'wf085' };

/** The ONLY place that starts the Exposure analysis: an explicit user action, never automatic. */
export default function ExposureAction(p: Props) {
  const { lang, t, tOptional } = useI18n();
  const hectares = p.result.aoi?.hectares ?? p.result.metadata.aoi_hectares ?? 0;
  const tooLarge = hectares > p.config.exposure.max_aoi_hectares;
  const noRef = !p.result.analysis_ref;
  const blocked = tooLarge || noRef || !!p.paused;
  const perUnit: Record<string, [string, string]> = {
    SECOND: ['s', 's'], MINUTE: ['min', 'min'], HOUR: ['h', 'h'], DAY: ['día', 'day'], MONTH: ['mes', 'month'],
  };
  const rate = p.config.rate_limits.exposure
    .map((r) => `${r.count}/${(perUnit[r.per.toUpperCase()] ?? [r.per, r.per])[lang === 'es' ? 0 : 1]}`).join(' · ');
  const minutes = Math.max(1, Math.round((p.config.service?.cache_ttl_seconds ?? 1800) / 60));

  return (
    <section className="card exposure-action" data-testid="exposure-action">
      <h2>{t('exposure.cta.title')}</h2>
      <p className="muted small">{t('exposure.cta.text')}</p>
      <div className="field-row">
        <div>
          <label htmlFor="exp-threshold">{t('exposure.cta.threshold')}</label>
          <select id="exp-threshold" value={String(p.threshold)} disabled={p.disabled || p.running}
                  onChange={(e) => p.onThreshold(Number(e.target.value))}>
            {p.config.exposure.thresholds.map((v) => (
              <option key={v} value={String(v)}>
                {`≥ ${v.toFixed(2)} · ${tOptional(`results.${THRESHOLD_KEYS[String(v)]}`) ?? ''}`}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="exp-buffer">{t('exposure.cta.buffer')}</label>
          <input id="exp-buffer" type="number" min={0} max={p.config.exposure.max_buffer_m} step={50}
                 value={p.bufferM} disabled={p.disabled || p.running}
                 onChange={(e) => p.onBuffer(Math.max(0, Math.min(p.config.exposure.max_buffer_m, Number(e.target.value) || 0)))} />
        </div>
      </div>
      <button className="btn primary full" onClick={p.onRun} disabled={p.disabled || p.running || blocked}>
        {p.running ? t('exposure.cta.running') : t('exposure.cta.button')}
      </button>
      {tooLarge && (
        <div className="alert warning" role="alert">
          {t('exposure.cta.tooLarge', { hectares: formatNumber(hectares, lang), max: formatNumber(p.config.exposure.max_aoi_hectares, lang) })}
        </div>
      )}
      {!tooLarge && noRef && <div className="alert warning">{t('exposure.cta.noAnalysis')}</div>}
      {p.paused && <div className="alert warning" role="alert">{t('service.exposurePaused')}</div>}
      <p className="muted small">{t('exposure.cta.limit', { max: formatNumber(p.config.exposure.max_aoi_hectares, lang) })}</p>
      <p className="muted small" data-testid="exposure-limitations">{t('exposure.cta.limitations', { rate, minutes })}</p>
    </section>
  );
}
