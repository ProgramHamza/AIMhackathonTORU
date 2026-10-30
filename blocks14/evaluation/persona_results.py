"""Score frozen synthetic personas and exercise the complete offline handoff."""
import hashlib
import json
from pathlib import Path
from prep.evidence.schema import EvidenceBundle
from prep.evidence.history import weight_change,latest_discharge_medications
from prep.evidence.normalization import NormalizationIndex
from prep.evidence.reconciliation import ReconciliationIndex
from prep.handoff import build_handoff
from evaluation.score import score


def main():
    root=Path('data/evaluation/new-personas')
    manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    results=[]
    for persona in manifest['personas']:
        case=persona['id']
        gp=root/'gold'/f'{case}.json'
        if hashlib.sha256(gp.read_bytes()).hexdigest()!=manifest['gold_hashes'][gp.name]:
            raise ValueError('Frozen gold changed after first run')
        gold=json.loads(gp.read_text(encoding='utf-8'))
        bundle=EvidenceBundle.model_validate_json((root/'predictions'/f'{case}.json').read_text(encoding='utf-8-sig'))
        result=score(bundle,gold,reconcile=True)
        out=root/'handoffs'/case
        ready=build_handoff(bundle,out)
        NormalizationIndex.model_validate_json((out/'normalization.json').read_text(encoding='utf-8')).validate_against(ready)
        ReconciliationIndex.model_validate_json((out/'reconciliation.json').read_text(encoding='utf-8')).validate_against(ready)
        changes=weight_change(bundle)
        actual=changes.result.value if changes else None
        accepted=sum(c.status=='accepted' for c in ready.contradictions)
        candidates=sum(c.status=='candidate' for c in ready.contradictions)
        result['pipeline_checks']={'handoff_valid':True,'weight_change':{'expected':gold['expected_weight_change'],'actual':actual,'passed':actual==gold['expected_weight_change']},
            'accepted_contradictions':{'expected':gold['expected_accepted'],'actual':accepted,'passed':accepted==gold['expected_accepted']},
            'review_candidates':{'expected':gold['expected_candidates'],'actual':candidates,'passed':candidates==gold['expected_candidates']},
            'latest_discharge_medications':latest_discharge_medications(bundle).model_dump()}
        result['missing_labels']=[g for g in gold['expected_facts'] if g['id'] in result['missing_gold_ids']]
        result['processing_gap_reasons']=sorted({g.reason for g in bundle.processing_gaps})
        results.append(result)
    total={k:sum(r[k] for r in results) for k in ('matched','expected','predicted')}
    report={'totals':total,'cases':results,'limitations':'AI-authored synthetic labels, strict field/span matching, not a clinical accuracy estimate. No labels or extraction rules changed to improve this run.'}
    (root/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'totals':total,'patients':[{'id':r['case_id'],'matched':r['matched'],'expected':r['expected'],'predicted':r['predicted'],'checks':r['pipeline_checks']} for r in results]},indent=2))


if __name__=='__main__':
    main()
