import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { bundle, defaultSituation, departmentOptions } from './mock'
import { LangProvider, useI18n } from './lang'
import type { LabelId, Situation, Source } from './types'
import { LangSwitch, Rich, SourceLink } from './components/bits'

/**
 * The plain variant, served at /normal: white and grey, one font, one size, no texture.
 * It uses the same data and strings as the paper variant.
 */

const MIN_LEFT = 340
const clampLeft = (px: number) => Math.min(Math.max(px, MIN_LEFT), Math.min(window.innerWidth * 0.55, 780))
const defaultLeft = () => clampLeft(Math.round(window.innerWidth * 0.36))

const input =
  'mt-1 w-full border border-neutral-300 bg-white px-3 py-2 outline-none focus:border-neutral-900'

function Part({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="mt-6 min-w-0 border-0 border-t border-neutral-200 p-0 pt-4">
      <legend className="float-left mb-3 w-full font-bold">{title}</legend>
      <div className="clear-both">{children}</div>
    </fieldset>
  )
}

function PlainLogin({ initial, onSubmit }: { initial: Situation; onSubmit: (s: Situation) => void }) {
  const { s, t } = useI18n()
  const [name, setName] = useState(initial.patientName)
  const [birth, setBirth] = useState(initial.birthNumber)
  const [depts, setDepts] = useState<string[]>(initial.departments)
  const [prompt, setPrompt] = useState(initial.prompt)

  const toggle = (id: string) =>
    setDepts((cur) => (cur.includes(id) ? cur.filter((d) => d !== id) : [...cur, id]))
  const label =
    depts.length === 0
      ? s.departmentHint
      : depts.length === 1
        ? t(departmentOptions.find((d) => d.id === depts[0])!.name)
        : s.departmentsSelected(depts.length)

  return (
    <form
      className="mx-auto max-w-[520px] px-6 pb-16 pt-20"
      onSubmit={(e) => {
        e.preventDefault()
        onSubmit({ patientName: name, birthNumber: birth, departments: depts, prompt })
      }}
    >
      <p className="text-neutral-500">{s.appName}</p>
      <h1 className="font-bold">{s.requestTitle}</h1>
      <p className="mt-1 text-neutral-600">{s.requestIntro}</p>

      <Part title={s.stepPatient}>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block">
            {s.patientName}
            <input className={input} value={name} onChange={(e) => setName(e.target.value)} autoComplete="off" />
          </label>
          <label className="block">
            {s.birthNumber}
            <input className={input} value={birth} onChange={(e) => setBirth(e.target.value)} autoComplete="off" />
          </label>
        </div>
      </Part>

      <Part title={s.stepDepartment}>
        <details className="relative">
          <summary className={`${input} cursor-pointer list-none`}>{label}</summary>
          <ul className="absolute left-0 right-0 z-10 mt-1 border border-neutral-300 bg-white py-1">
            {departmentOptions.map((d) => (
              <li key={d.id}>
                <label className="flex cursor-pointer items-center gap-3 px-3 py-1 hover:bg-neutral-100">
                  <input type="checkbox" checked={depts.includes(d.id)} onChange={() => toggle(d.id)} />
                  {t(d.name)}
                </label>
              </li>
            ))}
          </ul>
        </details>
      </Part>

      <Part title={s.stepRequest}>
        <label className="block">
          {s.situation}
          <textarea
            className={`${input} min-h-[9rem] resize-y`}
            rows={6}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder={s.situationHint}
          />
        </label>
        <p className="mt-1 text-neutral-500">{s.requestExample}</p>
      </Part>

      <div className="mt-8 flex items-center justify-between border-t border-neutral-200 pt-4">
        <span className="text-neutral-500">{s.syntheticOnly}</span>
        <button type="submit" className="bg-neutral-900 px-5 py-2 font-bold text-white hover:bg-black">
          {s.open}
        </button>
      </div>
    </form>
  )
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
      className={`ml-2 inline-block h-[0.55em] w-[0.55em] bg-red-700 ${active === id ? 'outline outline-2 outline-offset-2 outline-red-700' : ''}`}
    />
  )
}

function Entry({ title, bad, children }: { title: string; bad?: boolean; children: ReactNode }) {
  return (
    <section className={`grid grid-cols-[7rem_1fr] gap-x-5 border-t py-2 ${bad ? 'border-red-200' : 'border-neutral-200'}`}>
      <h3 className={`font-bold ${bad ? 'text-red-700' : ''}`}>{title}</h3>
      <div className="space-y-1">{children}</div>
    </section>
  )
}

