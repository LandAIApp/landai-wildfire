import { useI18n } from '../i18n/LanguageContext';
import type { AnalyzeResponse } from '../types/api';

const ITEMS = ['pre', 'post', 'history', 'likelihood', 'areas', 'tiles'] as const;

export default function Methodology({ result }: { result: AnalyzeResponse | null }) {
  const { t } = useI18n();
  return (
    <details className="card methodology">
      <summary>{t('method.title')}</summary>
      <p>{t('method.intro')}</p>
      <ul>
        {ITEMS.map((id) => (
          <li key={id}><b>{t(`method.${id}.label`)}</b>: {t(`method.${id}.text`)}</li>
        ))}
      </ul>
      {result && (
        <p className="small muted">
          {t('method.model', {
            model: result.metadata.model_version,
            pos: result.training.positive_samples,
            neg: result.training.negative_samples,
          })}{' '}
          {t(result.metadata.equivalence_validated ? 'method.equiv.yes' : 'method.equiv.no')}
        </p>
      )}
    </details>
  );
}
