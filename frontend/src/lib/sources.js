/** Document lookup for one active dataset; App passes the store down through SourceContext. */
export function makeDocumentStore(documents) {
  const byId = new Map(documents.map((d) => [d.id, d]));

  const getDocument = (docId) => {
    const doc = byId.get(docId);
    if (!doc) throw new Error(`Unknown source document: ${docId}`);
    return doc;
  };

  /** All selected passages, in their citation order. */
  const getPassage = (ref) => {
    const doc = getDocument(ref.docId);
    return ref.passageIds.map((id) => findSegment(doc, id).text).join('\n');
  };

  const resolves = (ref) => {
    const doc = byId.get(ref.docId);
    return Boolean(doc) && ref.passageIds.every((id) => hasSegment(doc, id));
  };

  return { getDocument, getPassage, resolves };
}

function* passages(doc) {
  for (const section of doc.sections) {
    if (section.headingId) yield { id: section.headingId, text: section.heading };
    for (const paragraph of section.paragraphs) {
      for (const seg of paragraph) if (typeof seg !== 'string') yield seg;
    }
  }
}

function findSegment(doc, passageId) {
  for (const seg of passages(doc)) if (seg.id === passageId) return seg;
  throw new Error(`Unknown passage ${passageId} in ${doc.id}`);
}

const hasSegment = (doc, passageId) => {
  for (const seg of passages(doc)) if (seg.id === passageId) return true;
  return false;
};

export function refKey(ref) {
  return `${ref.docId}#${ref.passageIds.join('+')}`;
}

/** Every reference in the encounter, for the startup check and the backend adapter. */
export function encounterRefs(encounter) {
  return [
    ...encounter.summary.map((p) => p.source),
    ...encounter.important.flatMap((i) => i.sources),
    ...encounter.otherHistory.map((h) => h.source),
    ...(encounter.record ?? []).map((r) => r.source),
    ...encounter.contradictions.flatMap((c) => c.sides),
    ...(encounter.reviewFindings ?? []).flatMap((c) => c.sides),
  ].filter(Boolean);
}

/** Throws if any reference in the encounter points nowhere. */
export function validateRefs(encounter, store) {
  for (const ref of encounterRefs(encounter)) {
    if (!store.resolves(ref)) throw new Error(`Unresolved citation ${refKey(ref)}`);
  }
}
