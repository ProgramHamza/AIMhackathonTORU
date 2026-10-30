import { LinkedText } from './LinkedText';
import { SourceLink } from './SourceLink';
import { plainText } from '../lib/linkedText';

/** One chronological line through the summary points and the other medical history. */
export function Timeline({ summary, history }) {
  const events = [
    ...summary.map((p) => ({ id: p.text, date: p.date, when: p.when, kind: 'summary', point: p, key: Boolean(p.key), planned: Boolean(p.planned) })),
    ...history.map((h) => ({ id: h.id, date: h.year, when: h.when ?? h.year, kind: 'history', item: h, key: false, planned: false })),
  ].sort((a, b) => b.date.localeCompare(a.date));

  return (
    <ol className="timeline" aria-label="Patient timeline, newest first">
      {events.map((e) => (
        <li key={e.id} className="timeline-item" data-key={e.key} data-planned={e.planned} data-kind={e.kind}>
          <time className="block text-muted">
            {e.when}
            {e.planned && <span className="ml-2 font-sans text-accent">Planned</span>}
          </time>
          {e.kind === 'summary' ? (
            <p className="m-0 text-body leading-snug">
              <LinkedText text={e.point.text} sources={[e.point.source]} citedFor={`Patient summary: ${plainText(e.point.text)}`} />
            </p>
          ) : (
            <p className="m-0 text-meta leading-snug">
              <SourceLink source={e.item.source} citedFor={`Other medical history: ${e.item.label}`}>
                {e.item.label}
              </SourceLink>
              <span className="text-muted"> · {e.item.status}</span>
            </p>
          )}
        </li>
      ))}
    </ol>
  );
}
