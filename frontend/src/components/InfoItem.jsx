import { LinkedText } from './LinkedText';
import { useSources } from '../lib/SourceContext';
import { useT } from '../lib/i18n';

export function InfoItem({ item, contradiction }) {
  const { focusContradiction, activeContradiction } = useSources();
  const t = useT();
  const headingId = `${item.id}-heading`;
  const tone = contradiction ? (contradiction.severity === 'high' ? 'alert' : 'review') : 'none';
  return (
    <li className="border-b border-rule last:border-b-0">
      <article id={`important-${item.id}`} aria-labelledby={headingId} data-tone={tone} className="info-row">
        <div className="flex flex-col items-start gap-y-1">
          <h3 id={headingId} className="row-title m-0 leading-snug">
            {item.heading}
          </h3>
          <span className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
            <time className="text-muted whitespace-nowrap">{item.recency}</time>
            {contradiction && (
              <button
                type="button"
                className="conflict-tag"
                data-tone={tone}
                data-active={activeContradiction === contradiction.id}
                aria-label={t('openContradiction', { code: contradiction.code, title: contradiction.title })}
                onClick={() => focusContradiction(contradiction.id)}
              >
                {t('contradictionTag', { code: contradiction.code })}
              </button>
            )}
          </span>
        </div>
        <p className="m-0 min-w-0 max-w-[72ch] text-body leading-snug text-ink">
          <LinkedText text={item.summary} sources={item.sources} citedFor={item.heading} />
        </p>
      </article>
    </li>
  );
}
