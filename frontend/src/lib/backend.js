import { makeDocumentStore } from './sources';
import { formatDate, formatMonth } from './format';
import { makeT, num } from './i18n';

/**
 * Backend adapter: POST /api/assess (backend/app/server.py) -> the UI's Dataset shape.
 * Every fact shown is a verbatim document passage or a value the backend calculated from
 * linked passages; references that do not resolve against the returned documents are dropped.
 * Labels and generated text follow the requested language; passages stay verbatim.
 */

const MAX_KEYWORDS = 4;      // per row: a drug list keeps three drugs and a superseded dose
const MAX_FALLBACK_CHARS = 70; // passage shown when the backend gave no keyword
const MAX_QUOTE_CHARS = 180;

const ERRORS = { 404: 'noPatient', 500: 'serverFailed' };

export async function assess({ name, birthDate, task, lang = 'en' }) {
  const t = makeT(lang);
  let res;
  try {
    res = await fetch('/api/assess', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, birthDate, task, lang }),
    });
  } catch {
    throw new Error(t('unreachable'));
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(ERRORS[res.status] ? t(ERRORS[res.status]) : (body.error ?? `Backend error ${res.status}`));
  return { ...toDataset(body), query: { name, birthDate, task } };
}

/**
 * POST /api/import: a patient folder in the test-data format (patient.json, documents/<id>.json and
 * optional extraction files). The backend checks, stores and indexes it; returns {patient, documents,
 * facts, contradictions, warnings}.
 */
export async function importPatient(fileList, lang = 'en') {
  const t = makeT(lang);
  const files = await Promise.all(
    [...fileList]
      .filter((f) => f.name.toLowerCase().endsWith('.json'))
      .map(async (f) => ({ name: f.webkitRelativePath || f.name, text: await f.text() })),
  );
  let res;
  try {
    res = await fetch('/api/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ files }),
    });
  } catch {
    throw new Error(t('unreachable'));
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(res.status === 500 ? t('importFailed') : (body.error ?? `Backend error ${res.status}`));
  return body;
}

/** Segment IDs -> one citation per document, in first-seen order. */
function byDoc(segmentIds) {
  const groups = new Map();
  for (const id of segmentIds) {
    const docId = id.split('#')[0];
    if (!groups.has(docId)) groups.set(docId, []);
    if (!groups.get(docId).includes(id)) groups.get(docId).push(id);
  }
  return [...groups].map(([docId, passageIds]) => ({ docId, passageIds }));
}

const quote = (text) => {
  const t = text.replace(/\s+/g, ' ').replace(/\[/g, '(').replace(/\]/g, ')').trim();
  return t.length > MAX_QUOTE_CHARS ? `${t.slice(0, MAX_QUOTE_CHARS - 1)}…` : t;
};

/** The words that answer the item (backend keyword); a trimmed passage only when there is none. */
const keywordOf = (f) => {
  const text = quote(f.keyword || f.text);
  return f.keyword || text.length <= MAX_FALLBACK_CHARS ? text : `${text.slice(0, MAX_FALLBACK_CHARS - 1).replace(/\s+\S*$/, '')} …`;
};

/** A flag as a citation; `marks` are the keyword's character ranges inside the passage, for highlighting. */
const flagSource = (f) => ({
  docId: f.doc_id,
  passageIds: [f.segment_id],
  marks: {
    [f.segment_id]: (f.highlights ?? [])
      .map(([a, b]) => [a - f.start, b - f.start])
      .filter(([a, b]) => a >= 0 && a < b && b <= f.text.length),
  },
});

const prettyRole = (nodeId) => {
  const tail = nodeId.split(/[.:/]/).pop().replace(/_/g, ' ');
  return tail.charAt(0).toUpperCase() + tail.slice(1);
};

const valueText = (d, lang) => {
  const v = d.concept.endsWith('_change') ? (d.value > 0 ? '+' : '') + d.value.toFixed(1) : d.value.toFixed(1);
  return `${num(v, lang)} ${d.unit}`;
};

