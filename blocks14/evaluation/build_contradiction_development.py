"""Independent source-level development cases for the bounded contradiction rules."""
import hashlib
import json
from pathlib import Path


def finding(kind,status,*quotes):
    return {'kind':kind,'status':status,'required_quotes':[{'document_id':doc,'quote':quote} for doc,quote in quotes]}


BAD='Vitalparameter:<BR>Größe: 162 cm<BR>Gewicht: 73 kg<BR>BMI: 34'
CASES=[
 ('BMI-01',[BAD],[finding('numeric_inconsistency','accepted',('d0','Größe: 162 cm'),('d0','Gewicht: 73 kg'),('d0','BMI: 34'))]),
 ('BMI-02',['Vitalparameter:<BR>Größe: 162 cm<BR>Gewicht: 73 kg<BR>BMI: 27,8'],[]),
 ('BMI-03',['Vitalparameter:<BR>Größe: 162 cm<BR>Gewicht: 73 kg<BR>BMI: 28'],[]),
 ('BMI-04',['Vitalparameter:<BR>02.01.2021 Größe: 162 cm<BR>07.08.2024 Gewicht: 73 kg<BR>BMI: 34'],[]),
 ('BMI-05',['Vitalparameter:<BR>Größe: 162 cm<BR><BR>Gewicht: 73 kg<BR><BR>BMI: 34'],[]),
 ('BMI-06',[BAD,BAD],[finding('numeric_inconsistency','accepted',('d0','BMI: 34'),('d1','BMI: 34'))]),
 ('BMI-07',['Vitalparameter:<BR>Größe: 162 cm<BR>Gewicht: 73 kg<BR>Gewicht: 88 kg<BR>BMI: 34'],[]),
 ('BMI-08',['Vitalparameter:<BR>Größe: 1,62 m<BR>Gewicht: 73000 g<BR>BMI: 34'],
     [finding('numeric_inconsistency','accepted',('d0','Größe: 1,62 m'),('d0','Gewicht: 73000 g'),('d0','BMI: 34'))]),
 ('DATE-01',['Aufnahme am 02.08.2024<BR><BR>Aufnahme am 04.08.2024'],
     [finding('event_date','candidate',('d0','Aufnahme am 02.08.2024'),('d0','Aufnahme am 04.08.2024'))]),
 ('DATE-02',['Geplante Aufnahme am 02.08.2024<BR><BR>Aufnahme am 04.08.2024'],[]),
 ('DATE-03',['Aufnahme am 02.08.2024','Aufnahme am 04.08.2024'],[]),
 ('DATE-04',['Aufnahme am 02.08.20244<BR><BR>Aufnahme am 04.08.2024'],[]),
]


def build(root=Path('tests/fixtures/contradictions')):
    for case_id,texts,findings in CASES:
        directory=root/'inputs'/case_id
        directory.mkdir(parents=True,exist_ok=True)
        hashes={}
        for i,text in enumerate(texts):
            doc_id=f'd{i}'
            raw=(json.dumps({'metadata':{'id':doc_id,'date':'2024-08-07'},'text':text},ensure_ascii=False,indent=2)+'\n').encode('utf-8')
            (directory/(doc_id+'.json')).write_bytes(raw)
            hashes[doc_id]=hashlib.sha256(raw).hexdigest()
        gold={'case_id':case_id,'split':'development','review_status':'ai_authored_pending_independent_review',
            'source_hashes':hashes,'expected_findings':findings,
            'scope':'Bounded rules only. Candidate means review-needed, never an accepted contradiction. No model extraction accuracy claim.'}
        (root/'gold').mkdir(parents=True,exist_ok=True)
        (root/'gold'/(case_id+'.json')).write_text(json.dumps(gold,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    build()
