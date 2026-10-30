import { bundle } from '../mock'
import { useI18n } from '../lang'
import type { LabelId, RecordMeta } from '../types'
import { roughClip } from '../rough'
import { Rich } from './bits'

type Props = {
  filters: LabelId[]
  setFilters: (f: LabelId[]) => void
  activeConflict: string | null
  setActiveConflict: (id: string | null) => void
  onOpen: (docId: string, para: string) => void
}

function Relevance({ value }: { value: number }) {
  const { s } = useI18n()
  const strong = value >= 55
  return (
    <div
      className="relative flex h-[54px] w-[74px] items-center justify-center"
      role="img"
      aria-label={`${s.relevance} ${value}%`}
      title={`${s.relevance} ${value}%`}
    >
      {/* a tab in the corner: the more relevant the record, the deeper the green */}
      <div className="absolute inset-0 bg-ok" style={{ opacity: 0.14 + 0.86 * (value / 100) }} />
      <div className={`relative font-bold leading-none ${strong ? 'text-paper' : 'text-ink'}`}>
        <span className="">{value}</span>
        <span className="">%</span>
      </div>
    </div>
  )
}

type SheetProps = {
  rec: RecordMeta
  filters: LabelId[]
  active: string | null
  setActive: (id: string | null) => void
  onOpen: (docId: string, para: string) => void
}

function Sheet({ rec, active, setActive, onOpen, filters }: SheetProps) {
  const { s, t, date } = useI18n()
  const doc = bundle.documents.find((d) => d.id === rec.doc)!
  const excerpt = doc.paragraphs.find((p) => p.id === rec.excerpt) ?? doc.paragraphs[0]
  const chips = bundle.labels.filter((l) => (rec.labels[l.id] ?? 0) > 0)
  const hit = active !== null && rec.conflicts.includes(active)

  return (
    <li className={`sheet-shadow ${hit ? 'is-hit' : ''}`}>
      <article className="sheet-rough relative" style={{ clipPath: roughClip(rec.doc) }}>
        <button
          type="button"
          onClick={() => onOpen(rec.doc, excerpt.id)}
          className="block w-full px-5 pb-4 pt-4 text-left"
          aria-label={`${s.openRecord}: ${t(doc.title)}`}
        >
          <div className="pr-24">
            <h3 className=" font-bold leading-tight">{t(doc.title)}</h3>
            <p className="mt-0.5 text-ink/65">
              {date(doc.date)}, {t(doc.department)}
            </p>
          </div>
          <p className="mt-3 line-clamp-3 max-w-[68ch] leading-[1.4] text-ink/90">
            <Rich text={t(excerpt.text)} />
          </p>
        </button>

        <div className="pointer-events-none absolute right-0 top-0">
          <Relevance value={rec.relevance} />
        </div>

        {(chips.length > 0 || rec.conflicts.length > 0) && (
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-t border-ink/15 px-5 py-2.5">
            {chips.map((l) => {
              const on = filters.includes(l.id)
              return (
                <span
                  key={l.id}
                  className={` leading-[1.5] ${on ? 'font-bold text-ink underline decoration-ok decoration-2 underline-offset-4' : 'text-ink/70'}`}
                >
                  {t(l.title)} <strong className="text-ink">{rec.labels[l.id]}</strong>
                </span>
              )
            })}
            {rec.conflicts.length > 0 && (
              <span
                className="stamp ml-auto text-bad"
                onMouseEnter={() => setActive(rec.conflicts[0])}
                onMouseLeave={() => setActive(null)}
              >
                {s.contradiction}
                {rec.conflicts.length > 1 ? ` ×${rec.conflicts.length}` : ''}
              </span>
            )}
          </div>
        )}
      </article>
    </li>
  )
}

export function Records({ filters, setFilters, activeConflict, setActiveConflict, onOpen }: Props) {
  const { s, t } = useI18n()
  const sorted = [...bundle.records].sort((a, b) => b.relevance - a.relevance)
  const shown = filters.length === 0 ? sorted : sorted.filter((r) => filters.some((f) => (r.labels[f] ?? 0) > 0))

  const toggle = (id: LabelId) =>
    setFilters(filters.includes(id) ? filters.filter((f) => f !== id) : [...filters, id])

  const total = (id: LabelId) => bundle.records.filter((r) => (r.labels[id] ?? 0) > 0).length

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="px-6 pb-3 pt-5 pr-24">
        <h2 className=" font-bold leading-none">{s.records}</h2>
        <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-2">
          <span className="mr-1 text-ink/65">{s.relevantFor}</span>
          {bundle.labels.map((l) => {
            const on = filters.includes(l.id)
            return (
              <button
                key={l.id}
                type="button"
                aria-pressed={on}
                onClick={() => toggle(l.id)}
                className={`border px-2.5 py-0.5 transition-colors ${on ? 'border-ink bg-ink font-bold text-paper' : 'border-ink/40 bg-paper/60 hover:bg-paper'}`}
              >
                {t(l.title)} <span className={on ? 'text-paper/70' : 'text-ink/55'}>{total(l.id)}</span>
              </button>
            )
          })}
          {filters.length > 0 && (
            <button type="button" className="src ml-1 !" onClick={() => setFilters([])}>
              {s.clearSelection}
            </button>
          )}
        </div>
        <p className="mt-2 text-ink/55">{s.showing(shown.length, bundle.records.length)}</p>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-8 pt-1">
        {shown.length === 0 ? (
          <p className="mt-10 text-center text-ink/60">{s.noMatch}</p>
        ) : (
          <ul className="mx-auto flex max-w-[820px] flex-col gap-4">
            {shown.map((r) => (
              <Sheet
                key={r.doc}
                rec={r}
                filters={filters}
                active={activeConflict}
                setActive={setActiveConflict}
                onOpen={onOpen}
              />
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