function Sources({ sources, onOpen }: { sources: Source[]; onOpen: (s: Source) => void }) {
  return (
    <span className="ml-2 inline-flex flex-wrap gap-x-3 text-neutral-500">
      {sources.map((src) => (
        <SourceLink key={`${src.doc}-${src.para}`} source={src} onOpen={onOpen} />
      ))}
    </span>
  )
}

function PlainSummary({
  situation,
  active,
  setActive,
  onOpen,
  onChange,
}: {
  situation: Situation
  active: string | null
  setActive: (id: string | null) => void
  onOpen: (s: Source) => void
  onChange: () => void
}) {
  const { s, t, date } = useI18n()
  const p = bundle.patient
  const depts = situation.departments
    .map((id) => departmentOptions.find((d) => d.id === id))
    .filter((d) => d !== undefined)
    .map((d) => t(d.name))
    .join(', ')

  return (
    <div className="h-full overflow-y-auto px-7 py-5">
      <h1 className="text-[24px] font-bold leading-tight">{p.name}</h1>
      <p className="mt-0.5 text-[17px] text-neutral-600">
        {p.age} {s.years}, {t(p.sex)}, {s.born} {date(p.born)}
      </p>
      <dl className="mt-4 grid grid-cols-3 gap-x-4 border-y border-neutral-200 py-3">
        <div>
          <dt className="text-neutral-500">{s.height}</dt>
          <dd className="text-[20px] font-bold">{p.heightCm} cm</dd>
        </div>
        <div>
          <dt className="text-neutral-500">{s.weight}</dt>
          <dd>
            <strong className="text-[20px]">{p.weightKg} kg</strong>
            <span className="ml-2">
              <SourceLink source={p.weightSource} onOpen={onOpen} />
            </span>
          </dd>
        </div>
        <div>
          <dt className="text-neutral-500">{s.bmi}</dt>
          <dd className="text-[20px] font-bold">
            {p.bmi}
            <Flag id={p.bmiConflict} active={active} set={setActive} />
          </dd>
        </div>
      </dl>

      <div className="mt-4 flex items-baseline justify-between gap-4 text-neutral-500">
        <span>
          {s.situationOf}
          {depts && `, ${depts}`}
        </span>
        <button type="button" onClick={onChange} className="src">
          {s.change}
        </button>
      </div>
      <p className="mt-1 whitespace-pre-wrap">{situation.prompt}</p>

      <h2 className="mb-0 mt-4 border-b border-neutral-900 pb-1 font-bold">{s.summary}</h2>
      {bundle.groups.map((g) => (
        <Entry key={g.label} title={t(g.title)}>
          {g.facts.map((f) => (
            <p key={f.id}>
              <strong>{t(f.value)}</strong>
              {f.conflicts?.map((c) => <Flag key={c} id={c} active={active} set={setActive} />)}
              {f.detail && <span className="text-neutral-600">, {t(f.detail)}</span>}
              <Sources sources={f.sources} onOpen={onOpen} />
            </p>
          ))}
        </Entry>
      ))}
      <Entry title={s.notDocumented}>
        <p>{bundle.notDocumented.map((n) => t(n.title)).join(', ')}</p>
      </Entry>
      <Entry title={s.contradictions} bad>
        {bundle.conflicts.map((c) => (
          <p
            key={c.id}
            onMouseEnter={() => setActive(c.id)}
            onMouseLeave={() => setActive(null)}
            className={`-ml-2 border-l-2 pl-2 ${active === c.id ? 'border-red-700 bg-red-50' : 'border-transparent'}`}
          >
            <strong>{t(c.title)}</strong>
            <span className="text-neutral-600">, {t(c.summary)}</span>
            <Sources sources={c.sources} onOpen={onOpen} />
          </p>
        ))}
      </Entry>
    </div>
  )
}

