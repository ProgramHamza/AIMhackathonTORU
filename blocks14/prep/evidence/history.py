"""Source-linked documented history; never equates a document date with event onset."""
from datetime import date
import hashlib
import json
from typing import Literal

from pydantic import Field
from prep.evidence.schema import Model, DerivedFact
from prep.evidence.normalization import canonicalize

VERSION='documented-history-v1'


class HistoryPoint(Model):
    fact_id: str
    source_fact_ids: list[str]
    value: float
    unit: str
    ordering_date: str | None
    ordering_basis: Literal['clinical_date','document_date','unknown']
    document_dates: list[str]


class Selection(Model):
    as_of: str
    fact_ids: list[str] = Field(default_factory=list)
    undated_fact_ids: list[str] = Field(default_factory=list)
    meaning: str


def source_dates(bundle):
    documents={d.id:d for d in bundle.documents}
    passages={p.id:p for p in bundle.passages}
    return documents,passages


def cutoff(bundle,as_of=None):
    if as_of:
        return date.fromisoformat(as_of).isoformat()
    known=[d.document_date.isoformat() for d in bundle.documents if d.document_date]
    if not known:
        raise ValueError('An explicit as_of date is required when documents have no dates')
    return max(known)


def measurement_history(bundle,concept,*,as_of=None):
    end=cutoff(bundle,as_of)
    documents,passages=source_dates(bundle)
    groups={}
    for f in bundle.facts:
        if (canonicalize(f)[0] or f.concept)!=concept or f.value.kind!='measurement' or f.assertion!='affirmed' or f.subject!='patient':
            continue
        if f.clinical_status in ('planned','recommended'):
            continue
        docs=[documents[i] for i in {passages[r.passage_id].document_id for r in f.evidence}]
        dates=sorted({d.document_date.isoformat() for d in docs if d.document_date})
        # A later letter cannot supply evidence to an earlier snapshot.
        if dates and max(dates)>end:
            continue
        t=f.clinical_time
        if t.precision=='day' and t.basis in ('explicit','contextual'):
            ordering,basis=t.value,'clinical_date'
        elif f.clinical_status=='historical' or t.precision not in ('day','unknown'):
            ordering,basis=None,'unknown'
        elif dates:
            ordering,basis=max(dates),'document_date'
        else:
            ordering,basis=None,'unknown'
        if ordering and ordering>end:
            continue
        # Do not collapse same-valued results in distinct documents or source blocks.
        core=tuple(sorted({r.passage_id for r in f.evidence if passages[r.passage_id].kind!='heading'}))
        key=(ordering,basis,f.value.quantity.value,f.value.quantity.unit,f.value.site,f.value.method,core)
        groups.setdefault(key,[]).append(f)
    points=[]
    for (ordering,basis,value,unit,site,method,core),fs in groups.items():
        f=min(fs,key=lambda x:(x.extraction_method!='rule',x.id))
        dates=sorted({documents[passages[r.passage_id].document_id].document_date.isoformat()
            for member in fs for r in member.evidence if documents[passages[r.passage_id].document_id].document_date})
        points.append(HistoryPoint(fact_id=f.id,source_fact_ids=sorted(x.id for x in fs),value=value,unit=unit,
            ordering_date=ordering,ordering_basis=basis,document_dates=dates))
    return sorted(points,key=lambda p:(p.ordering_date or '',p.fact_id))


def latest_measurements(bundle,concept,*,as_of=None):
    points=measurement_history(bundle,concept,as_of=as_of)
    dated=[p for p in points if p.ordering_date]
    latest=max((p.ordering_date for p in dated),default=None)
    return Selection(as_of=cutoff(bundle,as_of),fact_ids=[p.fact_id for p in dated if p.ordering_date==latest],
        undated_fact_ids=[p.fact_id for p in points if not p.ordering_date],
        meaning='Latest day-orderable evidence for this measurement; ties retained. Undated IDs include partial/relative dates and unanchored history. Document-date ordering is not a measurement date or proof that later results are absent.')


def latest_discharge_medications(bundle,*,as_of=None):
    end=cutoff(bundle,as_of)
    docs,passages=source_dates(bundle)
    lists={}
    undated=[]
    for f in bundle.facts:
        if f.category!='medications' or f.value.kind!='medication' or f.assertion!='affirmed' or f.subject!='patient':
            continue
        if f.clinical_status in ('discontinued','historical','resolved'):
            continue
        source_ids={passages[r.passage_id].document_id for r in f.evidence
            if (passages[r.passage_id].section or '').casefold() in ('entlassungsmedikation','medikation bei entlassung')}
        for doc_id in source_ids:
            dt=docs[doc_id].document_date
            if dt is None:
                undated.append(f.id)
            elif dt.isoformat()<=end:
                lists.setdefault(dt.isoformat(),set()).add(f.id)
    latest=max(lists,default=None)
    return Selection(as_of=end,fact_ids=sorted(lists[latest]) if latest else [],undated_fact_ids=sorted(set(undated)),
        meaning='Medication entries in the latest dated discharge list(s), not proof of current use or administration. Earlier lists remain in source history.')


def weight_change(bundle,*,as_of=None):
    points=measurement_history(bundle,'body_weight',as_of=as_of)
    dated=[p for p in points if p.ordering_date and p.unit in ('kg','g')]
    if len({p.ordering_date for p in dated})<2:
        return None
    first_date,last_date=min(p.ordering_date for p in dated),max(p.ordering_date for p in dated)
    first=[p for p in dated if p.ordering_date==first_date]
    last=[p for p in dated if p.ordering_date==last_date]
    kg=lambda p:p.value/(1000 if p.unit=='g' else 1)
    # Conflicting endpoint values must not be silently resolved by ID ordering.
    if len({kg(p) for p in first})!=1 or len({kg(p) for p in last})!=1:
        return None
    a,b=first[0],last[0]
    result=kg(b)-kg(a)
    identity=hashlib.sha256(json.dumps([VERSION,a.fact_id,b.fact_id,result]).encode()).hexdigest()[:24]
    return DerivedFact(id='derived-weight-'+identity,category='vitals',concept='body_weight_change',label='Change between earliest and latest dated weight evidence',
        calculation='weight_change',calculation_version=VERSION,input_fact_ids=[a.fact_id,b.fact_id],result={'value':round(result,4),'unit':'kg'},
        explanation=f'{kg(b):g} kg minus {kg(a):g} kg = {result:g} kg. Evidence ordered at {a.ordering_date} ({a.ordering_basis}) and {b.ordering_date} ({b.ordering_basis}); document dates are not asserted measurement dates.')
