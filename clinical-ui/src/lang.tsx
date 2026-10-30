import { createContext, useContext, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import type { L, Lang } from './types'

const en = {
  appName: 'Clinical summary desk',
  requestTitle: 'Patient record request',
  requestIntro: 'Tell us whose record to open and what you need it for. Only the facts for that task will be shown.',
  stepPatient: 'Patient',
  stepDepartment: 'Your department',
  stepRequest: 'Your request',
  requestExample: 'For example: surgeon, planning the operation after the tumour board',
  patientName: 'Patient name',
  birthNumber: 'Birth number',
  department: 'Department',
  departmentHint: 'Choose one or more',
  departmentsSelected: (n: number) => `${n} departments`,
  situation: 'Situation',
  situationHint: 'Your role and what you are doing, for example: surgeon, planning the operation after the tumour board',
  open: 'Open record',
  syntheticOnly: 'Synthetic data only',
  summary: 'Summary',
  situationOf: 'Situation',
  change: 'Change',
  years: 'years',
  born: 'born',
  height: 'Height',
  weight: 'Weight',
  bmi: 'BMI',
  notDocumented: 'Not documented',
  contradictions: 'Contradictions',
  noContradictions: 'No contradictions found.',
  records: 'Records',
  relevantFor: 'Relevant for',
  allRecords: 'All records',
  showing: (n: number, total: number) => `Showing ${n} of ${total}`,
  clearSelection: 'Clear selection',
  relevance: 'relevance',
  noMatch: 'No record matches this selection.',
  back: 'Back to records',
  openRecord: 'Open record',
  contradiction: 'Contradiction',
  showOriginal: 'Show German original',
  showTranslation: 'Show translation',
  originalNote: 'The original documents are in German.',
  seeOther: 'See also',
  assistant: 'Assistant',
  assistantTitle: 'Ask about this patient',
  assistantOffline: 'Not connected yet. Questions will be answered here, with a source for every fact.',
  assistantPlaceholder: 'Type a question',
  send: 'Send',
  close: 'Close',
  dragHint: 'Drag to resize',
  widen: 'Widen the summary',
  narrow: 'Narrow the summary',
  language: 'Language',
  showing_fact: 'Fact',
  fromRecord: 'From',
}

const de: typeof en = {
  appName: 'Klinischer Überblick',
  requestTitle: 'Anfrage zur Patientenakte',
  requestIntro: 'Wählen Sie die Akte und den Zweck. Angezeigt werden nur die Fakten, die für diese Aufgabe nötig sind.',
  stepPatient: 'Patientin',
  stepDepartment: 'Ihre Abteilung',
  stepRequest: 'Ihre Anfrage',
  requestExample: 'Zum Beispiel: Chirurgin, Operationsplanung nach dem Tumorboard',
  patientName: 'Name der Patientin',
  birthNumber: 'Geburtsnummer',
  department: 'Abteilung',
  departmentHint: 'Eine oder mehrere wählen',
  departmentsSelected: (n: number) => `${n} Abteilungen`,
  situation: 'Situation',
  situationHint: 'Ihre Rolle und Ihre Aufgabe, zum Beispiel: Chirurgin, Operationsplanung nach dem Tumorboard',
  open: 'Akte öffnen',
  syntheticOnly: 'Nur synthetische Daten',
  summary: 'Zusammenfassung',
  situationOf: 'Situation',
  change: 'Ändern',
  years: 'Jahre',
  born: 'geboren',
  height: 'Größe',
  weight: 'Gewicht',
  bmi: 'BMI',
  notDocumented: 'Nicht dokumentiert',
  contradictions: 'Widersprüche',
  noContradictions: 'Keine Widersprüche gefunden.',
  records: 'Dokumente',
  relevantFor: 'Relevant für',
  allRecords: 'Alle Dokumente',
  showing: (n: number, total: number) => `${n} von ${total} angezeigt`,
  clearSelection: 'Auswahl aufheben',
  relevance: 'Relevanz',
  noMatch: 'Kein Dokument passt zu dieser Auswahl.',
  back: 'Zurück zu den Dokumenten',
  openRecord: 'Dokument öffnen',
  contradiction: 'Widerspruch',
  showOriginal: 'Deutsches Original anzeigen',
  showTranslation: 'Übersetzung anzeigen',
  originalNote: 'Die Originaldokumente sind auf Deutsch.',
  seeOther: 'Siehe auch',
  assistant: 'Assistent',
  assistantTitle: 'Fragen zu dieser Patientin',
  assistantOffline: 'Noch nicht verbunden. Fragen werden hier beantwortet, mit Quelle für jeden Fakt.',
  assistantPlaceholder: 'Frage eingeben',
  send: 'Senden',
  close: 'Schließen',
  dragHint: 'Ziehen, um die Breite zu ändern',
  widen: 'Zusammenfassung verbreitern',
  narrow: 'Zusammenfassung verschmälern',
  language: 'Sprache',
  showing_fact: 'Fakt',
  fromRecord: 'Aus',
}

const strings = { en, de }

type Ctx = { lang: Lang; setLang: (l: Lang) => void }
const LangContext = createContext<Ctx>({ lang: 'en', setLang: () => {} })

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLang] = useState<Lang>('en')
  const value = useMemo(() => ({ lang, setLang }), [lang])
  return <LangContext.Provider value={value}>{children}</LangContext.Provider>
}

export function useI18n() {
  const { lang, setLang } = useContext(LangContext)
  const s = strings[lang]
  const t = (text: L) => text[lang]
  const date = (iso: string) =>
    new Date(iso).toLocaleDateString(lang === 'en' ? 'en-GB' : 'de-AT', {
      day: 'numeric',
      month: 'long',
      year: 'numeric',
    })
  return { lang, setLang, s, t, date }
}