function PlainRecords({
  filters,
  setFilters,
  active,
  setActive,
  onOpen,
}: {
  filters: LabelId[]
  setFilters: (f: LabelId[]) => void
  active: string | null
  setActive: (id: string | null) => void
  onOpen: (s: Source) => void
}) {
  const { s, t, date } = useI18n()
  const sorted = [...bundle.records].sort((a, b) => b.relevance - a.relevance)
  const shown = filters.length === 0 ? sorted : sorted.filter((r) => filters.some((f) => (r.labels[f] ?? 0) > 0))
  const toggle = (id: LabelId) =>
    setFilters(filters.includes(id) ? filters.filter((f) => f !== id) : [...filters, id])

  return (
    <div className="h-full overflow-y-auto px-7 py-6 pr-24">
      <h2 className="font-bold">{s.records}</h2>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <span className="text-neutral-500">{s.relevantFor}</span>
        {bundle.labels.map((l) => {
          const on = filters.includes(l.id)
          const n = bundle.records.filter((r) => (r.labels[l.id] ?? 0) > 0).length
          return (
            <button
              key={l.id}
              type="button"
              aria-pressed={on}
              onClick={() => toggle(l.id)}
              className={`border px-2.5 py-0.5 ${on ? 'border-neutral-900 bg-neutral-900 text-white' : 'border-neutral-300 hover:border-neutral-900'}`}
            >
              {t(l.title)} {n}
            </button>
          )
        })}
        {filters.length > 0 && (
          <button type="button" className="src" onClick={() => setFilters([])}>
            {s.clearSelection}
          </button>
        )}
      </div>
      <p className="mt-2 text-neutral-500">{s.showing(shown.length, bundle.records.length)}</p>

      {shown.length === 0 ? (
        <p className="mt-8 text-neutral-500">{s.noMatch}</p>
      ) : (
        <ul className="mt-2">
          {shown.map((r) => {
            const doc = bundle.documents.find((d) => d.id === r.doc)!
            const ex = doc.paragraphs.find((p) => p.id === r.excerpt) ?? doc.paragraphs[0]
            const chips = bundle.labels.filter((l) => (r.labels[l.id] ?? 0) > 0)
            const hit = active !== null && r.conflicts.includes(active)
            return (
              <li key={r.doc} className={`border-t border-neutral-200 py-4 ${hit ? 'bg-red-50' : ''}`}>
                <div className="flex items-baseline justify-between gap-6">
                  <button type="button" onClick={() => onOpen({ doc: r.doc, para: ex.id })} className="text-left">
                    <span className="font-bold underline-offset-2 hover:underline">{t(doc.title)}</span>
                    <span className="block text-neutral-500">
                      {date(doc.date)}, {t(doc.department)}
                    </span>
                  </button>
                  <span className="shrink-0 text-right" title={`${s.relevance} ${r.relevance}%`}>
                    <strong>{r.relevance}%</strong>
                    <span className="mt-1 block h-[3px] w-14 bg-neutral-200">
                      <span className="block h-full bg-green-700" style={{ width: `${r.relevance}%` }} />
                    </span>
                  </span>
                </div>
                <p className="mt-2 max-w-[70ch]">
                  <Rich text={t(ex.text)} />
                </p>
                {(chips.length > 0 || r.conflicts.length > 0) && (
                  <p className="mt-2 flex flex-wrap gap-x-5 text-neutral-600">
                    {chips.map((l) => (
                      <span key={l.id}>
                        {t(l.title)} <strong className="text-neutral-900">{r.labels[l.id]}</strong>
                      </span>
                    ))}
                    {r.conflicts.length > 0 && (
                      <span
                        className="ml-auto font-bold text-red-700"
                        onMouseEnter={() => setActive(r.conflicts[0])}
                        onMouseLeave={() => setActive(null)}
                      >
                        {s.contradiction}
                        {r.conflicts.length > 1 ? ` ×${r.conflicts.length}` : ''}
                      </span>
                    )}
                  </p>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

function PlainReader({ source, onBack, onOpen }: { source: Source; onBack: () => void; onOpen: (s: Source) => void }) {
  const { s, t, date, lang } = useI18n()
  const [original, setOriginal] = useState(false)
  const hl = useRef<HTMLDivElement>(null)
  const doc = bundle.documents.find((d) => d.id === source.doc)!
  useEffect(() => {
    hl.current?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [source.doc, source.para])
  const german = lang === 'de' || original

  return (
    <div className="h-full overflow-y-auto px-7 py-6 pr-24">
      <button type="button" onClick={onBack} className="src">
        {s.back}
      </button>
      <h2 className="mt-3 font-bold">{t(doc.title)}</h2>
      <p className="text-neutral-500">
        {date(doc.date)}, {t(doc.department)}
      </p>
      {lang === 'en' && (
        <p className="mt-1 text-neutral-500">
          {s.originalNote}{' '}
          <button type="button" className="src" onClick={() => setOriginal((o) => !o)}>
            {original ? s.showTranslation : s.showOriginal}
          </button>
        </p>
      )}
      <div className="mt-4 max-w-[70ch] border-t border-neutral-200 pt-4">
        {doc.paragraphs.map((p) => {
          const on = p.id === source.para
          const conflict = bundle.conflicts.find((c) => c.sources.some((x) => x.doc === doc.id && x.para === p.id))
          const others = conflict?.sources.filter((x) => !(x.doc === doc.id && x.para === p.id)) ?? []
          return (
            <div
              key={p.id}
              ref={on ? hl : undefined}
              className={`-mx-3 mb-2 px-3 py-2 ${on ? 'bg-green-100' : ''} ${conflict ? 'border-l-2 border-red-700' : ''}`}
            >
              <Rich text={german ? p.text.de : p.text.en} />
              {conflict && (
                <p className="text-neutral-600">
                  <strong className="text-red-700">{s.contradiction}:</strong> {t(conflict.title)}
                  {others.length > 0 && (
                    <>
                      {'. '}
                      {s.seeOther}
                      <Sources sources={others} onOpen={onOpen} />
                    </>
                  )}
                </p>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function PlainWorkspace({ situation, onChange }: { situation: Situation; onChange: () => void }) {
  const { s } = useI18n()
  const [left, setLeft] = useState(defaultLeft)
  const [dragging, setDragging] = useState(false)
  const [reader, setReader] = useState<Source | null>(null)
  const [filters, setFilters] = useState<LabelId[]>([])
  const [active, setActive] = useState<string | null>(null)
  const start = useRef({ x: 0, w: 0 })

  useEffect(() => {
    const onResize = () => setLeft((w) => clampLeft(w))
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  return (
    <div className={`flex h-full flex-col lg:flex-row ${dragging ? 'select-none' : ''}`}>
      <aside className="shrink-0 bg-neutral-50 max-lg:!w-full lg:h-full" style={{ width: left }} aria-label={s.summary}>
        <PlainSummary situation={situation} active={active} setActive={setActive} onOpen={setReader} onChange={onChange} />
      </aside>
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label={s.dragHint}
        tabIndex={0}
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId)
          start.current = { x: e.clientX, w: left }
          setDragging(true)
        }}
        onPointerMove={(e) => dragging && setLeft(clampLeft(start.current.w + e.clientX - start.current.x))}
        onPointerUp={() => setDragging(false)}
        onPointerCancel={() => setDragging(false)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowLeft') setLeft((w) => clampLeft(w - 24))
          if (e.key === 'ArrowRight') setLeft((w) => clampLeft(w + 24))
        }}
        className="relative hidden w-px shrink-0 cursor-col-resize bg-neutral-300 hover:bg-neutral-900 lg:block"
      >
        <span className="absolute inset-y-0 -left-2 w-4" />
      </div>
      <main className="min-h-0 min-w-0 flex-1 bg-white max-lg:min-h-[70vh] lg:h-full">
        {reader ? (
          <PlainReader source={reader} onBack={() => setReader(null)} onOpen={setReader} />
        ) : (
          <PlainRecords filters={filters} setFilters={setFilters} active={active} setActive={setActive} onOpen={setReader} />
        )}
      </main>
    </div>
  )
}

function PlainChat() {
  const { s } = useI18n()
  const [open, setOpen] = useState(false)
  return (
    <div className="fixed bottom-4 right-4 z-30 flex flex-col items-end gap-2">
      {open && (
        <section className="flex h-[320px] w-[min(320px,calc(100vw-2rem))] flex-col border border-neutral-300 bg-white">
          <header className="flex items-baseline justify-between border-b border-neutral-200 px-4 py-2">
            <h2 className="font-bold">{s.assistantTitle}</h2>
            <button type="button" className="src" onClick={() => setOpen(false)}>
              {s.close}
            </button>
          </header>
          <p className="flex-1 px-4 py-3 text-neutral-500">{s.assistantOffline}</p>
          <form className="flex gap-2 border-t border-neutral-200 p-3" onSubmit={(e) => e.preventDefault()}>
            <input disabled placeholder={s.assistantPlaceholder} className="min-w-0 flex-1 border border-neutral-300 px-2 py-1" />
            <button disabled className="bg-neutral-300 px-3 py-1 font-bold text-white">
              {s.send}
            </button>
          </form>
        </section>
      )}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="border border-neutral-300 bg-white px-4 py-2 font-bold hover:border-neutral-900"
      >
        {s.assistant}
      </button>
    </div>
  )
}

function PlainShell() {
  const [situation, setSituation] = useState<Situation | null>(null)
  const [draft, setDraft] = useState<Situation>(defaultSituation)
  return (
    <div className="fixed inset-0 overflow-auto bg-white font-sans text-[15px] leading-[1.45] text-neutral-900">
      {situation ? (
        <PlainWorkspace
          situation={situation}
          onChange={() => {
            setDraft(situation)
            setSituation(null)
          }}
        />
      ) : (
        <PlainLogin initial={draft} onSubmit={setSituation} />
      )}
      <LangSwitch className="text-neutral-900" />
      {situation && <PlainChat />}
    </div>
  )
}

export default function Plain() {
  return (
    <LangProvider>
      <PlainShell />
    </LangProvider>
  )
}
