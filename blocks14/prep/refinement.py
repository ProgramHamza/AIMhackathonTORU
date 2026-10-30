"""Refine selected source passages without rerunning the patient's full extraction."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from prep.evidence.schema import EvidenceBundle
from prep.extraction.coverage import with_headings
from prep.extraction.chunks import section_batches
from prep.extraction.narrative import extract_passages
from prep.preparation import write_bundle

VERSION='targeted-refinement-v1'


def refine(bundle, pattern, requested_concepts, client):
    if bundle.derived_facts or bundle.contradictions:
        raise ValueError('Refine the raw extraction bundle, then rebuild derived outputs/indexes')
    regex=re.compile(pattern,re.I)
    selected=[p for p in bundle.passages if p.kind!='heading' and regex.search(p.text)]
    if not selected:
        raise ValueError('No source passages match refinement selector')
    raw=bundle.model_dump(mode='json')
    facts={f.id:f for f in bundle.facts}
    gaps={g.id:g for g in bundle.processing_gaps}
    for document in bundle.documents:
        all_passages=[p for p in bundle.passages if p.document_id==document.id]
        matches=[p for p in selected if p.document_id==document.id]
        if not matches:
            continue
        for batch in section_batches(with_headings(matches,all_passages)):
            ids={p.id for p in batch}
            existing=[f for f in facts.values() if any(r.passage_id in ids for r in f.evidence)]
            result=extract_passages(document,batch,client,existing_facts=existing,requested_concepts=requested_concepts)
            for f in result.facts:
                facts.setdefault(f.id,f)
            for gap in result.processing_gaps:
                gaps.setdefault(gap.id,gap)
    raw['facts']=[f.model_dump(mode='json') for f in facts.values()]
    raw['processing_gaps']=[g.model_dump(mode='json') for g in gaps.values()]
    settings={'version':VERSION,'pattern':pattern,'requested_concepts':requested_concepts,'model':client.model}
    config=hashlib.sha256((bundle.manifest.configuration_hash+json.dumps(settings,sort_keys=True)).encode()).hexdigest()
    version=hashlib.sha256(json.dumps({'source':bundle.manifest.evidence_version,'config':config,'facts':raw['facts'],'gaps':raw['processing_gaps']},sort_keys=True).encode()).hexdigest()
    raw['manifest'].update(evidence_version=version,bundle_id=bundle.manifest.patient_id+':'+version[:16],
        pipeline_version=bundle.manifest.pipeline_version+'+'+VERSION,configuration_hash=config,
        prepared_at=datetime.now(timezone.utc).isoformat(),status='partial',
        model_versions=sorted(set(bundle.manifest.model_versions+[client.model])))
    return EvidenceBundle.model_validate(raw)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--search',required=True)
    parser.add_argument('--concept',action='append',required=True)
    parser.add_argument('--max-calls',type=int,default=4)
    args=parser.parse_args()
    if args.input.resolve()==args.output.resolve() or args.max_calls<1:
        parser.error('Use a separate output path and a positive request budget')
    from dotenv import load_dotenv
    from prep.llm.gemini import GeminiClient
    load_dotenv(Path(__file__).resolve().parents[1]/'.env.local',override=False)
    bundle=EvidenceBundle.model_validate_json(args.input.read_text(encoding='utf-8-sig'))
    client=GeminiClient.from_env()
    client.max_calls=args.max_calls
    try:
        refined=refine(bundle,args.search,args.concept,client)
        write_bundle(refined,args.output)
    finally:
        client.close()
    metrics={'before':len(bundle.facts),'after':len(refined.facts),'usage':client.usage.snapshot(),'cache_hits':client.cache_hits}
    args.output.with_suffix('.metrics.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
    print(json.dumps(metrics,indent=2))


if __name__=='__main__':
    main()
