import type { ReactNode } from 'react'
import { bundle, departmentOptions } from '../mock'
import { useI18n } from '../lang'
import type { Situation, Source } from '../types'
import { SourceLink } from './bits'

type Props = {
  situation: Situation
  activeConflict: string | null
  setActiveConflict: (id: string | null) => void
  onOpen: (s: Source) => void
  onChange: () => void
}

function Flag({ id, active, set }: { id: string; active: string | null; set: (id: string | null) => void }) {
  const { s } = useI18n()
  return (
    <span
      tabIndex={0}
      title={s.contradiction}
      aria-label={s.contradiction}
      onMouseEnter={() => set(id)}
      onMouseLeave={() => set(null)}
      onFocus={() => set(id)}
      onBlur={() => set(null)}
      className={`ml-2 inline-block h-[0.55em] w-[0.55em] bg-bad ${active === id ? 'outline outline-2 outline-offset-2 outline-bad' : ''}`}
    />
  )
}

/** The page is a ledger: the heading sits in the left column, its entries in the right one. */
function Entry({ title, tone = 'cream', children }: { title: string; tone?: 'cream' | 'bad'; children: ReactNode }) {
  return (
    <section
      className={`grid grid-cols-[7.5rem_1fr] gap-x-5 border-t py-3 ${tone === 'bad' ? 'border-bad/60' : 'border-cream/25'}`}
    >
      <h3 className={`font-bold ${tone === 'bad' ? 'text-bad' : ''}`}>{title}</h3>
      <div className="space-y-2.5">{children}</div>
    </section>
  )
}

function Sources({ sources, onOpen }: { sources: Source[]; onOpen: (s: Source) => void }) {
  return (
    <div className="flex flex-wrap gap-x-4 text-cream/70">
      {sources.map((src) => (
        <SourceLink key={`${src.doc}-${src.para}`} source={src} onOpen={onOpen} />
      ))}
    </div>
  )
}

export function Summary({ situation, activeConflict, setActiveConflict, onOpen, onChange }: Props) {
  const { s, t, lang } = useI18n()
  const p = bundle.patient
  const born = new Date(p.born).toLocaleDateString(lang === 'en' ? 'en-GB' : 'de-AT', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })
  const deptNames = situation.departments
    .map((id) => departmentOptions.find((d) => d.id === id))
    .filter((d) => d !== undefined)
    .map((d) => t(d.name))
    .join(', ')

  return (
    <div className="h-full overflow-y-auto px-8 pb-6 pt-7">
      <header>
        <h1 className="font-bold">{p.name}</h1>
        <p className="text-cream/70">
          {p.age} {s.years}, {t(p.sex)}, {s.born} {born}
        </p>
        <dl className="mt-3 grid grid-cols-3 gap-x-4 border-y border-cream/40 py-2">
          <div>
            <dt className="text-cream/70">{s.height}</dt>
            <dd className="font-bold">{p.heightCm} cm</dd>
          </div>
          <div>
            <dt className="text-cream/70">{s.weight}</dt>
            <dd>
              <strong>{p.weightKg} kg</strong>
              <span className="ml-2">
                <SourceLink source={p.weightSource} onOpen={onOpen} />
              </span>
            </dd>
          </div>
          <div>
            <dt className="text-cream/70">{s.bmi}</dt>
            <dd className="font-bold">
              {p.bmi}
              <Flag id={p.bmiConflict} active={activeConflict} set={setActiveConflict} />
            </dd>
          </div>
        </dl>
      </header>

      <section aria-label={s.situationOf} className="mt-4">
        <div className="flex items-baseline justify-between gap-4 text-cream/70">
          <span>
            {s.situationOf}
            {deptNames && `, ${deptNames}`}
          </span>
          <button type="button" onClick={onChange} className="src">
            {s.change}
          </button>
        </div>
        <p className="mt-1 whitespace-pre-wrap">{situation.prompt}</p>
      </section>

      <h2 className="mt-6 border-b-2 border-cream pb-1 font-bold">{s.summary}</h2>

      <div>
        {bundle.groups.map((g) => (
          <Entry key={g.label} title={t(g.title)}>
            {g.facts.map((f) => (
              <div key={f.id}>
                <div>
                  <strong>{t(f.value)}</strong>
                  {f.conflicts?.map((c) => (
                    <Flag key={c} id={c} active={activeConflict} set={setActiveConflict} />
                  ))}
                  {f.detail && <span className="text-cream/80">, {t(f.detail)}</span>}
                </div>
                <Sources sources={f.sources} onOpen={onOpen} />
              </div>
            ))}
          </Entry>
        ))}

        <Entry title={s.notDocumented}>
          <p>{bundle.notDocumented.map((n) => t(n.title)).join(', ')}</p>
        </Entry>

        <Entry title={s.contradictions} tone="bad">
          {bundle.conflicts.length === 0 ? (
            <p className="text-cream/70">{s.noContradictions}</p>
          ) : (
            bundle.conflicts.map((c) => (
              <div
                key={c.id}
                onMouseEnter={() => setActiveConflict(c.id)}
                onMouseLeave={() => setActiveConflict(null)}
                className={`-ml-2 border-l-2 pl-2 ${activeConflict === c.id ? 'border-bad bg-bad/10' : 'border-transparent'}`}
              >
                <div>
                  <strong>{t(c.title)}</strong>
                  <span className="text-cream/80">, {t(c.summary)}</span>
                </div>
                <Sources sources={c.sources} onOpen={onOpen} />
              </div>
            ))
          )}
        </Entry>
      </div>
    </div>
  )
}
