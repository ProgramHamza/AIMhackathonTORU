import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { departmentOptions } from '../mock'
import { useI18n } from '../lang'
import type { Situation } from '../types'

const fieldLine =
  'w-full bg-transparent border-0 border-b border-ink/60 pb-1 pt-1 leading-tight outline-none placeholder:text-ink/35 focus:border-ink'

/** One part of the form: a heading with a rule, then its fields. */
function Part({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="mt-6 min-w-0 border-0 p-0">
      <legend className="mb-3 w-full border-b border-ink/25 pb-1 font-bold text-ink">{title}</legend>
      {children}
    </fieldset>
  )
}

function Label({ children }: { children: ReactNode }) {
  return <span className="block text-ink/65">{children}</span>
}

export function Login({ initial, onSubmit }: { initial: Situation; onSubmit: (s: Situation) => void }) {
  const { s, t } = useI18n()
  const [name, setName] = useState(initial.patientName)
  const [birth, setBirth] = useState(initial.birthNumber)
  const [depts, setDepts] = useState<string[]>(initial.departments)
  const [prompt, setPrompt] = useState(initial.prompt)
  const [menu, setMenu] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!menu) return
    const close = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenu(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [menu])

  const toggle = (id: string) =>
    setDepts((cur) => (cur.includes(id) ? cur.filter((d) => d !== id) : [...cur, id]))

  const deptLabel = () => {
    if (depts.length === 0) return ''
    if (depts.length === 1) return t(departmentOptions.find((d) => d.id === depts[0])!.name)
    return s.departmentsSelected(depts.length)
  }

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    onSubmit({ patientName: name, birthNumber: birth, departments: depts, prompt })
  }

  return (
    <main className="paper-dark relative flex min-h-full items-center justify-center overflow-hidden px-4 py-10">
      <div className="relative w-full max-w-[600px]">
        {/* the pile of sheets underneath */}
        <div className="sheet absolute inset-0 translate-x-2 translate-y-3 opacity-70" aria-hidden />
        <div className="sheet absolute inset-0 translate-x-1 translate-y-1.5 opacity-90" aria-hidden />

        <form onSubmit={submit} className="sheet relative px-8 pb-7 pt-8 sm:px-11">
          <header>
            <p className=" text-ink/60">{s.appName}</p>
            <h1 className="mt-0.5 font-bold leading-tight">{s.requestTitle}</h1>
            <p className="mt-2 max-w-[52ch] leading-snug text-ink/75">{s.requestIntro}</p>
          </header>

          <Part title={s.stepPatient}>
            <div className="grid gap-x-8 gap-y-5 sm:grid-cols-2">
              <label className="block">
                <Label>{s.patientName}</Label>
                <input className={fieldLine} value={name} onChange={(e) => setName(e.target.value)} autoComplete="off" />
              </label>
              <label className="block">
                <Label>{s.birthNumber}</Label>
                <input
                  className={fieldLine}
                  value={birth}
                  onChange={(e) => setBirth(e.target.value)}
                  autoComplete="off"
                  inputMode="numeric"
                />
              </label>
            </div>
          </Part>

          <Part title={s.stepDepartment}>
            <div className="relative" ref={menuRef}>
              <Label>{s.department}</Label>
              <button
                type="button"
                className={`${fieldLine} flex items-center justify-between text-left`}
                onClick={() => setMenu((m) => !m)}
                aria-haspopup="listbox"
                aria-expanded={menu}
              >
                <span className={depts.length ? '' : 'text-ink/35'}>{deptLabel() || s.departmentHint}</span>
                <span aria-hidden className="">
                  {menu ? '▴' : '▾'}
                </span>
              </button>
              {menu && (
                <ul
                  role="listbox"
                  aria-multiselectable
                  className="sheet absolute left-0 right-0 top-full z-10 mt-1 max-h-60 overflow-auto py-1"
                >
                  {departmentOptions.map((d) => {
                    const on = depts.includes(d.id)
                    return (
                      <li key={d.id} role="option" aria-selected={on}>
                        <button
                          type="button"
                          onClick={() => toggle(d.id)}
                          className="flex w-full items-center gap-3 px-4 py-1.5 text-left hover:bg-ink/5"
                        >
                          <span
                            className={`inline-flex h-4 w-4 items-center justify-center border border-ink/70 leading-none ${on ? 'bg-ink text-paper' : ''}`}
                          >
                            {on ? '✓' : ''}
                          </span>
                          <span className={on ? 'font-bold' : ''}>{t(d.name)}</span>
                        </button>
                      </li>
                    )
                  })}
                </ul>
              )}
            </div>
          </Part>

          <Part title={s.stepRequest}>
            <label className="block">
              <Label>{s.situation}</Label>
              <textarea
                className="ruled mt-0.5 block min-h-[9rem] w-full resize-y border-0 bg-transparent px-0 pt-0 outline-none placeholder:text-ink/35"
                rows={6}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder={s.situationHint}
              />
            </label>
            <p className="mt-1 text-ink/55">{s.requestExample}</p>
          </Part>

          <footer className="mt-7 flex items-center justify-between gap-4 border-t border-ink/25 pt-4">
            <span className=" text-ink/60">{s.syntheticOnly}</span>
            <button
              type="submit"
              className="bg-charcoal px-6 py-2 font-bold text-cream transition-transform hover:-translate-y-px active:translate-y-0"
            >
              {s.open}
            </button>
          </footer>
        </form>
      </div>
    </main>
  )
}
