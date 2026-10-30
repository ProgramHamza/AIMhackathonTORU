import { useSources } from '../lib/SourceContext';
import { useT } from '../lib/i18n';
import { ageOn, formatDate, todayIso } from '../lib/format';

function Field({ term, children }) {
  return (
    <div className="grid grid-cols-[88px_minmax(0,1fr)] gap-x-3 py-0.5">
      <dt className="label pt-px">{term}</dt>
      <dd className="m-0 text-meta leading-snug">{children}</dd>
    </div>
  );
}

function ContradictionList({ contradictions }) {
  const { focusContradiction, activeContradiction } = useSources();
  const t = useT();
  return (
    <section aria-labelledby="attention-heading" className="border-t border-rule px-5 pt-4 pb-4">
      <h2 id="attention-heading" className="m-0 mb-2.5 flex items-center gap-2 text-meta font-semibold text-alert">
        <span aria-hidden="true" className="inline-grid h-3.5 w-3.5 place-items-center border border-alert text-[9px] leading-none">!</span>
        {t(contradictions.length === 1 ? 'contradictionsOne' : 'contradictionsMany', { n: contradictions.length })}
      </h2>
      <ul className="m-0 flex list-none flex-col gap-1 p-0">
        {contradictions.map((c) => (
          <li key={c.id} className="attention-item" data-active={activeContradiction === c.id}>
            <button
              type="button"
              aria-current={activeContradiction === c.id ? 'true' : undefined}
              className="attention-button text-ink"
              title={c.title}
              onClick={() => focusContradiction(c.id)}
            >
              <span className="mono mr-2 text-muted">{c.code}</span>
              {c.title}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function PatientPanel({ patient, encounter }) {
  const t = useT();
  const today = todayIso();
  return (
    <aside aria-label={t('patientProfile')} className="panel panel-patient flex flex-col border-r-2 border-rule-strong">
      <section aria-labelledby="patient-name" className="px-5 pt-4 pb-4">
        <h1 id="patient-name" className="mt-0 mb-1 text-[24px] leading-tight font-semibold tracking-[-0.02em]">
          <span>{patient.familyName}</span>, {patient.givenName}
        </h1>
        <dl className="m-0">
          <Field term={t('born')}>
            <span className="whitespace-nowrap">{formatDate(patient.birthDate, t.lang)}</span> · {t.term(patient.sex)}
          </Field>
          <Field term={t('age')}>
            <span className="whitespace-nowrap">{t('years', { n: ageOn(patient.birthDate, today) })}</span>
          </Field>
          <Field term={t('patientId')}>
            <span className="mono">{patient.id}</span>
          </Field>
          {encounter.asOf && (
            <Field term={t('recordsAsOf')}>{formatDate(encounter.asOf, t.lang)}</Field>
          )}
          {encounter.date && (
            <Field term={t('encounter')}>
              <span>{formatDate(encounter.date, t.lang)}</span>
            </Field>
          )}
          <Field term={t('context')}>{encounter.context}</Field>
        </dl>

      </section>

      <ContradictionList contradictions={encounter.contradictions} />

      {encounter.reviewFindings?.length > 0 && (
        <ReviewFindings findings={encounter.reviewFindings} />
      )}


    </aside>
  );
}

function ReviewFindings({ findings }) {
  const { focusContradiction } = useSources();
  const t = useT();
  return (
    <section className="border-t border-rule px-5 py-3" aria-label={t('differentFindingsAria')}>
      <h2 className="m-0 mb-2 text-meta font-semibold text-muted">{t('differentFindings')}</h2>
      {findings.map((item) => (
        <button key={item.id} type="button" className="attention-button text-ink" onClick={() => focusContradiction(item.id)}>
          {item.title} · {t('review')}
        </button>
      ))}
    </section>
  );
}
