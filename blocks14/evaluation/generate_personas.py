"""Three new independent synthetic patients; labels authored before model execution."""
import hashlib
import json
from pathlib import Path
from typing import get_args
from prep.evidence.schema import Category
from prep.ingestion.documents import normalize


def fact(category,quote,**fields):
    return {'quote':quote,'fields':{'category':category,'assertion':'affirmed','subject':'patient',**fields}}


def measurement(concept,quote,value,unit,category='vitals'):
    return fact(category,quote,concept=concept,value={'kind':'measurement','quantity':{'value':value,'unit':unit}})


def medication(quote,slots):
    return fact('medications',quote,value={'kind':'medication','drug_name':'Testmittel Rho','strength':{'value':4,'unit':'mg'},
        'schedule':dict(zip(('morning','midday','evening','night'),slots))})


PERSONAS=[
 {'id':'persona-metabolic','name':'Mira Falk (fictional)','focus':'Diabetes follow-up, changed prescription and weight; no contradiction expected.',
  'documents':[
   ('2024-02-12','Diagnosen:<BR>Diabetes mellitus Typ II.<BR><BR>Vitalparameter:<BR>Größe: 180 cm<BR>Gewicht: 84 kg<BR>BMI: 25,9<BR><BR>Labor:<BR>HbA1c: 7,6%<BR><BR>Entlassungsmedikation:<BR>Applikation mo mi ab na Einheit Info<BR>Testmittel Rho 4 mg oral 1 0 0 0 ST',[
    fact('diagnoses','Diabetes mellitus Typ II.'),measurement('body_height','Größe: 180 cm',180,'cm'),measurement('body_weight','Gewicht: 84 kg',84,'kg'),measurement('body_mass_index','BMI: 25,9',25.9,'kg/m2'),measurement('hba1c','HbA1c: 7,6%',7.6,'%',category='laboratory'),medication('Testmittel Rho 4 mg oral 1 0 0 0 ST',[1,0,0,0])]),
   ('2024-08-19','Verlauf:<BR>Keine Hypoglykämien.<BR><BR>Vitalparameter:<BR>Gewicht: 80 kg<BR><BR>Labor:<BR>HbA1c: 6,9%<BR><BR>Entlassungsmedikation:<BR>Applikation mo mi ab na Einheit Info<BR>Testmittel Rho 4 mg oral 1 0 1 0 ST',[
    fact('symptoms','Keine Hypoglykämien.',assertion='negated'),measurement('body_weight','Gewicht: 80 kg',80,'kg'),measurement('hba1c','HbA1c: 6,9%',6.9,'%',category='laboratory'),medication('Testmittel Rho 4 mg oral 1 0 1 0 ST',[1,0,1,0])])],
  'expected_weight_change':-4,'expected_accepted':0,'expected_candidates':0},
 {'id':'persona-orthopaedic','name':'Jonas Berg (fictional)','focus':'Allergy, recommended then completed right-knee MRI, negation and family history.',
  'documents':[
   ('2024-03-07','Allergien:<BR>Latex-Allergie (Urtikaria, Juckreiz)<BR><BR>Symptome:<BR>Schmerzen im rechten Knie.<BR><BR>Plan:<BR>Eine MRT des rechten Knies wird empfohlen. Sie wurde noch nicht durchgeführt.<BR><BR>Familienanamnese:<BR>Der Vater hat Diabetes mellitus.',[
    fact('allergies','Latex-Allergie (Urtikaria, Juckreiz)',value={'kind':'allergy','substance':'Latex','reactions':['Urtikaria','Juckreiz']}),
    fact('symptoms','Schmerzen im rechten Knie.',value={'kind':'assertion','laterality':'right'}),
    fact('care_plans','Eine MRT des rechten Knies wird empfohlen.',clinical_status='recommended'),
    fact('procedures','Sie wurde noch nicht durchgeführt.',assertion='negated'),
    fact('family_history','Der Vater hat Diabetes mellitus.',subject='family_member')]),
   ('2024-03-25','Durchgeführte Untersuchung:<BR>MRT des rechten Knies am 22.03.2024 durchgeführt.<BR><BR>Diagnosen:<BR>Kein Meniskusriss.<BR><BR>Verlauf:<BR>Die Knieschmerzen sind abgeklungen.',[
    fact('procedures','MRT des rechten Knies am 22.03.2024 durchgeführt.',clinical_status='completed',clinical_time={'precision':'day','value':'2024-03-22','basis':'explicit'},value={'kind':'event','laterality':'right'}),
    fact('diagnoses','Kein Meniskusriss.',assertion='negated'),fact('symptoms','Die Knieschmerzen sind abgeklungen.',clinical_status='resolved')])],
  'expected_weight_change':None,'expected_accepted':0,'expected_candidates':0},
 {'id':'persona-neurology','name':'Lea Winter (fictional)','focus':'Headache, conflicting admission dates, deliberately wrong BMI, normal follow-up and family history.',
  'documents':[
   ('2024-09-12','Aufnahme am 08.09.2024<BR>Entlassen am 12.09.2024<BR><BR>Symptome:<BR>Kopfschmerzen und Schwindel.<BR><BR>Vitalparameter:<BR>Größe: 165 cm<BR>Gewicht: 65 kg<BR>BMI: 32<BR><BR>Therapie und Verlauf:<BR>Die Patientin wurde am 09.09.2024 auf der Station aufgenommen.<BR>Die Kopfschmerzen sind abgeklungen.<BR><BR>Allergien:<BR>Keine bekannten Allergien.',[
    fact('encounters','Aufnahme am 08.09.2024',concept='admission',clinical_status='completed',clinical_time={'precision':'day','value':'2024-09-08','basis':'explicit'}),
    fact('encounters','Entlassen am 12.09.2024',concept='discharge',clinical_status='completed',clinical_time={'precision':'day','value':'2024-09-12','basis':'explicit'}),
    fact('symptoms','Kopfschmerzen'),fact('symptoms','Schwindel.'),measurement('body_height','Größe: 165 cm',165,'cm'),measurement('body_weight','Gewicht: 65 kg',65,'kg'),measurement('body_mass_index','BMI: 32',32,'kg/m2'),
    fact('encounters','Die Patientin wurde am 09.09.2024 auf der Station aufgenommen.',clinical_status='completed',clinical_time={'precision':'day','value':'2024-09-09','basis':'explicit'}),
    fact('symptoms','Die Kopfschmerzen sind abgeklungen.',clinical_status='resolved'),fact('allergies','Keine bekannten Allergien.',assertion='negated')]),
   ('2024-10-08','Verlauf:<BR>Keine aktuellen Kopfschmerzen.<BR><BR>Vitalparameter:<BR>Gewicht: 64 kg<BR><BR>Familienanamnese:<BR>Die Mutter hat Migräne.',[
    fact('symptoms','Keine aktuellen Kopfschmerzen.',assertion='negated'),measurement('body_weight','Gewicht: 64 kg',64,'kg'),fact('family_history','Die Mutter hat Migräne.',subject='family_member')])],
  'expected_weight_change':-1,'expected_accepted':1,'expected_candidates':1},
]


