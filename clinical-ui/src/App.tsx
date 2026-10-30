import { useCallback, useEffect, useRef, useState } from 'react'
import { defaultSituation } from './mock'
import { LangProvider, useI18n } from './lang'
import type { LabelId, Situation, Source } from './types'
import { Login } from './components/Login'
import { Summary } from './components/Summary'
import { Records } from './components/Records'
import { Reader } from './components/Reader'
import { Chat } from './components/Chat'
import { LangSwitch } from './components/bits'

const MIN_LEFT = 340
const clampLeft = (px: number) => Math.min(Math.max(px, MIN_LEFT), Math.min(window.innerWidth * 0.55, 780))
const defaultLeft = () => clampLeft(Math.round(window.innerWidth * 0.36))

function Workspace({ situation, onChange }: { situation: Situation; onChange: () => void }) {
  const { s } = useI18n()
  const [left, setLeft] = useState(defaultLeft)
  const [dragging, setDragging] = useState(false)
  const [reader, setReader] = useState<Source | null>(null)
  const [filters, setFilters] = useState<LabelId[]>([])
  const [activeConflict, setActiveConflict] = useState<string | null>(null)
  const startX = useRef(0)
  const startW = useRef(0)
  const moved = useRef(false)

  useEffect(() => {
    const onResize = () => setLeft((w) => clampLeft(w))
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const down = (e: React.PointerEvent) => {
    e.currentTarget.setPointerCapture(e.pointerId)
    startX.current = e.clientX
    startW.current = left
    moved.current = false
    setDragging(true)
  }
  const move = (e: React.PointerEvent) => {
    if (!dragging) return
    if (Math.abs(e.clientX - startX.current) > 3) moved.current = true
    setLeft(clampLeft(startW.current + e.clientX - startX.current))
  }
  const up = () => setDragging(false)

  const atMax = left >= clampLeft(99999) - 2
  const toggleWidth = () => {
    if (moved.current) return
    setLeft(atMax ? defaultLeft() : clampLeft(99999))
  }
  const key = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowLeft') setLeft((w) => clampLeft(w - 24))
    if (e.key === 'ArrowRight') setLeft((w) => clampLeft(w + 24))
  }

  const open = useCallback((src: Source) => setReader(src), [])

  return (
    <div className={`flex h-full flex-col lg:flex-row ${dragging ? 'select-none' : ''}`}>
      <aside
        className="paper-dark shrink-0 max-lg:!w-full lg:h-full"
        style={{ width: left }}
        aria-label={s.summary}
      >
        <Summary
          situation={situation}
          activeConflict={activeConflict}
          setActiveConflict={setActiveConflict}
          onOpen={open}
          onChange={onChange}
        />
      </aside>

      <div
        role="separator"
        aria-orientation="vertical"
        aria-label={s.dragHint}
        aria-valuenow={Math.round(left)}
        tabIndex={0}
        onPointerDown={down}
        onPointerMove={move}
        onPointerUp={up}
        onPointerCancel={up}
        onKeyDown={key}
        className="group relative hidden w-px shrink-0 cursor-col-resize bg-charcoal shadow-[1px_0_0_rgba(0,0,0,0.25)] lg:block"
      >
        {/* wide invisible grab area along the whole line */}
        <span className="absolute inset-y-0 -left-2.5 w-5" />
        <button
          type="button"
          onClick={toggleWidth}
          aria-label={atMax ? s.narrow : s.widen}
          className="paper-dark absolute left-1/2 top-1/2 flex h-12 w-5 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-sm border border-cream/40 text-[18px] leading-none text-cream transition-colors group-hover:border-cream"
        >
          {atMax ? '‹' : '›'}
        </button>
      </div>

      <main className="paper-cream relative min-h-0 min-w-0 flex-1 max-lg:min-h-[70vh] lg:h-full">
        {reader ? (
          <Reader source={reader} onBack={() => setReader(null)} onOpen={open} />
        ) : (
          <Records
            filters={filters}
            setFilters={setFilters}
            activeConflict={activeConflict}
            setActiveConflict={setActiveConflict}
            onOpen={(doc, para) => open({ doc, para })}
          />
        )}
      </main>
    </div>
  )
}

function Shell() {
  const [situation, setSituation] = useState<Situation | null>(null)
  const [draft, setDraft] = useState<Situation>(defaultSituation)

  return (
    <>
      {situation ? (
        <Workspace
          situation={situation}
          onChange={() => {
            setDraft(situation)
            setSituation(null)
          }}
        />
      ) : (
        <Login initial={draft} onSubmit={setSituation} />
      )}
      <LangSwitch className={situation ? 'text-cream max-lg:text-cream lg:text-ink' : 'text-cream'} />
      {situation && <Chat />}
    </>
  )
}

export default function App() {
  return (
    <LangProvider>
      <Shell />
    </LangProvider>
  )
}
