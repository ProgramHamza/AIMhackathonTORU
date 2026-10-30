"""Attach an explicitly documented outpatient visit date to main visit measurements."""
from datetime import datetime, timezone
import hashlib
import json
import re
from prep.evidence.schema import EvidenceBundle, ClinicalTime, EvidenceRef
from prep.extraction.source_checks import source_dates

VERSION='outpatient-context-v1'


def contextualize_outpatient_measurements(bundle):
    if bundle.derived_facts or bundle.contradictions:
        raise ValueError('Use raw evidence, then rebuild derived outputs')
    result=bundle.model_copy(deep=True)
    changes=[]
    passages={p.id:p for p in bundle.passages}
    for doc in bundle.documents:
        if 'ambulanter patientenbrief' not in doc.normalized_text.casefold():
            continue
        candidates=[]
        for p in bundle.passages:
            if p.document_id!=doc.id:
                continue
            match=re.search(
                r'ambulanten Besuch[\s\S]*?\bwelche am (\d{1,2}\.\d{1,2}\.\d{4}) an unserer Abteilung in Behandlung war',p.text,re.I)
            if match:
                days=source_dates(match[1])
                if len(days)==1:
                    candidates.append((p,match,next(iter(days))))
        if len(candidates)!=1:
            continue
        p,match,day=candidates[0]
        if doc.document_date and day>doc.document_date.isoformat():
            continue
        ref=EvidenceRef(passage_id=p.id,start=p.start+match.start(),end=p.start+match.end(),quote=match[0])
        for fact in result.facts:
            if fact.category!='vitals' or fact.value.kind!='measurement' or fact.assertion!='affirmed' or fact.subject!='patient':
                continue
            if fact.clinical_time.basis!='document_fallback' or fact.clinical_status not in ('unknown','active'):
                continue
            clinical_refs=[r for r in fact.evidence if passages[r.passage_id].kind!='heading']
            if not clinical_refs or any(passages[r.passage_id].document_id!=doc.id or (passages[r.passage_id].section or '').casefold() not in ('vitalparameter','befunde') for r in clinical_refs):
                continue
            if any(re.search(r'früher|zuvor|damals|historisch|geplant',r.quote,re.I) for r in clinical_refs):
                continue
            old=fact.clinical_time.model_dump(mode='json')
            fact.clinical_time=ClinicalTime(precision='day',value=day,basis='contextual',original_text=match[1])
            fact.evidence.append(ref.model_copy(deep=True))
            fact.validation.notes.append('Outpatient visit date attached contextually from the cited visit introduction; not an explicitly timed measurement.')
            changes.append({'fact_id':fact.id,'before':old,'after':fact.clinical_time.model_dump(mode='json'),'added_evidence':ref.model_dump()})
    if not changes:
        return result,changes
    version=hashlib.sha256((bundle.manifest.evidence_version+VERSION+json.dumps(changes,sort_keys=True)).encode()).hexdigest()
    result.manifest.evidence_version=version
    result.manifest.bundle_id=bundle.manifest.patient_id+':'+version[:16]
    result.manifest.configuration_hash=hashlib.sha256((bundle.manifest.configuration_hash+VERSION).encode()).hexdigest()
    result.manifest.pipeline_version+='+'+VERSION
    result.manifest.prepared_at=datetime.now(timezone.utc)
    return EvidenceBundle.model_validate(result.model_dump(mode='json')),changes


def main():
    import argparse
    from pathlib import Path
    from prep.preparation import write_bundle
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.input.resolve()==args.output.resolve():
        parser.error('Preserve original evidence by choosing a separate output')
    source=EvidenceBundle.model_validate_json(args.input.read_text(encoding='utf-8-sig'))
    result,changes=contextualize_outpatient_measurements(source)
    write_bundle(result,args.output)
    args.output.with_suffix('.date-changes.json').write_text(json.dumps(changes,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'date_updates':len(changes),'model_calls':0}))


if __name__=='__main__':
    main()
