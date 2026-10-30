import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from prep.preparation import prepare_patient
from prep.evidence.history import measurement_history,latest_measurements,latest_discharge_medications,weight_change
from prep.evidence.schema import ClinicalTime
from prep.handoff import build_handoff
from prep.refinement import refine


class HistoryTests(unittest.TestCase):
    def bundle(self,rows):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for i,(text,date) in enumerate(rows):
                (root/f'{i}.json').write_text(json.dumps({'metadata':{'id':str(i),'date':date},'text':text}),encoding='utf-8')
            return prepare_patient(root,'test','independent_synthetic')

    def weights(self):
        return self.bundle([('Gewicht: 82 kg','2023-01-01'),('Gewicht: 74 kg','2023-06-01')])

    def test_weight_change_keeps_signed_subtraction_and_inputs(self):
        b=self.weights()
        change=weight_change(b)
        self.assertEqual(change.result.value,-8)
        self.assertEqual(change.input_fact_ids,[f.id for f in b.facts])
        self.assertIn('document_date',change.explanation)

    def test_snapshot_excludes_future_documents(self):
        b=self.weights()
        self.assertEqual(len(measurement_history(b,'body_weight',as_of='2023-02-01')),1)
        self.assertEqual(latest_measurements(b,'body_weight',as_of='2023-02-01').fact_ids,[b.facts[0].id])
        self.assertIsNone(weight_change(b,as_of='2023-02-01'))

    def test_conflicting_endpoint_values_prevent_calculation(self):
        b=self.bundle([('Gewicht: 82 kg','2023-01-01'),('Gewicht: 74 kg\nGewicht: 76 kg','2023-06-01')])
        self.assertIsNone(weight_change(b))
        self.assertEqual(len(latest_measurements(b,'body_weight').fact_ids),2)

    def test_unknown_document_requires_explicit_cutoff(self):
        b=self.bundle([('Gewicht: 82 kg',None)])
        with self.assertRaises(ValueError):
            latest_measurements(b,'body_weight')
        selection=latest_measurements(b,'body_weight',as_of='2023-01-01')
        self.assertEqual(selection.fact_ids,[])
        self.assertEqual(selection.undated_fact_ids,[b.facts[0].id])

    def test_unanchored_history_not_ranked_as_new_measurement(self):
        b=self.weights()
        b.facts[1].clinical_status='historical'
        selection=latest_measurements(b,'body_weight')
        self.assertEqual(selection.fact_ids,[b.facts[0].id])
        self.assertEqual(selection.undated_fact_ids,[b.facts[1].id])

    def test_explicit_old_date_is_not_new_measurement_from_later_letter(self):
        b=self.weights()
        b.facts[1].clinical_time=ClinicalTime(precision='day',basis='explicit',value='2022-01-01')
        self.assertEqual(latest_measurements(b,'body_weight').fact_ids,[b.facts[0].id])

    def test_medication_lists_are_not_combined_across_dates(self):
        table=lambda schedule:f'Entlassungsmedikation:<BR>Applikation mo mi ab na Einheit Info<BR>Testmittel 8 mg oral {schedule} ST'
        b=self.bundle([(table('1 0 0 0'),'2023-01-01'),(table('1 0 1 0'),'2023-06-01')])
        self.assertEqual(latest_discharge_medications(b).fact_ids,[b.facts[1].id])
        self.assertEqual(latest_discharge_medications(b,as_of='2023-02-01').fact_ids,[b.facts[0].id])

    def test_package_indexes_and_hashes_match_final_bundle(self):
        b=self.weights()
        original=b.model_dump_json()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            result=build_handoff(b,root)
            manifest=json.loads((root/'manifest.json').read_text())
            for name,digest in manifest['files'].items():
                self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(),digest)
            history=json.loads((root/'history.json').read_text())
            self.assertEqual(history['source_evidence_version'],result.manifest.evidence_version)
            self.assertEqual(len(result.derived_facts),1)
        self.assertEqual(b.model_dump_json(),original)

    def test_refinement_preserves_existing_facts_and_source(self):
        b=self.weights()
        result=SimpleNamespace(facts=[],processing_gaps=[])
        with patch('prep.refinement.extract_passages',return_value=result) as extract:
            refined=refine(b,'Gewicht',['measurement'],SimpleNamespace(model='test'))
        self.assertEqual(extract.call_count,2)
        self.assertEqual(refined.facts,b.facts)
        self.assertEqual(refined.documents,b.documents)
        self.assertNotEqual(refined.manifest.evidence_version,b.manifest.evidence_version)

    def test_refinement_requires_matching_source_and_raw_input(self):
        b=self.weights()
        with self.assertRaisesRegex(ValueError,'No source'):
            refine(b,'doesnotmatch',[],SimpleNamespace(model='test'))
        b.derived_facts=[weight_change(b)]
        with self.assertRaisesRegex(ValueError,'raw extraction'):
            refine(b,'Gewicht',[],SimpleNamespace(model='test'))


if __name__=='__main__':
    unittest.main()
