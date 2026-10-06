import { useI18n } from '../i18n/LanguageContext';
import { formatHectares } from '../services/format';
import { describeIssue } from '../services/issues';
import type { AnalyzeResponse } from '../types/api';

/** Contact destination for the commercial call to action (set VITE_LANDAI_CONTACT_URL). */
const CONTACT_URL = ((import.meta.env.VITE_LANDAI_CONTACT_URL as string | undefined) ?? '').trim();

export default function ResultsPanel({ result }: { result: AnalyzeResponse | null }) {
  const { lang, t, tOptional } = useI18n();
  const probable = result?.area_hectares.find((a) => a.key === 'wf050');
  const high = result?.area_hectares.find((a) => a.key === 'wf072');
  const ctx = result
    ? { aoiHectares: result.metadata.aoi_hectares, positiveSamples: result.training.positive_samples }
    : {};

  return (
    <section className="card">
      <h2>{t('results.title')}</h2>
      {!result && <p className="muted">{t('results.empty')}</p>}
      {result && (
        <>
          <p className="muted small">
            {result.metadata.municipality}, {result.metadata.department} ·{' '}
            {result.metadata.fire_date} → {result.metadata.analysis_end}
          </p>
          <div className="headline-results">
            <div>
              <span>{t('results.probable')}</span>
              <strong>{probable ? formatHectares(probable.hectares, lang) : '—'}</strong>
            </div>

            <div>
              <span>{t('results.highConfidence')}</span>
              <strong>{high ? formatHectares(high.hectares, lang) : '—'}</strong>
            </div>
          </div>
          <div className="result-summary">
            <div>
              <span>{t('results.about.model')}</span>
              <strong>{result.metadata.model_version}</strong>
            </div>

            <div>
              <span>{t('results.about.data')}</span>
              <strong>Sentinel-2 + VIIRS</strong>
            </div>

            <div>
              <span>{t('results.about.images')}</span>
              <strong>
                {result.image_counts.pre} PRE · {result.image_counts.post} POST
              </strong>
            </div>

            <div>
              <span>{t('results.about.resolution')}</span>
              <strong>20 m</strong>
            </div>
          </div>
          <table className="results">
            <thead>
              <tr>
                <th>{t('results.colConfidence')}</th>
                <th>{t('results.colThreshold')}</th>
                <th className="num">{t('results.colArea')}</th>
              </tr>
            </thead>
            <tbody>
              {result.area_hectares.map((a) => (
                <tr key={a.key} className={a.key === 'wf050' ? 'highlight' : ''}>
                  <td>{tOptional(`results.${a.key}`) ?? a.label}</td>
                  <td>{`≥ ${a.threshold.toFixed(2)}`}</td>
                  <td className="num">{formatHectares(a.hectares, lang)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {result.warnings.map((w, i) => (
            <div key={i} className="alert warning">{describeIssue(lang, w, ctx)}</div>
          ))}
          <div className="cta">
            <p>{t('results.cta.text')}</p>
            {CONTACT_URL && (
              <a className="cta-link" href={CONTACT_URL} target="_blank" rel="noopener noreferrer">
                {t('results.cta.link')}
              </a>
            )}
          </div>
        </>
      )}
      <p className="disclaimer">{t('disclaimer.text')}</p>
    </section>
  );
}
