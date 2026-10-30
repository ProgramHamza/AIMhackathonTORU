import { useEffect, useRef, useState } from 'react';
import { PanelHeader } from './PanelHeader';
import { InfoItem } from './InfoItem';
import { useT } from '../lib/i18n';

export function ImportantPanel({ encounter, task }) {
  const t = useT();
  const scrollRef = useRef(null);
  const contentRef = useRef(null);
  const timer = useRef(null);
  const [scrolling, setScrolling] = useState(false);
  const [moreBelow, setMoreBelow] = useState(false);
  const updateOverflow = () => {
    const el = scrollRef.current;
    if (el) setMoreBelow(el.scrollHeight - el.clientHeight - el.scrollTop > 8);
  };
  useEffect(() => {
    const observer = new ResizeObserver(updateOverflow);
    observer.observe(scrollRef.current);
    observer.observe(contentRef.current);
    updateOverflow();
    return () => { observer.disconnect(); clearTimeout(timer.current); };
  }, []);
  const onScroll = () => {
    setScrolling(true);
    updateOverflow();
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setScrolling(false), 750);
  };
  const byId = new Map(encounter.contradictions.map((c) => [c.id, c]));
  return (
    <section id="panel-important" aria-labelledby="important-heading" className="panel important-panel @container">
      <div ref={scrollRef} className="important-scroll" data-scrolling={scrolling} onScroll={onScroll} tabIndex={0} aria-label={t('importantScroll')}>
      <div ref={contentRef}>
      <PanelHeader
        id="important-heading"
        title={t('importantTitle')}
        kicker={
          <p className="m-0 mb-3 text-meta">
            <span className="eyebrow mr-2">{t('task')}</span>
            <span className="font-semibold text-ink">{task.label}</span>
            {task.role && <span className="text-muted"> · {task.role}</span>}
          </p>
        }
      >
      </PanelHeader>
      <div className="px-6 pb-6">
        {task.curated ? (
          <ol className="m-0 list-none p-0">
            {encounter.important.map((item) => (
              <InfoItem key={item.id} item={item} contradiction={item.contradictionId ? byId.get(item.contradictionId) : undefined} />
            ))}
          </ol>
        ) : (
          <p className="my-6 text-body text-muted">{t('noSelection')}</p>
        )}
        <p className="mt-2 mb-0 border-t border-rule pt-3 text-meta text-muted">
          {t('sourceDocsHint')}
        </p>
      </div>
      </div>
      </div>
      {moreBelow && <button type="button" className="important-scroll-hint" aria-label={t('scrollMore')} onClick={() => scrollRef.current?.scrollBy({ top: scrollRef.current.clientHeight * 0.65, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' })}>
        <svg width="16" height="16" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m4 7 6 6 6-6" stroke="currentColor" strokeWidth="1.5" /></svg>
      </button>}
    </section>
  );
}
