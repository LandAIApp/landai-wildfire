import { useI18n } from '../i18n/LanguageContext';
import { LANGUAGES } from '../i18n';

export default function LanguageSwitch() {
  const { lang, setLang, t } = useI18n();
  return (
    <div className="lang-switch" role="group" aria-label={t('header.language')}>
      {LANGUAGES.map((code) => (
        <button key={code} type="button" className={code === lang ? 'active' : ''}
                aria-pressed={code === lang} onClick={() => setLang(code)}>
          {code.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
