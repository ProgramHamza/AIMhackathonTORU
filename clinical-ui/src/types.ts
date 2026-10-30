export type Lang = 'en' | 'de'

/** A text in both interface languages. */
export type L = { en: string; de: string }

/** Points at one paragraph of one document. */
export type Source = { doc: string; para: string }

export type LabelId = 'antithrombotic' | 'allergy' | 'heart' | 'other'

export type Paragraph = {
  id: string
  /** `**bold**` marks the words the facts were taken from. The German text is the original. */
  text: L
}

export type Doc = {
  id: string
  title: L
  /** Short name used in source links. */
  short: L
  date: string
  kind: L
  department: L
  paragraphs: Paragraph[]
}

export type RecordMeta = {
  doc: string
  /** 0 to 100 */
  relevance: number
  /** Number of facts per checklist label found in this record. */
  labels: Partial<Record<LabelId, number>>
  /** Paragraph shown as the excerpt. */
  excerpt: string
  conflicts: string[]
}

export type Fact = {
  id: string
  value: L
  detail?: L
  sources: Source[]
  conflicts?: string[]
}

export type Group = {
  label: LabelId
  title: L
  facts: Fact[]
}

export type NotDocumented = { id: string; title: L }

export type Conflict = {
  id: string
  title: L
  summary: L
  sources: Source[]
}

export type Patient = {
  name: string
  sex: L
  born: string
  age: number
  heightCm: number
  weightKg: number
  bmi: number
  weightSource: Source
  bmiConflict: string
}

export type Situation = {
  patientName: string
  birthNumber: string
  departments: string[]
  prompt: string
}

export type Bundle = {
  patient: Patient
  groups: Group[]
  notDocumented: NotDocumented[]
  conflicts: Conflict[]
  documents: Doc[]
  records: RecordMeta[]
  labels: { id: LabelId; title: L }[]
}
