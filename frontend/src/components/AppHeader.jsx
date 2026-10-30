import { LANGS, useLang } from '../lib/i18n';

function LangSwitch() {
  const { lang, setLang, busy, t } = useLang();
  return (
    <div className="lang-switch" role="group" aria-label={t('language')} aria-busy={busy}>
      {LANGS.map((code) => (
        <button key={code} type="button" lang={code} aria-pressed={lang === code} onClick={() => setLang(code)}>
          {code.toUpperCase()}
        </button>
      ))}
      {busy && <span className="lang-switch-busy" role="status" aria-label={t('translating')} />}
    </div>
  );
}

export function AppHeader({ clinician, task, role = task?.role, onNewSearch }) {
  const { t } = useLang();
  return (
    <header className="relative z-30 flex h-12 shrink-0 items-center justify-between gap-6 border-b-2 border-rule-strong bg-canvas px-5">
      <div className="flex min-w-0 items-baseline gap-2">
        <span className="eyebrow">{t('loggedIn')}</span>
        <span className="truncate text-meta font-semibold text-ink">{clinician.name}</span>
        {role && <span className="label hidden truncate sm:inline">· {role}</span>}
      </div>
      <div className="flex shrink-0 items-center gap-5">
        {onNewSearch && (
          <button type="button" onClick={onNewSearch} className="text-meta text-muted hover:text-ink">
            {t('newSearch')}
          </button>
        )}
        <LangSwitch />
      </div>
    </header>
  );
}
