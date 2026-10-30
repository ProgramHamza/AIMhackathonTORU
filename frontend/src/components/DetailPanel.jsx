import { useEffect, useLayoutEffect, useRef } from 'react';
import { SourceLink } from './SourceLink';
import { formatDate } from '../lib/format';
import { useSources } from '../lib/SourceContext';
import { useT } from '../lib/i18n';

const sideLetter = (i) => String.fromCharCode(65 + i);

function Bar({ eyebrow, back }) {
  return (
    <div className="sticky top-0 z-10 -mx-6 flex min-h-12 items-center gap-4 border-b border-rule bg-panel px-6 py-3">
      {back ? (
        <button type="button" className="details-toggle text-left" onClick={back.onClick}>
          ← {back.label}
        </button>
      ) : (
        <p className="eyebrow m-0">{eyebrow}</p>
      )}
    </div>
  );
}

function Side({ source, label, citedFor }) {
  const { store } = useSources();
  const t = useT();
  const doc = store.getDocument(source.docId);
  return (
    <figure className="m-0 min-w-0 border-t border-rule pt-2">
      <figcaption className="flex flex-wrap items-baseline justify-between gap-x-3">
        <span className="label">{label}</span>
        <time className="text-muted">{formatDate(doc.date, t.lang)}</time>
      </figcaption>
      <p className="mt-0.5 mb-1.5 text-meta text-muted">
        <SourceLink source={source} citedFor={citedFor}>
          {doc.label || doc.type}
        </SourceLink>{' '}
        · {doc.department}
      </p>
      <blockquote className="m-0 border-l-2 border-rule pl-3 text-body leading-snug">“{store.getPassage(source)}”</blockquote>
    </figure>
  );
}

function ContradictionView({ item, headingRef }) {
  const t = useT();
  const high = item.severity === 'high';
  const review = item.kind === 'review';
  const sideLabel = (i) => t('sourceSide', { letter: sideLetter(i) });
  return (
    <article aria-labelledby="detail-heading" className="px-6 pt-2 pb-8">
      <Bar eyebrow={review ? t('reviewFindings') : t('contradictionCode', { code: item.code })} />
      <div className={`mt-2 border-l-4 pl-4 ${high ? 'border-l-alert' : 'border-l-discrepancy-ink'}`}>
        <div className="flex items-baseline justify-between gap-4">
          <h2 id="detail-heading" ref={headingRef} tabIndex={-1} className="panel-title m-0 focus:outline-none">
            {item.title}
          </h2>
          <span className="status-tag">{review ? t('differentTag') : t('unresolved')}</span>
        </div>
        <p className="mt-1.5 mb-0 text-body leading-snug">{item.description}</p>
        <p className="meta mt-1.5 mb-0">
          {high && <span className="text-alert">{t('highPriority')}</span>}
          {item.topic} · {t(item.sides.length === 1 ? 'sourcesOne' : 'sourcesCount', { n: item.sides.length })}
        </p>
      </div>

      <div className="mt-5 grid grid-cols-1 gap-x-5 gap-y-4 @lg:grid-cols-2">
        {item.sides.map((source, i) => (
          <Side key={i} source={source} label={sideLabel(i)} citedFor={`${item.code} ${item.title} — ${sideLabel(i)}`} />
        ))}
      </div>

      <p className="mt-5 mb-0 text-meta leading-relaxed">
        <span className="label mr-1.5">{t('whyReview')}</span>
        {item.reason}
      </p>
      <p className="meta mt-5 mb-0 border-t border-rule pt-3">{review ? t('reviewFooter') : t('unresolvedFooter')}</p>
    </article>
  );
}

