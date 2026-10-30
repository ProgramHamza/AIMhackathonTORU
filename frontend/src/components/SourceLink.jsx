import { refKey } from '../lib/sources';
import { formatDate } from '../lib/format';
import { useSources } from '../lib/SourceContext';
import { useT } from '../lib/i18n';

/** Clickable reference to a source document passage; opens it in the drawer. */
export function SourceLink({ source, citedFor, label, marker = false, children }) {
  const { openSource, activeKey, store } = useSources();
  const t = useT();
  const doc = store.getDocument(source.docId);
  const date = formatDate(doc.date, t.lang);
  const open = t('openSource', { title: doc.title, date });

  if (marker) {
    const passage = store.getPassage(source);
    return (
      <a
        href={`#source-${source.docId}`}
        className="source-marker"
        data-active={activeKey === refKey(source)}
        title={`${passage}\n— ${doc.title} · ${date}`}
        aria-label={`${t('passageN', { n: children, text: passage })}. ${open}`}
        onClick={(e) => {
          e.preventDefault();
          e.currentTarget.focus({ preventScroll: true });
          openSource(source, citedFor);
        }}
      >
        {children}
      </a>
    );
  }

  if (children) {
    return (
      <a
        href={`#source-${source.docId}`}
        className="inline-source"
        data-active={activeKey === refKey(source)}
        title={doc.label || `${doc.title} · ${date}`}
        aria-label={`${typeof children === 'string' ? children : citedFor}. ${open}`}
        onClick={(e) => {
          e.preventDefault();
          e.currentTarget.focus({ preventScroll: true });
          openSource(source, citedFor);
        }}
      >
        {children}
      </a>
    );
  }

  return (
    <button
      type="button"
      className="source-link"
      data-active={activeKey === refKey(source)}
      aria-label={open}
      onClick={() => openSource(source, citedFor)}
    >
      {label ?? (doc.label || (
        <>
          {doc.type} · <span className="whitespace-nowrap">{date}</span>
        </>
      ))}
      <span aria-hidden="true" className="whitespace-nowrap"> ↗</span>
    </button>
  );
}
