import { useEffect, useRef, useState } from 'react'
import { bundle } from '../mock'
import { useI18n } from '../lang'
import type { Source } from '../types'
import { Rich, SourceLink } from './bits'

type Props = {
  source: Source
  onBack: () => void
  onOpen: (s: Source) => void
}

export function Reader({ source, onBack, onOpen }: Props) {
  const { s, t, date, lang } = useI18n()
  const [original, setOriginal] = useState(false)
  const hlRef = useRef<HTMLDivElement>(null)
  const doc = bundle.documents.find((d) => d.id === source.doc)!

  useEffect(() => {
    hlRef.current?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [source.doc, source.para])

  const showGerman = lang === 'de' || original

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="px-6 pb-3 pt-5 pr-24">
        <button type="button" onClick={onBack} className="src !">
          {s.back}
        </button>
        <h2 className="mt-3 font-bold leading-tight">{t(doc.title)}</h2>
        <p className="mt-1 text-ink/65">
          {date(doc.date)}, {t(doc.department)}
        </p>
        {lang === 'en' && (
          <p className="mt-2 text-ink/60">
            {s.originalNote}{' '}
            <button type="button" className="src" onClick={() => setOriginal((o) => !o)}>
              {original ? s.showTranslation : s.showOriginal}
            </button>
          </p>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-10 pt-1">
        <div className="sheet mx-auto max-w-[760px] px-9 py-8">
          {doc.paragraphs.map((p) => {
            const on = p.id === source.para
            const conflict = bundle.conflicts.find((c) =>
              c.sources.some((x) => x.doc === doc.id && x.para === p.id),
            )
            const others = conflict?.sources.filter((x) => !(x.doc === doc.id && x.para === p.id)) ?? []
            return (
              <div
                key={p.id}
                ref={on ? hlRef : undefined}
                className={`relative -mx-3 mb-3 px-3 py-2 leading-[1.55] ${on ? 'bg-ok/35' : ''} ${conflict ? 'border-l-[3px] border-bad' : ''}`}
              >
                <Rich text={showGerman ? p.text.de : p.text.en} />
                {conflict && (
                  <p className="mt-1 text-ink/70">
                    <span className="font-bold text-bad">{s.contradiction}:</span> {t(conflict.title)}
                    {others.length > 0 && (
                      <>
                        {'. '}
                        {s.seeOther}{' '}
                        {others.map((o, i) => (
                          <span key={`${o.doc}-${o.para}`}>
                            {i > 0 && ', '}
                            <SourceLink source={o} onOpen={onOpen} />
                          </span>
                        ))}
                      </>
                    )}
                  </p>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
