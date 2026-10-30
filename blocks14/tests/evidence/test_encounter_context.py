import json
from pathlib import Path
import tempfile
import unittest
from prep.preparation import prepare_patient
from prep.evidence.encounter_context import contextualize_outpatient_measurements


class EncounterContextTests(unittest.TestCase):
    def bundle(self,day='04.04.2024',historical=False,duplicate=False):
        intro=f'Wir berichten über den ambulanten Besuch von Frau Demo, geb 02.09.1957, welche am {day} an unserer Abteilung in Behandlung war.'
        text='Ort, am 05.04.2024<BR><BR>Ambulanter Patientenbrief<BR><BR>'+intro
        if duplicate:
            text+='<BR><BR>'+intro.replace(day,'03.04.2024')
        text+='<BR><BR>Vitalparameter:<BR>Gewicht: 71 kg'
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)
            (p/'d.json').write_text(json.dumps({'metadata':{'id':'d','date':'2024-04-05'},'text':text}),encoding='utf-8')
            b=prepare_patient(p,'test','independent_synthetic')
        if historical:
            b.facts[0].clinical_status='historical'
        return b

    def test_context_date_and_citation_preserve_original(self):
        b=self.bundle()
        before=b.model_dump_json()
        revised,changes=contextualize_outpatient_measurements(b)
        self.assertEqual(len(changes),1)
        self.assertEqual(revised.facts[0].clinical_time.value,'2024-04-04')
        self.assertEqual(revised.facts[0].clinical_time.basis,'contextual')
        self.assertIn('04.04.2024',revised.facts[0].evidence[-1].quote)
        self.assertEqual(b.model_dump_json(),before)
        repeated,again=contextualize_outpatient_measurements(revised)
        self.assertEqual(again,[])
        self.assertEqual(repeated,revised)

    def test_invalid_future_ambiguous_or_historical_anchor_skipped(self):
        for b in (self.bundle('31.02.2024'),self.bundle('06.04.2024'),self.bundle(duplicate=True),self.bundle(historical=True)):
            self.assertEqual(contextualize_outpatient_measurements(b)[1],[])
