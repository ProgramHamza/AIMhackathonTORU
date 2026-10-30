"""Bounded contradiction rules. Review candidates are NOT display-ready contradictions."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
from typing import Literal

from pydantic import Field
from prep.evidence.schema import Model, EvidenceBundle, Contradiction, DerivedFact
from prep.evidence.normalization import bundle_hash, canonicalize, laterality
from prep.extraction.source_checks import source_dates

VERSION = 'contradictions-v1'
BMI_VERSION = 'bmi-kg-m2-v1'
BMI_ABSOLUTE_MARGIN = 0.5
BMI_RELATIVE_MARGIN = 0.03


class Assessment(Model):
    contradiction_id: str
    rule: Literal['bmi_same_block', 'explicit_same_event_dates', 'document_encounter_dates', 'summary_laterality']
    scope: str
    requires_review: bool
    assumptions: list[str]


class Diagnostic(Model):
    code: str
    fact_ids: list[str]
    explanation: str


class ContradictionReport(Model):
    schema_version: Literal['1.0.0'] = '1.0.0'
    detector_version: str = VERSION
    source_evidence_version: str
    source_bundle_sha256: str
    derived_facts: list[DerivedFact] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    assessments: list[Assessment] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)

    def validate_against(self, bundle):
        if self.model_dump() != detect_contradictions(bundle).model_dump():
            raise ValueError('Stale or modified contradiction report; rebuild from source bundle')


def stable_id(prefix, *parts):
    return prefix + hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]


def concept(fact):
    return canonicalize(fact)[0] or fact.concept


def explicit_event(fact, documents):
    # Existing extraction IDs identify source spans, not established clinical events.
    if not fact.event_id or any(fact.event_id.startswith(doc + ':span:') for doc in documents):
        return None
    return fact.event_id


def evidence_union(facts, extras=()):
    refs = [r for f in facts for r in f.evidence] + list(extras)
    return [r for _, r in sorted({(r.passage_id,r.start,r.end,r.quote):r for r in refs}.items())]


def source_resolution(fact):
    """Half a displayed numeric step; None if no matching source numeral exists."""
    value = fact.value.quantity.value
    steps = []
    for ref in fact.evidence:
        for token in re.findall(r'(?<![\w.])\d+(?:[.,]\d+)?(?!\w)', ref.quote):
            if float(token.replace(',', '.')) == value:
                decimals = len(re.split('[.,]',token)[1]) if re.search('[.,]',token) else 0
                steps.append(0.5 * 10 ** -decimals)
    return max(steps) if steps else None


def labelled_bmi_input_supported(fact):
    """Require the number and unit together under the correct source label."""
    patterns = {
        'body_height': r'(?:Körpergröße|Größe|height)\s*:?\s*(\d+(?:[.,]\d+)?)\s*(cm|m)\b',
        'body_weight': r'(?:Körpergewicht|Gewicht|weight)\s*:?\s*(\d+(?:[.,]\d+)?)\s*(kg|g)\b',
        'body_mass_index': r'\b(?:BMI|body mass index)\s*:?\s*(\d+(?:[.,]\d+)?)(?![\d.,])(?:\s*(kg/m[²2]))?',
    }
    c=concept(fact)
    for ref in fact.evidence:
        for match in re.finditer(patterns[c],ref.quote,re.I):
            unit=(match[2] or 'kg/m2').replace('²','2')
            if float(match[1].replace(',','.'))==fact.value.quantity.value and unit==fact.value.quantity.unit.replace('²','2'):
                return True
    return False


def detect_contradictions(bundle):
    # Also validate callers that mutated an already-created Pydantic object.
    bundle = EvidenceBundle.model_validate(bundle.model_dump(mode='json'))
    passages = {p.id:p for p in bundle.passages}
    documents = {d.id:d for d in bundle.documents}
    report = ContradictionReport(source_evidence_version=bundle.manifest.evidence_version,
        source_bundle_sha256=bundle_hash(bundle))
    facts = sorted(bundle.facts, key=lambda f:f.id)

    def doc_ids(f):
        return {passages[r.passage_id].document_id for r in f.evidence}

    def eligible(f):
        return f.assertion == 'affirmed' and f.subject == 'patient'

    def add(kind, status, rule, scope, claims, explanation, assumptions, derived=(), extras=()):
        ids = sorted({f.id for f in claims} | {d.id for d in derived})
        cid = stable_id('conflict-', VERSION, rule, scope)
        previous = next((c for c in report.contradictions if c.id==cid), None)
        if previous is not None:
            previous.claim_ids = sorted(set(previous.claim_ids) | set(ids))
            previous.evidence = evidence_union(claims, [*previous.evidence,*extras])
            return
        report.contradictions.append(Contradiction(id=cid, kind=kind, status=status, claim_ids=ids,
            explanation=explanation, evidence=evidence_union(claims,extras), detector_version=VERSION, review_method='rules'))
        report.assessments.append(Assessment(contradiction_id=cid,rule=rule,scope=scope,
            requires_review=status!='accepted',assumptions=assumptions))

    # BMI is compared only within one source paragraph/table block. A shared heading
    # or document date does not establish contemporaneous measurements.
    blocks = defaultdict(lambda: defaultdict(list))
    for f in facts:
        c = concept(f)
        if eligible(f) and f.category == 'vitals' and f.value.kind == 'measurement' and c in {'body_height','body_weight','body_mass_index'}:
            for pid in {r.passage_id for r in f.evidence if passages[r.passage_id].kind != 'heading'}:
                blocks[pid][c].append(f)
    for pid, values in sorted(blocks.items()):
        if not all(c in values for c in ('body_height','body_weight','body_mass_index')):
            continue
        members = [f for fs in values.values() for f in fs]
        def skip(code, explanation):
            report.diagnostics.append(Diagnostic(code=code,fact_ids=sorted({f.id for f in members}),explanation=explanation))
        selected = {}
        for c, fs in values.items():
            signatures = {json.dumps({'value':f.value.model_dump(), 'time':f.clinical_time.model_dump(),
                'status':f.clinical_status},sort_keys=True) for f in fs}
            if len(signatures) != 1:
                break
            selected[c] = min(fs,key=lambda f:(f.extraction_method!='rule',f.id))
        if len(selected)!=3:
            skip('ambiguous_bmi_inputs','Multiple distinct values, methods or times in the same block; no BMI comparison.')
            continue
        h,w,b = (selected[c] for c in ('body_height','body_weight','body_mass_index'))
        times = {(f.clinical_time.precision,f.clinical_time.value,f.clinical_time.end,f.clinical_time.basis) for f in (h,w,b)}
        events = {explicit_event(f,documents) for f in (h,w,b)} - {None}
        if len(times)>1 or len(events)>1 or any(f.clinical_status in ('historical','planned','recommended') for f in (h,w,b)):
            skip('noncontemporaneous_bmi_inputs','Inputs do not establish one contemporaneous measurement block.')
            continue
        text = passages[pid].text
        if re.search(r'\b(?:früher|zuvor|damals|historisch|geschätzt|circa|etwa|ungefähr|ca\.)',text,re.I) or len(source_dates(text))>1:
            skip('qualified_bmi_block','Historical or approximate wording requires review rather than arithmetic contradiction.')
            continue
        units = (h.value.quantity.unit,w.value.quantity.unit,b.value.quantity.unit)
        if units[0] not in ('cm','m') or units[1] not in ('kg','g') or units[2] not in ('kg/m2','kg/m²'):
            skip('unsupported_bmi_units','BMI calculation supports explicit cm/m, kg/g and kg/m2 only.')
            continue
        if not all(labelled_bmi_input_supported(f) for f in (h,w,b)):
            skip('unsupported_bmi_source_fields','Number, unit and measurement label are not jointly supported by a cited source span.')
            continue
        scales = (0.01 if units[0]=='cm' else 1, 0.001 if units[1]=='g' else 1)
        height,weight,recorded = h.value.quantity.value*scales[0],w.value.quantity.value*scales[1],b.value.quantity.value
        resolutions = [source_resolution(f) for f in (h,w,b)]
        if any(x is None for x in resolutions):
            skip('unconfirmed_bmi_numeral','A structured input numeral is not present in its cited source.')
            continue
        dh,dw,db = resolutions[0]*scales[0],resolutions[1]*scales[1],resolutions[2]
        if height<=dh or weight<=dw or recorded<=0:
            skip('invalid_bmi_inputs','Nonpositive inputs or rounding intervals prevent a valid BMI calculation.')
            continue
        calculated = weight/height**2
        low,high = (weight-dw)/(height+dh)**2,(weight+dw)/(height-dh)**2
        derived = DerivedFact(id=stable_id('derived-',BMI_VERSION,pid,h.id,w.id),category='vitals',concept='body_mass_index',
            label='Calculated BMI from co-located recorded height and weight',calculation='bmi',calculation_version=BMI_VERSION,
            input_fact_ids=[w.id,h.id],result={'value':round(calculated,4),'unit':'kg/m2'},
            explanation=f'weight_kg / height_m² = {weight:g} / {height:g}² = {calculated:.4f}. Source rounding interval: {low:.4f}–{high:.4f}.')
        report.derived_facts.append(derived)
        separation = max(low-(recorded+db),(recorded-db)-high,0)
        margin = max(BMI_ABSOLUTE_MARGIN,BMI_RELATIVE_MARGIN*calculated)
        if separation > margin:
            # Exact copied blocks with matching time metadata count once; all input
            # facts and citations remain attached. This can conservatively undercount
            # coincidentally identical blocks; it never invents a second disagreement.
            scope = 'event:' + next(iter(events)) if events else stable_id('measurement-block-',text,sorted(times))
            add('numeric_inconsistency','accepted','bmi_same_block',scope,members,
                f'Recorded BMI {recorded:g} kg/m² differs from {calculated:.2f} kg/m² calculated using the height and weight in the same source block. Rounding intervals remain separated by {separation:.2f}, above the conservative margin {margin:.2f}.',
                ['Same source measurement block and compatible time metadata.',
                 'Explicit units; source rounding intervals plus max(0.5 kg/m², 3% of calculated BMI) margin.',
                 'A documentation inconsistency, not a diagnosis; the recorded value is preserved.'],derived=[derived])

    # Dates: accepted only with established shared event identity, not mere co-occurrence.
    events, encounters = defaultdict(list), defaultdict(list)
    for f in facts:
        if not eligible(f) or f.value.kind!='event' or f.clinical_status!='completed':
            continue
        if f.clinical_time.precision!='day' or f.clinical_time.basis!='explicit':
            continue
        if f.clinical_time.value not in source_dates('\n'.join(r.quote for r in f.evidence)):
            report.diagnostics.append(Diagnostic(code='unconfirmed_event_date',fact_ids=[f.id],
                explanation='The explicit structured date is not a valid date in its cited source; excluded from comparison.'))
            continue
        event = explicit_event(f,documents)
        if event:
            events[(event,concept(f))].append(f)
        if f.category=='encounters' and concept(f) in ('admission','discharge') and len(doc_ids(f))==1:
            encounters[(next(iter(doc_ids(f))),concept(f))].append(f)
    accepted_date_sets = []
    for (event,c), members in sorted(events.items()):
        dates = sorted({f.clinical_time.value for f in members})
        if len(dates)<2:
            continue
        accepted_date_sets.append({f.id for f in members})
        add('event_date','accepted','explicit_same_event_dates',event+'|'+c,members,
            f'The same explicitly linked {c} event has conflicting recorded dates: {", ".join(dates)}.',
            ['Upstream event_id identifies one established event, not a source-span ID.',
             'Only affirmed completed events with explicit day dates are compared.'])
    for (doc,c), members in sorted(encounters.items()):
        dates = sorted({f.clinical_time.value for f in members})
        known_events = {explicit_event(f,documents) for f in members} - {None}
        if len(dates)<2 or len(known_events)>1 or any({f.id for f in members} <= ids for ids in accepted_date_sets):
            continue
        add('event_date','candidate','document_encounter_dates',doc+'|'+c,members,
            f'This document gives multiple dates for {c}: {", ".join(dates)}. Confirm that they describe the same encounter before displaying a contradiction.',
            ['Shared document is a retrieval scope only; it does not prove same-event identity.',
             'Separate admissions, transfers or historical events may explain the difference.'])

    # Side disagreement with a summary is only a review candidate: bilateral disease
    # and distinct examinations can be valid. No positive-left vs positive-right alert.
    side_groups = defaultdict(list)
    for f in facts:
        if not eligible(f) or f.category!='imaging' or f.value.kind!='measurement' or len(doc_ids(f))!=1:
            continue
        site = f.value.site
        if not site:
            continue
        reported,side,status,refs = laterality(f,passages)
        if side not in ('left','right') or status not in ('explicit','contextual'):
            continue
        site = re.sub(r'\ba\.', 'arteria',site.casefold())
        site = re.sub(r'\s+',' ',site).strip()
        summary = any(re.search(r'gesamtbeurteilung|zusammenfassung|conclusion',passages[r.passage_id].text+' '+(passages[r.passage_id].section or ''),re.I) for r in f.evidence)
        scope=(next(iter(doc_ids(f))),concept(f),site,f.value.quantity.value,f.value.quantity.unit)
        side_groups[scope].append((f,side,summary,refs))
    for scope, items in sorted(side_groups.items()):
        if {i[1] for i in items}!={'left','right'} or not any(i[2] for i in items) or all(i[2] for i in items):
            continue
        dates={i[0].clinical_time.value for i in items if i[0].clinical_time.basis=='explicit' and i[0].clinical_time.precision=='day'}
        event_ids={explicit_event(i[0],documents) for i in items}-{None}
        if len(dates)>1 or len(event_ids)>1:
            continue
        add('laterality','candidate','summary_laterality',json.dumps(scope),[i[0] for i in items],
            'The finding and summary name different sides for a matching measurement and anatomical site. Confirm examination identity and whether bilateral findings explain this before displaying a contradiction.',
            ['Same document, anatomical site, concept, measurement and unit; summary versus finding.',
             'Source-linked laterality is lexical evidence, not proof of a mutually exclusive clinical claim.'],
            extras=[r for i in items for r in i[3]])

    report.derived_facts.sort(key=lambda d:d.id)
    report.contradictions.sort(key=lambda c:c.id)
    report.assessments.sort(key=lambda a:a.contradiction_id)
    # Validate source/derived references and all citation spans via the existing contract.
    raw=bundle.model_dump(mode='json')
    for field, additions in (('derived_facts',report.derived_facts),('contradictions',report.contradictions)):
        merged={item['id']:item for item in raw[field]}
        for item in additions:
            data=item.model_dump(mode='json')
            if item.id in merged and merged[item.id]!=data:
                raise ValueError('Conflicting generated ID already exists in bundle')
            merged[item.id]=data
        raw[field]=list(merged.values())
    EvidenceBundle.model_validate(raw)
    return report


def display_contradictions(bundle, report):
    """Default UI boundary: candidates stay in a separate review workflow."""
    report.validate_against(bundle)
    return [c.model_copy(deep=True) for c in report.contradictions if c.status=='accepted']


def attach_report(bundle, report):
    """Create a new evidence version with generated values/conflicts; preserve source data.

    Candidates retain candidate status. Consumers must filter status before display.
    Existing gaps remain; this does not certify complete contradiction coverage.
    """
    report.validate_against(bundle)
    raw=bundle.model_dump(mode='json')
    for field, additions in (('derived_facts',report.derived_facts),('contradictions',report.contradictions)):
        merged={item['id']:item for item in raw[field]}
        for item in additions:
            data=item.model_dump(mode='json')
            if item.id in merged and merged[item.id]!=data:
                raise ValueError('Cannot overwrite an existing derived fact or contradiction')
            merged[item.id]=data
        raw[field]=[item for _,item in sorted(merged.items())]
    version=hashlib.sha256((bundle.manifest.evidence_version+report.model_dump_json()).encode()).hexdigest()
    raw['manifest'].update(evidence_version=version,bundle_id=bundle.manifest.patient_id+':'+version[:16],
        pipeline_version=bundle.manifest.pipeline_version+'+'+VERSION,
        configuration_hash=hashlib.sha256((bundle.manifest.configuration_hash+VERSION).encode()).hexdigest())
    from datetime import datetime,timezone
    raw['manifest']['prepared_at']=datetime.now(timezone.utc).isoformat()
    # Enrichment does not promote the source processing status or remove audit gaps.
    return EvidenceBundle.model_validate(raw)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--enriched-output',type=Path,help='Optional new EvidenceBundle containing derived values and status-labelled contradictions')
    args=parser.parse_args()
    if args.input.resolve()==args.output.resolve():
        parser.error('Output must not overwrite the source bundle')
    if args.enriched_output and args.enriched_output.resolve() in (args.input.resolve(),args.output.resolve()):
        parser.error('Enriched output must be separate from both source and report')
    bundle=EvidenceBundle.model_validate_json(args.input.read_text(encoding='utf-8-sig'))
    report=detect_contradictions(bundle)
    report.validate_against(bundle)
    from prep.preparation import write_bundle
    write_bundle(report,args.output)
    if args.enriched_output:
        write_bundle(attach_report(bundle,report),args.enriched_output)
    print(json.dumps({'derived_values':len(report.derived_facts),'accepted':sum(c.status=='accepted' for c in report.contradictions),
        'review_candidates':sum(c.status=='candidate' for c in report.contradictions),
        'diagnostics':len(report.diagnostics),'model_calls':0},indent=2))


if __name__=='__main__':
    main()
