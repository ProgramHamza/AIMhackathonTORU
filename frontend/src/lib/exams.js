/** Relevance is based on citations in this task's selected findings, not a clinical score. */
export function orderExams(documents, important, order = 'date') {
  const cited = new Map();
  for (const item of important) for (const ref of item.sources ?? []) {
    const passages = cited.get(ref.docId) ?? new Set();
    ref.passageIds.forEach((id) => passages.add(id));
    cited.set(ref.docId, passages);
  }
  const entries = documents.map((doc) => ({
    ...doc,
    relevant: cited.has(doc.id),
    source: { docId: doc.id, passageIds: [...(cited.get(doc.id) ?? [])] },
  }));
  const newest = (a, b) => b.date.localeCompare(a.date) || a.id.localeCompare(b.id);
  return entries.sort((a, b) => {
    if (order === 'relevance') return Number(b.relevant) - Number(a.relevant) || newest(a, b);
    if (order === 'type') return a.type.localeCompare(b.type) || newest(a, b);
    return newest(a, b);
  });
}