/** The cited passage with the keyword's words in bold (ranges are offsets inside the passage). */
function Marked({ text, ranges }) {
  if (!ranges?.length) return text;
  const parts = [];
  let last = 0;
  for (const [a, b] of [...ranges].sort((x, y) => x[0] - y[0])) {
    if (a < last) continue;
    if (a > last) parts.push(text.slice(last, a));
    parts.push(<strong key={a} className="font-bold underline decoration-2 underline-offset-2">{text.slice(a, b)}</strong>);
    last = b;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

function SourceView({ citation, back, headingRef }) {
  const { store } = useSources();
  const t = useT();
  const doc = store.getDocument(citation.docId);
  const cited = new Set(citation.passageIds);
  return (
    <article aria-labelledby="detail-heading" className="source-view">
      <header className="source-heading">
      <Bar eyebrow={t('sourceOf', { type: doc.type })} back={back} />
      <h2 id="detail-heading" ref={headingRef} tabIndex={-1} className="panel-title mt-2 mb-1 focus:outline-none">
        {doc.title}
      </h2>
      </header>
      <div className="source-scroll" tabIndex={0} aria-label={t('documentContent')}>
      <p className="meta m-0">
        <time>
          {formatDate(doc.date, t.lang)}
          {doc.time ? ` · ${doc.time}` : ''}
        </time>{' '}
        {[doc.author, [doc.department, doc.facility].filter(Boolean).join(', ')].filter(Boolean).map((part) => ` · ${part}`)} ·{' '}
        <span className="mono">{doc.id}</span>
      </p>
      <p className="mt-3 mb-0 border-y border-rule py-2 text-meta">
        <span className="label mr-2">{t('openedFor')}</span>
        {citation.citedFor}
        <span className="text-muted">
          {' · '}
          {cited.size === 0 ? t('fullDocument') : cited.size === 1 ? t('passageOne') : t('passagesMany', { n: cited.size })}
        </span>
      </p>
      <div className="mt-4">
        {doc.sections.map((section, si) => (
          <section key={si} className="mb-4 last:mb-0">
            {section.heading && (
              <h3 className="mt-3 mb-1 text-[15px] leading-snug font-semibold text-ink">
                {cited.has(section.headingId) ? <mark data-cited="true" className="passage-cited">{section.heading}</mark> : section.heading}
              </h3>
            )}
            {section.paragraphs.map((paragraph, pi) => (
              <p key={pi} className="mt-0 mb-1.5 text-body leading-relaxed">
                {paragraph.map((seg, gi) =>
                  typeof seg === 'string' ? (
                    <span key={gi}>{seg}</span>
                  ) : cited.has(seg.id) ? (
                    <mark key={gi} data-cited="true" className="passage-cited">
                      <Marked text={seg.text} ranges={citation.marks?.[seg.id]} />
                    </mark>
                  ) : (
                    <span key={gi}>{seg.text}</span>
                  ),
                )}
              </p>
            ))}
          </section>
        ))}
      </div>
      <p className="meta mt-5 mb-0">{t('demoNote')}</p>
      </div>
    </article>
  );
}

function RecordView({ items, filter, onFilter, headingRef }) {
  const t = useT();
  const categories = [...new Set(items.map((i) => i.category))];
  const active = filter === 'all' || categories.includes(filter) ? filter : 'all';
  const options = [['all', t('all'), items.length], ...categories.map((c) => [c, c, items.filter((i) => i.category === c).length])];
  const groups = categories.filter((c) => active === 'all' || c === active);
  return (
    <article aria-labelledby="detail-heading" className="px-6 pt-2 pb-8">
      <Bar eyebrow={t('collectedFacts')} />
      <h2 id="detail-heading" ref={headingRef} tabIndex={-1} className="panel-title mt-2 mb-1 focus:outline-none">
        {t('collectedFacts')}
      </h2>
      <p className="meta m-0">{t('entriesNote', { n: items.length })}</p>
      <div role="group" aria-label={t('filterByCategory')} className="mt-4 flex flex-wrap gap-2">
        {options.map(([key, label, count]) => (
          <button key={key} type="button" aria-pressed={active === key} onClick={() => onFilter(key)} className="chip">
            {label} <span className="mono">{count}</span>
          </button>
        ))}
      </div>
      {groups.map((c) => (
        <section key={c} className="mt-5">
          <h3 className="label m-0 mb-1 text-ink">{c}</h3>
          <ul className="m-0 list-none p-0">
            {items
              .filter((i) => i.category === c)
              .map((i) => (
                <li key={i.id} className="flex items-baseline justify-between gap-3 border-b border-rule py-2 last:border-b-0">
                  <span className="min-w-0 text-body leading-snug">
                    {i.source ? (
                      <SourceLink source={i.source} citedFor={t('collectedFactsFor', { label: i.label })}>
                        {i.label}
                      </SourceLink>
                    ) : <span>{i.label}</span>}
                    {i.detail && <span className="text-meta text-muted"> · {i.detail}</span>}
                  </span>
                  <time className="shrink-0 text-muted">{i.when}</time>
                </li>
              ))}
          </ul>
        </section>
      ))}
    </article>
  );
}

/** Centered evidence dialog; background content is inert while open. */
export function DetailPanel({ detail, open, contradictions, record = [], onBack, onClose, recordFilter, onRecordFilter }) {
  const t = useT();
  const panelRef = useRef(null);
  const headingRef = useRef(null);
  const contradiction = detail?.kind === 'contradiction' ? contradictions.find((c) => c.id === detail.id) : null;
  const from = detail?.kind === 'source' ? detail.from : null;
  const fromContradiction = from?.kind === 'contradiction' ? contradictions.find((c) => c.id === from.id) : null;
  const backLabel = fromContradiction ? `${fromContradiction.code} ${fromContradiction.title}` : from?.kind === 'record' ? t('collectedFacts') : null;

  useEffect(() => {
    if (!open) return;
    const trapFocus = (event) => {
      if (event.key !== 'Tab') return;
      const controls = [...panelRef.current.querySelectorAll('a[href], button:not(:disabled), input, select, textarea, [tabindex="0"]')].filter(el => el.getClientRects().length);
      if (!controls.length) { event.preventDefault(); return; }
      const first = controls[0], last = controls[controls.length - 1];
      if (event.shiftKey && (document.activeElement === first || !controls.includes(document.activeElement))) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && (document.activeElement === last || !controls.includes(document.activeElement))) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', trapFocus);
    return () => document.removeEventListener('keydown', trapFocus);
  }, [open]);

  useLayoutEffect(() => {
    const panel = panelRef.current;
    if (!panel || !open) return;
    const target = detail?.kind === 'source' ? panel.querySelector('[data-cited="true"]') : null;
    const scroller = panel.querySelector('.source-scroll') || panel;
    if (target) {
      const top = target.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop;
      scroller.scrollTop = Math.max(0, top - scroller.clientHeight * 0.35);
    } else {
      scroller.scrollTop = 0;
    }
    headingRef.current?.focus({ preventScroll: true });
  }, [detail, open]);

  return (
    <>
    {open && <div className="evidence-backdrop" aria-hidden="true" onClick={onClose} />}
    <aside
      id="panel-detail"
      ref={panelRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby="detail-heading"
      className="drawer evidence-modal @container"
      data-open={open}
      data-source={detail?.kind === 'source'}
      inert={open ? undefined : ''}
    >
      <button type="button" className="evidence-close" aria-label={t('closeViewer')} onClick={onClose}><span aria-hidden="true">×</span></button>
      {contradiction ? (
        <ContradictionView item={contradiction} headingRef={headingRef} />
      ) : detail?.kind === 'source' ? (
        <SourceView
          citation={detail.citation}
          back={backLabel ? { label: backLabel, onClick: () => onBack(from) } : null}
          headingRef={headingRef}
        />
      ) : detail?.kind === 'record' ? (
        <RecordView items={record} filter={recordFilter} onFilter={onRecordFilter} headingRef={headingRef} />
      ) : null}
    </aside>
    </>
  );
}

