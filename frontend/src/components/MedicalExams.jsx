import { useEffect, useMemo, useRef, useState } from 'react';
import { SourceLink } from './SourceLink';
import { orderExams } from '../lib/exams';
import { formatDate } from '../lib/format';
import { useT } from '../lib/i18n';

/** Facts grouped by topic, in record order; topics with nothing documented go last. */
function groupFacts(facts) {
  const groups = new Map();
  for (const item of facts) {
    const id = item.categoryId ?? item.category;
    if (!groups.has(id)) groups.set(id, { id, name: item.category, items: [] });
    if (!item.missing) groups.get(id).items.push(item);
  }
  const all = [...groups.values()];
  return [...all.filter((g) => g.items.length), ...all.filter((g) => !g.items.length)];
}

/** Multi-select topic filter: every click applies at once; nothing selected means all topics. */
function TopicFilter({ groups, selected, onChange }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => { if (!ref.current?.contains(e.target)) setOpen(false); };
    const onKey = (e) => {
      if (e.key !== 'Escape') return;
      e.stopPropagation();
      setOpen(false);
      ref.current?.querySelector('.topic-filter-button')?.focus();
    };
    document.addEventListener('pointerdown', onDown);
    document.addEventListener('keydown', onKey, true);
    return () => {
      document.removeEventListener('pointerdown', onDown);
      document.removeEventListener('keydown', onKey, true);
    };
  }, [open]);

  const toggle = (id) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onChange(next);
  };
  const names = groups.filter((g) => selected.has(g.id)).map((g) => g.name);
  const label = names.length === 0 ? t('allTopics') : names.length === 1 ? names[0] : t('topicsSelected', { n: names.length });

  return (
    <div ref={ref} className="topic-filter">
      <button
        type="button"
        className="topic-filter-button"
        aria-haspopup="true"
        aria-expanded={open}
        aria-controls="topic-filter-menu"
        data-active={names.length > 0}
        onClick={() => setOpen((v) => !v)}
      >
        <svg width="13" height="13" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M3 5h14M6 10h8M8.5 15h3" stroke="currentColor" strokeWidth="1.7" /></svg>
        <span className="topic-filter-label">{label}</span>
        <svg className="topic-filter-caret" width="11" height="11" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m5 8 5 5 5-5" stroke="currentColor" strokeWidth="1.8" /></svg>
      </button>
      {open && (
        <div id="topic-filter-menu" className="topic-filter-menu" role="group" aria-label={t('filterTopics')}>
          <div className="topic-filter-actions">
            <button type="button" onClick={() => onChange(new Set())} disabled={!names.length}>{t('showAll')}</button>
          </div>
          <ul>
            {groups.map((g) => {
              const empty = !g.items.length;
              return (
                <li key={g.id}>
                  <label data-empty={empty}>
                    <input type="checkbox" checked={selected.has(g.id)} disabled={empty} onChange={() => toggle(g.id)} />
                    <span className="topic-filter-name">{g.name}</span>
                    <span className="topic-filter-count">{empty ? '—' : g.items.length}</span>
                  </label>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

function FactList({ groups, selected }) {
  const t = useT();
  const shown = groups.filter((g) => g.items.length && (selected.size === 0 || selected.has(g.id)));
  const missing = selected.size === 0 ? groups.filter((g) => !g.items.length) : [];
  return (
    <div className="fact-browser" tabIndex={0} aria-label={t('collectedFacts')}>
      {shown.map((g) => (
        <section key={g.id} className="fact-section" aria-labelledby={`facts-${g.id}`}>
          <h3 id={`facts-${g.id}`}>
            <span>{g.name}</span>
            <span className="fact-section-count">{g.items.length}</span>
          </h3>
          <ul>
            {g.items.map((item) => (
              <li key={item.id}>
                <span className="fact-label">
                  {item.source ? (
                    <SourceLink source={item.source} citedFor={t('collectedFactsFor', { label: item.label })}>{item.label}</SourceLink>
                  ) : item.label}
                </span>
                <span className="fact-meta">
                  <time>{item.when}</time>
                  {item.detail && <span>{item.detail}</span>}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ))}
      {missing.length > 0 && (
        <p className="fact-missing">
          <span className="label">{t('noFacts')}</span> {missing.map((g) => g.name).join(' · ')}
        </p>
      )}
    </div>
  );
}

export function MedicalExams({ documents, encounter, task }) {
  const t = useT();
  const [view, setView] = useState('documents');
  const [selected, setSelected] = useState(() => new Set()); // topic IDs stay stable across languages
  const items = useMemo(() => orderExams(documents, task.curated ? encounter.important : [], 'date'), [documents, encounter.important, task.curated]);
  const dates = [...new Set(items.map(doc => doc.date))];
  const groups = useMemo(() => groupFacts(encounter.record ?? []), [encounter.record]);
  const total = groups.reduce((n, g) => n + g.items.length, 0);
  const visible = groups.filter((g) => selected.size === 0 || selected.has(g.id)).reduce((n, g) => n + g.items.length, 0);
  const remove = (id) => setSelected((prev) => { const next = new Set(prev); next.delete(id); return next; });
  return (
    <aside className="exam-sidebar documents-sidebar" aria-label={t('documents')}>
      <div className="exam-content">
        <header className="exam-header">
          <h2>{t('documents')}</h2>
          <div className="document-views" role="group" aria-label={t('browseViews')}>
            <button type="button" aria-pressed={view === 'documents'} onClick={() => setView('documents')}>{t('byDocument')}</button>
            <button type="button" aria-pressed={view === 'types'} onClick={() => setView('types')}>{t('byType')}</button>
          </div>
          {view === 'types' && <>
            <TopicFilter groups={groups} selected={selected} onChange={setSelected} />
            {selected.size > 0 && (
              <ul className="topic-chips" aria-label={t('activeFilters')}>
                {groups.filter((g) => selected.has(g.id)).map((g) => (
                  <li key={g.id}>
                    <button type="button" aria-label={t('removeFilter', { name: g.name })} onClick={() => remove(g.id)}>
                      {g.name} <span aria-hidden="true">×</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <p aria-live="polite">{selected.size ? t('factsShown', { n: visible, total }) : t('factsCount', { n: total })}</p>
          </>}
        </header>
        {view === 'documents' ? <ol className="document-timeline" aria-label={t('timelineAria')}>
          {dates.map(date => <li key={date} className="document-timeline-day">
            <time className="document-timeline-date" dateTime={date}>{formatDate(date, t.lang)}</time>
            <ul>
              {items.filter(doc => doc.date === date).map(doc => <li key={doc.id} className="document-timeline-entry">
                <SourceLink source={doc.source} citedFor={t('documentFor', { type: doc.type })}>{doc.type}</SourceLink>
                <p>{doc.department || doc.category}</p>
                {doc.relevant && <span className="document-timeline-context">{t('taskSource')}</span>}
              </li>)}
            </ul>
          </li>)}
        </ol> : <FactList groups={groups} selected={selected} />}
      </div>
    </aside>
  );
}
