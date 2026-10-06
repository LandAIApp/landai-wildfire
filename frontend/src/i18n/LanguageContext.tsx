import {
  createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode,
} from 'react';
import {
  localeOf, persistLanguage, resolveInitialLanguage, translate, translateOptional,
  type Language, type MessageKey, type Params,
} from './index';

interface I18nValue {
  lang: Language;
  locale: string;
  setLang: (lang: Language) => void;
  t: (key: MessageKey, params?: Params) => string;
  tOptional: (key: string, params?: Params) => string | undefined;
}

const LanguageContext = createContext<I18nValue | null>(null);

function browserStorage(): Storage | null {
  try { return typeof window === 'undefined' ? null : window.localStorage; } catch { return null; }
}

export function LanguageProvider({ children, initial }: { children: ReactNode; initial?: Language }) {
  const [lang, setLang] = useState<Language>(() => initial ?? resolveInitialLanguage(browserStorage()));

  useEffect(() => {
    document.documentElement.lang = lang;
    persistLanguage(lang, browserStorage());
  }, [lang]);

  const t = useCallback((key: MessageKey, params?: Params) => translate(lang, key, params), [lang]);
  const tOptional = useCallback((key: string, params?: Params) => translateOptional(lang, key, params), [lang]);
  const value = useMemo<I18nValue>(
    () => ({ lang, locale: localeOf(lang), setLang, t, tOptional }),
    [lang, t, tOptional],
  );
  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useI18n(): I18nValue {
  const ctx = useContext(LanguageContext);
  if (!ctx) throw new Error('useI18n must be used inside <LanguageProvider>');
  return ctx;
}