def main():
    root=Path('data/evaluation/new-personas')
    if (root/'manifest.json').exists():
        raise ValueError('Corpus already frozen; do not overwrite labels after looking at results')
    for persona in PERSONAS:
        directory=root/'inputs'/persona['id']
        directory.mkdir(parents=True,exist_ok=True)
        labels=[]
        hashes={}
        for i,(day,text,ledger) in enumerate(persona['documents']):
            doc_id=persona['id']+f'-{i+1}'
            source={'metadata':{'id':doc_id,'date':day,'title':'Synthetic clinical letter'},'text':'Ort, am '+'.'.join(reversed(day.split('-')))+'<BR><BR>'+text}
            raw=(json.dumps(source,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
            (directory/f'{doc_id}.json').write_bytes(raw)
            hashes[doc_id]=hashlib.sha256(raw).hexdigest()
            normalized=normalize(source['text'])
            for item in ledger:
                start=normalized.index(item['quote'])
                labels.append({'id':f"{persona['id']}-F{len(labels)+1}",'fields':item['fields'],'concepts':[],
                    'evidence':[{'document_id':doc_id,'start':start,'end':start+len(item['quote']),'quote':item['quote']}]})
        gold={'case_id':persona['id'],'split':'development','review_status':'ai_authored_frozen_before_first_run_not_clinician_reviewed',
            'source_hashes':hashes,'categories':list(get_args(Category)),'expected_facts':labels,'forbidden_claims':[],
            'expected_weight_change':persona['expected_weight_change'],'expected_accepted':persona['expected_accepted'],'expected_candidates':persona['expected_candidates']}
        (root/'gold').mkdir(exist_ok=True)
        (root/'gold'/f"{persona['id']}.json").write_text(json.dumps(gold,ensure_ascii=False,indent=2),encoding='utf-8')
    manifest={'origin':'Independently authored synthetic cases, not variants of IBM records. Testmittel Rho is fictitious; no treatment recommendation.',
        'personas':[{k:v for k,v in p.items() if k!='documents'} for p in PERSONAS],
        'gold_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'gold').glob('*.json')}}
    (root/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'patients':3,'documents':6,'facts':sum(len(x[2]) for p in PERSONAS for x in p['documents']),'root':str(root)}))


if __name__=='__main__':
    main()
