import { useI18n } from '../i18n/LanguageContext';
import { describeIssue } from '../services/issues';
import type { PreflightResponse } from '../types/api';

export type Busy = 'catalog' | 'preflight' | 'analysis' | null;
export type StatusKind = 'idle' | 'info' | 'success' | 'warning' | 'error';
export interface Status { kind: StatusKind; text: string }

interface Props {
  departments: string[];
  municipalities: string[];
  department: string;
  municipality: string;
  fireDate: string;
  endDate: string;
  minDate: string;
  maxDate: string;
  busy: Busy;
  elapsed: number;
  status: Status;
  preflight: PreflightResponse | null;
  counts: { pre: number | null; post: number | null; history: number | null };
  onDepartment: (v: string) => void;
  onMunicipality: (v: string) => void;
  onFireDate: (v: string) => void;
  onEndDate: (v: string) => void;
  onExample: () => void;
  onCheck: () => void;
  onAnalyze: () => void;
}

const fmt = (n: number | null) => (n === null ? '—' : String(n));

export default function ControlPanel(p: Props) {
  const { lang, t } = useI18n();
  const disabled = p.busy !== null;
  const ready = !!p.department && !!p.municipality && !!p.fireDate && !!p.endDate;
  const datesOk = !p.fireDate || !p.endDate || p.endDate >= p.fireDate;
  const issueCtx = { department: p.department, municipality: p.municipality, aoiHectares: p.preflight?.aoi_hectares };

  return (
    <section className="card">
      <div className="card-head">
        <h2>{t('controls.title')}</h2>
        <button type="button" className="btn-link" onClick={p.onExample} disabled={disabled}>
          {t('controls.example')}
        </button>
      </div>
      <div className="demo-note">
        {t('controls.exampleNote')}
      </div>

      <label htmlFor="department">{t('controls.department')}</label>
      <select id="department" value={p.department} disabled={disabled || p.departments.length === 0}
              onChange={(e) => p.onDepartment(e.target.value)}>
        <option value="">
          {p.busy === 'catalog' && !p.departments.length ? t('controls.loading') : t('controls.selectDepartment')}
        </option>
        {p.departments.map((d) => <option key={d} value={d}>{d}</option>)}
      </select>

      <label htmlFor="municipality">{t('controls.municipality')}</label>
      <select id="municipality" value={p.municipality} disabled={disabled || p.municipalities.length === 0}
              onChange={(e) => p.onMunicipality(e.target.value)}>
        <option value="">{t('controls.selectMunicipality')}</option>
        {p.municipalities.map((m) => <option key={m} value={m}>{m}</option>)}
      </select>

      <label htmlFor="fire-date">{t('controls.fireDate')}</label>
      <input id="fire-date" type="date" value={p.fireDate} min={p.minDate} max={p.maxDate} disabled={disabled}
             onChange={(e) => p.onFireDate(e.target.value)} />

      <label htmlFor="end-date">{t('controls.endDate')}</label>
      <input id="end-date" type="date" value={p.endDate} min={p.fireDate || p.minDate} max={p.maxDate}
             disabled={disabled} onChange={(e) => p.onEndDate(e.target.value)} />
      {!datesOk && <div className="hint error-text">{t('controls.dateOrderError')}</div>}

      <div className="button-row">
        <button className="btn secondary" onClick={p.onCheck} disabled={disabled || !ready || !datesOk}>
          {p.busy === 'preflight' ? t('controls.checking') : t('controls.check')}
        </button>
        <button className="btn primary" onClick={p.onAnalyze} disabled={disabled || !ready || !datesOk}>
          {p.busy === 'analysis' ? t('controls.analyzing') : t('controls.analyze')}
        </button>
      </div>

      <div className={`status ${p.status.kind}`} role="status" aria-live="polite">
        {p.busy === 'analysis' && <span className="spinner" aria-hidden />}
        <span>{p.status.text}</span>
        {p.busy === 'analysis' && <span className="elapsed"> ({p.elapsed}s)</span>}
      </div>

      <div className="counts">
        <div><strong>{fmt(p.counts.pre)}</strong><span>{t('counts.pre')}</span></div>
        <div><strong>{fmt(p.counts.post)}</strong><span>{t('counts.post')}</span></div>
        <div><strong>{fmt(p.counts.history)}</strong><span>{t('counts.history')}</span></div>
      </div>

      {p.preflight?.date_windows && (
        <div className="windows">
          <div>{t('windows.pre')}: {p.preflight.date_windows.pre.start} → {p.preflight.date_windows.pre.end}</div>
          <div>{t('windows.post')}: {p.preflight.date_windows.post.start} → {p.preflight.date_windows.post.end}</div>
          <div>{t('windows.history')}: {p.preflight.date_windows.history.start} → {p.preflight.date_windows.history.end}</div>
        </div>
      )}

      {p.preflight?.blocking_errors.map((e) => (
        <div key={e.code} className="alert error">{describeIssue(lang, e, issueCtx)}</div>
      ))}
      {p.preflight?.warnings.map((w) => (
        <div key={w.code} className="alert warning">{describeIssue(lang, w, issueCtx)}</div>
      ))}
    </section>
  );
}
