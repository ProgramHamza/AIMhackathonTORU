/**
 * Summaries mark source-linked key terms as [term](sourceIndex). A long passage is cited as
 * [^sourceIndex] instead: a small numbered marker that opens the passage and shows it on hover.
 */
const LINK = /\[([^\]^][^\]]*)\]\((\d+)\)|\[\^(\d+)\]/g;

export function parseLinked(text) {
  const parts = [];
  let last = 0;
  let marker = 0;
  for (const m of text.matchAll(LINK)) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    parts.push(m[3] === undefined
      ? { term: m[1], source: Number(m[2]) }
      : { marker: ++marker, source: Number(m[3]) });
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

export const plainText = (text) => text.replace(LINK, (_, term) => term ?? '');
