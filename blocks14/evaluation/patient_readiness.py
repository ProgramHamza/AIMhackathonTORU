"""Offline supplied-patient scenario coverage audit. NEVER a runtime answer lookup.

Checks evidence availability for the published scenarios, not answer correctness,
rendered screens, unseen-query performance, or absence from the complete record.
"""
import argparse
import json
from pathlib import Path
from prep.evidence.schema import EvidenceBundle
from prep.evidence.history import latest_discharge_medications,latest_measurements,weight_change


def audit(bundle):
    facts={f.id:f for f in bundle.facts}
    meds=[facts[i] for i in latest_discharge_medications(bundle).fact_ids]
    def drug(name):
        return [f for f in meds if name.casefold() in f.value.drug_name.casefold()]
    def concepts(*names):
        return [f for f in bundle.facts if f.concept in names and f.assertion=='affirmed']
    def quotes(*words):
        return [f for f in bundle.facts if all(word.casefold() in ' '.join(r.quote for r in f.evidence).casefold() for word in words)]
    def latest(name):
        return [facts[i] for i in latest_measurements(bundle,name).fact_ids]
    rows=[]
    def add(identifier,groups,review=None):
        missing=[name for name,items in groups.items() if not items]
        refs=sorted({f.id for items in groups.values() for f in items})
        rows.append({'question_id':identifier,'status':'missing_evidence' if missing else 'requires_query_review' if review else 'evidence_available',
            'missing_groups':missing,'fact_ids':refs,'review_note':review})
    allergies=[f for f in bundle.facts if f.category=='allergies' and f.assertion=='affirmed' and f.value.reactions]
    add('1.1',{'antithrombotic discharge entry':drug('Thrombo ASS')})
    add('1.2',{'documented allergy with reactions':allergies})
    add('1.3',{'latest EF evidence':latest('ejection_fraction')})
    add('2.1',{'histology':quotes('invasiv','duktal'),'staging':concepts('tumour_stage')})
    add('2.2',{c:concepts(c) for c in ('estrogen_receptor','estrogen_receptor_percent','estrogen_receptor_allred',
        'progesterone_receptor','progesterone_receptor_percent','progesterone_receptor_allred','her2','ki67')})
    add('2.3',{'recommendation':quotes('Quadrantenresektion','empfohlen'),'scheduled intervention':quotes('Quadrantenresektion','16.05.2016')})
    add('3.1',{name:drug(name) for name in ('Glucophage','Actos','Byetta')})
    add('3.2',{'latest HbA1c evidence':latest('hba1c')})
    change=weight_change(bundle)
    add('3.3',{'weight change endpoints':[facts[i] for i in change.input_fact_ids] if change else []})
    add('4.1',{'documented causal attribution':quotes('zurückgeführt','Schwindel')})
    add('4.2',{'contrast allergy':allergies,'glucose-lowering medication':drug('Glucophage')},
        'Renal-function absence still needs query-specific full-document coverage review; no absence fact was invented.')
    add('4.3',{'latest antihypertensive entry':drug('Blopress')})
    add('5.1',{'carotid follow-up':quotes('Duplexsonographie','2 Monaten'),
        'eye follow-up':quotes('Augenkontrollen','empfohlen'),'blood-pressure review':quotes('Blutdruckkontrollen'),
        'GP medication adjustment':quotes('Anpassung','Hausarzt')})
    add('5.2',{'carotid follow-up recommendation':quotes('Duplexsonographie','2 Monaten')},
        'Absence of a completed follow-up needs query-specific full-document review; no fact-store-only not-documented conclusion.')
    add('5.3',{'left carotid source evidence':quotes('carotis interna links')},
        'Left-sided source evidence coexists with a right-sided passage. Preserve the review candidate rather than silently choosing one source.')
    return {'source_evidence_version':bundle.manifest.evidence_version,'facts':len(bundle.facts),
        'purpose':'Published-scenario evidence readiness only, not the official 15-answer score.',
        'evidence_available':sum(r['status']=='evidence_available' for r in rows),
        'requires_query_review':sum(r['status']=='requires_query_review' for r in rows),
        'missing_evidence':sum(r['status']=='missing_evidence' for r in rows),
        'weight_change':change.model_dump(mode='json') if change else None,'questions':rows}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    bundle=EvidenceBundle.model_validate_json(args.input.read_text(encoding='utf-8-sig'))
    result=audit(bundle)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('facts','evidence_available','requires_query_review','missing_evidence')},indent=2))


if __name__=='__main__':
    main()