const derivedLabel = (d, lang) => d.labels?.[lang] ?? d.label;
const STATUS_PREFIX = { documented_absent: 'absentPrefix', uncertain: 'uncertainPrefix' };
const MISSING = { not_documented: 'notDocumented', processing_incomplete: 'incomplete' };

function importantRow(item, derived, conflictFor, store, t) {
  const { lang } = t;
  const sources = [];
  const cite = (ref) => {
    if (!store.resolves(ref)) return null;
    sources.push(ref);
    return sources.length - 1;
  };

  // Every passage is shown by its keyword, and the keyword itself is the link to the passage.
  const parts = [];
  const seen = new Set();
  const flags = [...item.flags].sort((a, b) => Number(b.current) - Number(a.current));
  for (const f of flags) {
    const text = keywordOf(f);
    const key = text.toLowerCase().replace(/\s+/g, ' ');
    if (seen.has(key) || parts.length >= MAX_KEYWORDS) continue;
    const i = cite(flagSource(f));
    if (i === null) continue;
    seen.add(key);
    const notes = [f.polarity === 'affirmed' ? '' : t.term(f.polarity), f.current ? '' : t('superseded', { when: formatMonth(f.doc_date, lang) })].filter(Boolean);
    parts.push(`[${text}](${i})${notes.length ? ` (${notes.join(', ')})` : ''}`);
  }
  for (const d of derived.filter((x) => x.items.includes(item.item_id))) {
    const refs = byDoc(d.segment_ids).map(cite).filter((i) => i !== null);
    if (!refs.length) continue;
    const more = refs.slice(1).map((i, k) => ` [${t('sourceN', { n: k + 2 })}](${i})`).join('');
    parts.push(`${derivedLabel(d, lang)}: [${valueText(d, lang)}](${refs[0]})${more} (${t('calculated')})`);
  }

  const dates = item.flags.map((f) => f.doc_date).filter(Boolean).sort();
  const missing = MISSING[item.status] && t(MISSING[item.status]);
  return {
    id: item.item_id,
    heading: item.label[lang] ?? item.label.en,
    recency: missing || !dates.length ? '—' : formatDate(dates[dates.length - 1], lang),
    summary: missing && !parts.length
      ? missing
      : (STATUS_PREFIX[item.status] ? t(STATUS_PREFIX[item.status]) : '') + (parts.length ? parts.join(' · ') : t('mentioned')),
    sources,
    priority: item.priority,
    contradictionId: conflictFor(item.item_id),
  };
}

// Evidence-bundle explanations are English only; known patterns are rebuilt in the UI language.
const BMI = /Recorded BMI ([\d.]+) kg\/m² differs from ([\d.]+) kg\/m²[^.]*\.(?:\s*Rounding intervals remain separated by ([\d.]+), above the conservative margin ([\d.]+)\.)?/;

function describeConflict(c, t) {
  const { lang } = t;
  const bmi = c.explanation.match(BMI);
  if (bmi) {
    const [, recorded, calculated, gap, margin] = bmi.map((v) => v && num(v, lang));
    return {
      title: t('bmiTitle', { recorded, calculated }),
      description: t('bmiExplanation', { recorded, calculated }) + (gap ? ` ${t('roundingNote', { gap, margin })}` : ''),
    };
  }
  if (c.kind === 'laterality' && c.differing.length) {
    return { title: t('sideDiffers', { diff: c.differing.slice(0, 2).join(' / ') }), description: c.explanation };
  }
  const first = c.explanation.split(/(?<=\.)\s/)[0];
  return { title: first.length > 72 ? `${first.slice(0, 71).replace(/\s+\S*$/, '')}…` : first, description: c.explanation };
}

