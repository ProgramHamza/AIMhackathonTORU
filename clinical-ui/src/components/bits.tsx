import { Fragment } from 'react'
import { bundle } from '../mock'
import { useI18n } from '../lang'
import type { Source } from '../types'

/** Renders `**bold**` markers as bold text. */
export function Rich({ text }: { text: string }) {
  const parts = text.split(/\*\*(.+?)\*\*/g)
  return (
    <>
      {parts.map((p, i) =>
        i % 2 === 1 ? (
          <strong key={i}>{p}</strong>
        ) : (
          <Fragment key={i}>{p}</Fragment>
        ),
      )}
    </>
  )
}

export function SourceLink({ source, onOpen }: { source: Source; onOpen: (s: Source) => void }) {
  const { t } = useI18n()
  const doc = bundle.documents.find((d) => d.id === source.doc)
  if (!doc) return null
  return (
    <button type="button" className="src" onClick={() => onOpen(source)}>
      {t(doc.short)}
    </button>
  )
}

export function SourceList({ sources, onOpen }: { sources: Source[]; onOpen: (s: Source) => void }) {
  return (
    <>
      {sources.map((s, i) => (
        <Fragment key={`${s.doc}-${s.para}`}>
          {i > 0 && <span className="opacity-60">, </span>}
          <SourceLink source={s} onOpen={onOpen} />
        </Fragment>
      ))}
    </>
  )
}

export function LangSwitch({ className = '' }: { className?: string }) {
  const { lang, setLang, s } = useI18n()
  const item = (code: 'en' | 'de', label: string) => (
    <button
      type="button"
      onClick={() => setLang(code)}
      aria-pressed={lang === code}
      className={`px-1 ${lang === code ? 'font-bold underline underline-offset-4' : 'opacity-60 hover:opacity-100'}`}
    >
      {label}
    </button>
  )
  return (
    <div className={`fixed right-4 top-3 z-30 flex ${className}`} role="group" aria-label={s.language}>
      {item('en', 'EN')}
      <span className="opacity-40">|</span>
      {item('de', 'DE')}
    </div>
  )
}
