import { createContext, useContext } from 'react';

/**
 * UI language (EN/DE). Interface text, labels and generated explanations follow it; quoted
 * document passages stay verbatim in their original language.
 */
export const LANGS = ['en', 'de'];

const STRINGS = {
  en: {
    loggedIn: 'Logged in',
    newSearch: 'New search',
    language: 'Language',
    clinician: 'Clinician',
    // search
    findPatientTitle: 'Find a patient',
    patientName: 'Patient name',
    birthDate: 'Date of birth',
    roleTask: 'Role and task',
    findPatient: 'Find patient',
    searching: 'Searching the records…',
    loaded: 'Record loaded ✓',
    enterTask: 'Enter the role and task',
    noPatient: 'No patient found · check name and date of birth',
    unreachable: 'Backend not reachable · start it with python -m app.server',
    serverFailed: 'The assessment failed on the server',
    importFolder: 'Import patient folder',
    importFiles: 'Import files',
    importing: 'Importing and indexing the record…',
    imported: '{name} imported · {docs} documents · {facts} verified facts',
    importWarnings: '{n} file notes',
    importFailed: 'The import failed on the server',
    importHint: 'Same format as the test data: patient.json and documents/<id>.json',
    translating: 'Switching language…',
    // patient panel
    patientProfile: 'Patient profile',
    born: 'Born',
    age: 'Age',
    years: '{n} years',
    patientId: 'Patient ID',
    recordsAsOf: 'Records as of',
    encounter: 'Encounter',
    context: 'Context',
    contradictionsOne: '{n} contradiction',
    contradictionsMany: '{n} contradictions',
    differentFindings: 'Different findings · not counted as contradictions',
    differentFindingsAria: 'Different findings for review',
    review: 'Review',
    // important panel
    importantTitle: 'Important information',
    importantScroll: 'Important information, scrollable',
    task: 'Task',
    noSelection: 'No selection prepared for this task yet · use the collected facts and Documents',
    sourceDocsHint: 'Source documents · Documents on the right',
    scrollMore: 'Scroll down for more important information',
    openContradiction: 'Open contradiction {code}: {title}',
    contradictionTag: 'Contradiction {code} →',
    // documents sidebar
    documents: 'Documents',
    browseViews: 'Browse documents or facts',
    byDocument: 'By document',
    byType: 'By type',
    factCategories: 'Fact categories',
    factsCount: '{n} collected facts · all dates',
    noFacts: 'Not documented',
    allTopics: 'All topics',
    topicsSelected: '{n} topics',
    filterTopics: 'Filter topics',
    showAll: 'Show all',
    activeFilters: 'Active topic filters',
    removeFilter: 'Remove filter {name}',
    factsShown: '{n} of {total} facts',
    timelineAria: 'Document timeline, newest first',
    documentFor: 'Document: {type}',
    taskSource: 'Task source',
    // detail dialog
    closeViewer: 'Close document viewer',
    sourceSide: 'Source {letter}',
    reviewFindings: 'Different findings for review',
    contradictionCode: 'Contradiction {code}',
    differentTag: 'Different findings',
    unresolved: 'Unresolved',
    highPriority: 'High priority · ',
    sourcesOne: '1 source',
    sourcesCount: '{n} sources',
    whyReview: 'Why review',
    reviewFooter: 'Not counted as a contradiction · both findings preserved',
    unresolvedFooter: 'Unresolved · neither statement assumed correct · records unchanged',
    sourceOf: 'Source · {type}',
    documentContent: 'Document content',
    openedFor: 'Opened for',
    fullDocument: 'full document',
    passageOne: 'passage highlighted',
    passagesMany: '{n} passages highlighted',
    demoNote: 'Synthetic document · demonstration data only.',
    collectedFacts: 'Collected facts',
    collectedFactsFor: 'Collected facts: {label}',
    entriesNote: '{n} entries · all dates · not filtered by task relevance',
    filterByCategory: 'Filter by category',
    all: 'All',
    // source links
    openSource: 'Open source: {title}, {date}',
    passageN: 'Passage {n}: {text}',
    // backend adapter
    absentPrefix: 'Documented as absent: ',
    uncertainPrefix: 'Uncertain: ',
    notDocumented: 'Not documented',
    incomplete: 'Not fully processed · check the documents',
    mentioned: 'Mentioned in text',
    superseded: '{when}, superseded',
    calculated: 'calculated',
    calculatedCategory: 'Calculated',
    calculatedDetail: 'Calculated from the linked passages',
    sourceN: 'source {n}',
    reasonLlm: 'A language-model check confirmed that the linked passages cannot all be true.',
    reasonRule: 'A rule check found that the linked passages cannot all be true.',
    sideDiffers: 'Side differs: {diff}',
    bmiTitle: 'BMI {recorded} vs {calculated} kg/m² calculated',
    bmiExplanation: 'Recorded BMI {recorded} kg/m² differs from {calculated} kg/m² calculated from the height and weight in the same passage.',
    roundingNote: 'Rounding intervals remain separated by {gap}, above the conservative margin {margin}.',
  },
  de: {
    loggedIn: 'Angemeldet',
    newSearch: 'Neue Suche',
    language: 'Sprache',
    clinician: 'Ärztin/Arzt',
    findPatientTitle: 'Patientin oder Patient suchen',
    patientName: 'Name',
    birthDate: 'Geburtsdatum',
    roleTask: 'Rolle und Aufgabe',
    findPatient: 'Suchen',
    searching: 'Akten werden durchsucht…',
    loaded: 'Akte geladen ✓',
    enterTask: 'Rolle und Aufgabe eingeben',
    noPatient: 'Keine Person gefunden · Name und Geburtsdatum prüfen',
    unreachable: 'Backend nicht erreichbar · mit python -m app.server starten',
    serverFailed: 'Die Auswertung ist auf dem Server fehlgeschlagen',
    importFolder: 'Patientenordner importieren',
    importFiles: 'Dateien importieren',
    importing: 'Akte wird importiert und indexiert…',
    imported: '{name} importiert · {docs} Dokumente · {facts} geprüfte Fakten',
    importWarnings: '{n} Hinweise zu Dateien',
    importFailed: 'Der Import ist auf dem Server fehlgeschlagen',
    importHint: 'Format wie die Testdaten: patient.json und documents/<id>.json',
    translating: 'Sprache wird gewechselt…',
    patientProfile: 'Patientenprofil',
    born: 'Geboren',
    age: 'Alter',
    years: '{n} Jahre',
    patientId: 'Patienten-ID',
    recordsAsOf: 'Akten bis',
    encounter: 'Termin',
    context: 'Kontext',
    contradictionsOne: '{n} Widerspruch',
    contradictionsMany: '{n} Widersprüche',
    differentFindings: 'Abweichende Befunde · nicht als Widerspruch gezählt',
    differentFindingsAria: 'Abweichende Befunde zur Prüfung',
    review: 'Prüfen',
    importantTitle: 'Wichtige Informationen',
    importantScroll: 'Wichtige Informationen, scrollbar',
    task: 'Aufgabe',
    noSelection: 'Für diese Aufgabe gibt es noch keine Auswahl · gesammelte Fakten und Dokumente nutzen',
    sourceDocsHint: 'Quelldokumente · Dokumente rechts',
    scrollMore: 'Nach unten scrollen für weitere wichtige Informationen',
    openContradiction: 'Widerspruch {code} öffnen: {title}',
    contradictionTag: 'Widerspruch {code} →',
    documents: 'Dokumente',
    browseViews: 'Dokumente oder Fakten durchsuchen',
    byDocument: 'Nach Dokument',
    byType: 'Nach Thema',
    factCategories: 'Themen',
    factsCount: '{n} gesammelte Fakten · alle Daten',
    noFacts: 'Nicht dokumentiert',
    allTopics: 'Alle Themen',
    topicsSelected: '{n} Themen',
    filterTopics: 'Themen filtern',
    showAll: 'Alle anzeigen',
    activeFilters: 'Aktive Themenfilter',
    removeFilter: 'Filter {name} entfernen',
    factsShown: '{n} von {total} Fakten',
    timelineAria: 'Dokumentenverlauf, neueste zuerst',
    documentFor: 'Dokument: {type}',
    taskSource: 'Quelle für die Aufgabe',
    closeViewer: 'Dokumentansicht schließen',
    sourceSide: 'Quelle {letter}',
    reviewFindings: 'Abweichende Befunde zur Prüfung',
    contradictionCode: 'Widerspruch {code}',
    differentTag: 'Abweichende Befunde',
    unresolved: 'Ungeklärt',
    highPriority: 'Hohe Priorität · ',
    sourcesOne: '1 Quelle',
    sourcesCount: '{n} Quellen',
    whyReview: 'Warum prüfen',
    reviewFooter: 'Nicht als Widerspruch gezählt · beide Befunde bleiben erhalten',
    unresolvedFooter: 'Ungeklärt · keine Aussage als richtig angenommen · Akten unverändert',
    sourceOf: 'Quelle · {type}',
    documentContent: 'Dokumentinhalt',
    openedFor: 'Geöffnet für',
    fullDocument: 'ganzes Dokument',
    passageOne: 'Passage markiert',
    passagesMany: '{n} Passagen markiert',
    demoNote: 'Synthetisches Dokument · nur Demonstrationsdaten.',
    collectedFacts: 'Gesammelte Fakten',
    collectedFactsFor: 'Gesammelte Fakten: {label}',
    entriesNote: '{n} Einträge · alle Daten · nicht nach Aufgabe gefiltert',
    filterByCategory: 'Nach Thema filtern',
    all: 'Alle',
    openSource: 'Quelle öffnen: {title}, {date}',
    passageN: 'Passage {n}: {text}',
    absentPrefix: 'Als nicht vorhanden dokumentiert: ',
    uncertainPrefix: 'Unklar: ',
    notDocumented: 'Nicht dokumentiert',
    incomplete: 'Nicht vollständig geprüft · Dokumente ansehen',
    mentioned: 'Im Text erwähnt',
    superseded: '{when}, überholt',
    calculated: 'berechnet',
    calculatedCategory: 'Berechnet',
    calculatedDetail: 'Aus den verlinkten Passagen berechnet',
    sourceN: 'Quelle {n}',
    reasonLlm: 'Eine Sprachmodell-Prüfung hat bestätigt, dass die verlinkten Passagen nicht alle zutreffen können.',
    reasonRule: 'Eine Regelprüfung hat ergeben, dass die verlinkten Passagen nicht alle zutreffen können.',
    sideDiffers: 'Seitenangabe unterschiedlich: {diff}',
    bmiTitle: 'BMI {recorded} vs. {calculated} kg/m² berechnet',
    bmiExplanation: 'Dokumentierter BMI {recorded} kg/m² weicht von {calculated} kg/m² ab, berechnet aus Größe und Gewicht in derselben Passage.',
    roundingNote: 'Die Rundungsintervalle liegen {gap} auseinander, über der konservativen Toleranz von {margin}.',
  },
};

