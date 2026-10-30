import { useState } from 'react'
import { useI18n } from '../lang'

export function Chat() {
  const { s } = useI18n()
  const [open, setOpen] = useState(false)

  return (
    <div className="fixed bottom-4 right-4 z-30 flex flex-col items-end gap-2">
      {open && (
        <section
          aria-label={s.assistantTitle}
          className="sheet flex h-[360px] w-[min(320px,calc(100vw-2rem))] flex-col"
        >
          <header className="flex items-baseline justify-between border-b border-ink/25 px-4 py-2.5">
            <h2 className=" font-bold leading-none">{s.assistantTitle}</h2>
            <button type="button" className="src !" onClick={() => setOpen(false)}>
              {s.close}
            </button>
          </header>
          <div className="flex-1 px-4 py-4">
            <p className="text-ink/70">{s.assistantOffline}</p>
          </div>
          <form
            className="flex items-end gap-2 border-t border-ink/25 px-4 py-3"
            onSubmit={(e) => e.preventDefault()}
          >
            <input
              disabled
              placeholder={s.assistantPlaceholder}
              className="min-w-0 flex-1 border-0 border-b border-ink/40 bg-transparent pb-0.5 outline-none placeholder:text-ink/40"
            />
            <button type="submit" disabled className="bg-charcoal/40 px-3 py-1 font-bold text-cream">
              {s.send}
            </button>
          </form>
        </section>
      )}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="sheet px-4 py-2 font-bold transition-transform hover:-translate-y-px"
      >
        {s.assistant}
      </button>
    </div>
  )
}