/** The most specific role the prompt named; ancestors only when nothing was named. */
function pickRole(nodes, lang) {
  const roles = nodes.filter((n) => n.kind === 'role');
  const named = roles.filter((n) => n.source !== 'ancestor');
  const node = (named.length ? named : roles).sort((a, b) => b.activation - a.activation)[0];
  return node ? node.label?.[lang] ?? prettyRole(node.node_id) : '';
}

function toEncounter(body, store, t) {
  const { lang } = t;
  const r = body.result;
  const items = [...r.items, ...r.custom].sort((a, b) => a.order - b.order);
  const labelOf = (i) => i.label[lang] ?? i.label.en;
  const labels = new Map(items.map((i) => [i.item_id, labelOf(i)]));
  const critical = new Set(items.filter((i) => i.priority === 'critical').map((i) => i.item_id));

  const contradictions = r.conflicts
    .map((c, n) => ({
      id: `c-${n + 1}`,
      code: `C${n + 1}`,
      ...describeConflict(c, t),
      reason: t(c.confirmed_by === 'llm' ? 'reasonLlm' : 'reasonRule'),
      severity: c.kind === 'laterality' || c.items.some((i) => critical.has(i)) ? 'high' : 'normal',
      topic: c.items.map((i) => labels.get(i)).filter(Boolean).join(', ') || t.term(c.kind),
      sides: byDoc(c.segment_ids).filter(store.resolves),
      items: c.items,
    }))
    .filter((c) => c.sides.length);
  const conflictFor = (itemId) => contradictions.find((c) => c.items.includes(itemId))?.id;

  const important = items.map((i) => importantRow(i, r.derived, conflictFor, store, t));

  const record = items.flatMap((i) =>
    i.flags.length
      ? i.flags
          .map((f) => ({ f, source: flagSource(f) }))
          .filter(({ source }) => store.resolves(source))
          .map(({ f, source }) => ({
            id: `${i.item_id}-${f.segment_id}`,
            categoryId: i.item_id,
            category: labelOf(i),
            label: keywordOf(f),
            detail: f.polarity === 'affirmed' ? '' : t.term(f.polarity),
            when: formatMonth(f.doc_date, lang),
            source,
          }))
      : [{ id: `${i.item_id}-missing`, categoryId: i.item_id, category: labelOf(i), label: labelOf(i), detail: MISSING[i.status] ? t(MISSING[i.status]) : i.status, when: '—', source: null, missing: true }],
  );
  for (const d of r.derived) {
    const source = byDoc(d.segment_ids).find(store.resolves);
    if (source) {
      record.push({
        id: d.id, categoryId: 'calculated', category: t('calculatedCategory'),
        label: `${derivedLabel(d, lang)}: ${valueText(d, lang)}`,
        detail: lang === 'en' ? d.explanation : t('calculatedDetail'), when: '—', source,
      });
    }
  }

  const role = pickRole(body.plan.nodes, lang);
  return {
    encounter: {
      clinician: { name: t('clinician'), specialty: role, role },
      context: body.prompt,
      asOf: r.patient.as_of,
      important,
      contradictions,
      reviewFindings: [],
      record,
      summary: [],
      otherHistory: [],
      timings: body.timings_ms,
      issues: r.issues,
    },
    role,
  };
}

export function toDataset(body) {
  const lang = body.lang ?? 'en';
  const t = makeT(lang);
  // label: short document name for source links ("Arztbrief 04/2016"), from the backend
  const labels = body.result?.doc_labels ?? {};
  const documents = body.documents.map((d) => ({ ...d, date: d.date ?? '', label: labels[d.id]?.[lang] ?? labels[d.id]?.en ?? '' }));
  const store = makeDocumentStore(documents);
  const { encounter, role } = toEncounter(body, store, t);
  return {
    key: `backend-${body.patient.id}-${body.prompt}`,
    lang,
    note: 'Backend assessment',
    patient: body.patient,
    encounter,
    documents,
    store,
    tasks: [{ id: 'backend', label: body.prompt, role, curated: true }],
  };
}
