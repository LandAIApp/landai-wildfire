import { useI18n } from '../i18n/LanguageContext';
import type { ProgressSnapshot, StageState } from '../types/api';

const ICON: Record<StageState, string> = {
  pending: '○', running: '', done: '✓', cached: '✓', skipped: '–', failed: '✕',
};

/** Real stages reported by the backend. No percentage and no ETA: a stage is only pending, running, done, ... */
export default function ProgressList({ snapshot, kind }: { snapshot: ProgressSnapshot | null; kind: 'analysis' | 'exposure' }) {
  const { t, tOptional } = useI18n();
  if (!snapshot || snapshot.stages.length === 0) return null;
  return (
    <div className="progress-box" data-testid={`progress-${kind}`}>
      <ul className="progress-list">
        {snapshot.stages.map((s) => {
          const label = tOptional(`progress.${kind}.${s.key}`) ?? s.key;
          const cells = s.detail.cells_total ? ` ${s.detail.cells_done ?? 0}/${s.detail.cells_total}` : '';
          return (
            <li key={s.key} className={`stage ${s.state}`}>
              <span className="stage-icon" aria-hidden>
                {s.state === 'running' ? <span className="spinner" /> : ICON[s.state]}
              </span>
              <span className="stage-label">{label}{cells && <small>{cells}</small>}</span>
              <span className="stage-state">
                {t(`progress.state.${s.state}` as 'progress.state.done')}
                {s.seconds != null && s.state !== 'pending' && s.state !== 'skipped' ? ` · ${Math.round(s.seconds)} s` : ''}
              </span>
            </li>
          );
        })}
      </ul>
      <p className="muted small">{t('progress.note')}</p>
    </div>
  );
}
