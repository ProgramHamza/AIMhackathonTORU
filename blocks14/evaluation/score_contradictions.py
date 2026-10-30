"""Evaluate source preparation plus bounded detection, with no API calls."""
import argparse
import hashlib
import json
from pathlib import Path

from prep.preparation import prepare_patient, write_bundle
from prep.evidence.contradictions import detect_contradictions


def score_case(bundle,gold):
    if {d.id:d.source_sha256 for d in bundle.documents} != gold['source_hashes']:
        raise ValueError('Gold source hash mismatch')
    docs={d.id:d for d in bundle.documents}
    passages={p.id:p for p in bundle.passages}
    for expected in gold['expected_findings']:
        for ref in expected['required_quotes']:
            if ref['quote'] not in docs[ref['document_id']].normalized_text:
                raise ValueError('Gold quote is not in the source')
    report=detect_contradictions(bundle)
    used=set()
    missing=[]
    for index,expected in enumerate(gold['expected_findings']):
        match=next((c for c in report.contradictions if c.id not in used
            and c.kind==expected['kind'] and c.status==expected['status']
            and all(any(passages[r.passage_id].document_id==ref['document_id'] and ref['quote'] in r.quote for r in c.evidence)
                for ref in expected['required_quotes'])),None)
        if match:
            used.add(match.id)
        else:
            missing.append(index)
    unexpected=[{'id':c.id,'kind':c.kind,'status':c.status} for c in report.contradictions if c.id not in used]
    return {'case_id':gold['case_id'],'passed':not missing and not unexpected,
        'matched':len(used),'expected':len(gold['expected_findings']),'missing_indices':missing,'unexpected':unexpected,
        'accepted_false_alarms':sum(c['status']=='accepted' for c in unexpected),
        'expected_accepted':sum(c['status']=='accepted' for c in gold['expected_findings']),
        'expected_candidates':sum(c['status']=='candidate' for c in gold['expected_findings']),
        'source_evidence_version':bundle.manifest.evidence_version},report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus',type=Path,default=Path('tests/fixtures/contradictions'))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    rows=[]
    for path in sorted((args.corpus/'gold').glob('*.json')):
        gold=json.loads(path.read_text(encoding='utf-8'))
        if gold['split']!='development':
            raise ValueError('Only development evaluation supported')
        bundle=prepare_patient(args.corpus/'inputs'/gold['case_id'],gold['case_id'],'independent_synthetic')
        row,report=score_case(bundle,gold)
        row['gold_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append(row)
        write_bundle(report,args.output.parent/'contradiction-cases'/(gold['case_id']+'.json'))
    if not rows:
        raise ValueError('No development cases')
    result={'cases':len(rows),'passed':sum(r['passed'] for r in rows),
        'accepted_false_alarms':sum(r['accepted_false_alarms'] for r in rows),'model_calls':0,
        'limitations':'Small AI-authored development corpus for bounded rules. Not held out, clinician reviewed or a recall estimate for clinical records.',
        'results':rows}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='results'},indent=2))


if __name__=='__main__':
    main()