/** Words backend enums use; anything not listed is shown as is. */
const TERMS = {
  en: { female: 'Female', male: 'Male', diverse: 'Diverse', negated: 'negated', past: 'past', planned: 'planned', uncertain: 'uncertain', hypothetical: 'hypothetical', laterality: 'Side (laterality)', number: 'Values', date: 'Dates', status: 'Status', other: 'Content' },
  de: { female: 'Weiblich', male: 'Männlich', diverse: 'Divers', negated: 'verneint', past: 'früher', planned: 'geplant', uncertain: 'unsicher', hypothetical: 'hypothetisch', laterality: 'Seitenangabe', number: 'Werte', date: 'Daten', status: 'Status', other: 'Inhalt' },
};

export function makeT(lang) {
  const table = STRINGS[lang] ?? STRINGS.en;
  const t = (key, vars = {}) =>
    (table[key] ?? STRINGS.en[key] ?? key).replace(/\{(\w+)\}/g, (_, k) => String(vars[k] ?? ''));
  t.term = (word) => TERMS[lang]?.[String(word).toLowerCase()] ?? word;
  t.lang = lang;
  return t;
}

/** Decimal comma for German. */
export const num = (value, lang) => (lang === 'de' ? String(value).replace('.', ',') : String(value));

const DE = /\b(und|oder|für|vor|nach|bei|mit|der|die|das|des|dem|ein|eine|einer|ist|zur|zum|von|aus|präoperativ\w*|narkose\w*|aufgabe|prüfung|untersuchung|patientin|patienten|ärztin|arzt|anästhes\w*|brust\w*|operation|eingriff|vorbereitung|aufklärung|chirurg\w*|pflege\w*|station)\b/g;
const EN = /\b(and|or|for|before|after|with|the|of|to|pre-?operative|anaesthe\w*|anesthe\w*|check|surgery|assessment|review|patient|doctor|nurse|breast|operation|procedure|physio\w*|discharge|ward)\b/g;

/** Language of the typed task: 'de', 'en', or null when unclear. */
export function detectLang(text) {
  const s = ` ${text.toLowerCase()} `;
  const de = (s.match(DE) ?? []).length + (/[äöüß]/.test(s) ? 2 : 0);
  const en = (s.match(EN) ?? []).length;
  if (de === en) return null;
  return de > en ? 'de' : 'en';
}

export const LangContext = createContext({ lang: 'en', t: makeT('en'), setLang: () => {}, busy: false });

export const useT = () => useContext(LangContext).t;
export const useLang = () => useContext(LangContext);
