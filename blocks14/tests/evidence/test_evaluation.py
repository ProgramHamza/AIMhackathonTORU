import copy
import json
from pathlib import Path
import unittest
import tempfile

from prep.preparation import prepare_patient
from evaluation.score import score


class EvaluationTests(unittest.TestCase):
    def test_seed_reproduces_frozen_inputs_and_labels(self):
        from evaluation.build_development import build
        root=Path('tests/fixtures/independent')
        with tempfile.TemporaryDirectory() as directory:
            rebuilt=Path(directory)
            build(rebuilt)
            for path in root.rglob('*.json'):
                self.assertEqual(path.read_bytes(),(rebuilt/path.relative_to(root)).read_bytes())

    def fixture(self, case='DEV-MEAS-01'):
        root = Path('tests/fixtures/independent')
        gold = json.loads((root/'gold'/f'{case}.json').read_text(encoding='utf-8'))
        return prepare_patient(root/'inputs'/case, case, 'independent_synthetic'), gold

    def test_baseline_correct_fields_and_spans(self):
        bundle, gold = self.fixture()
        result = score(bundle, gold)
        self.assertEqual((result['matched'], result['expected'], result['predicted']), (3,3,3))

    def test_wrong_value_fails_even_with_real_quote(self):
        bundle, gold = self.fixture()
        bundle.facts[0].value.quantity.value = 999
        self.assertEqual(score(bundle,gold)['matched'],2)

    def test_stale_source_and_corrupt_gold_rejected(self):
        bundle, gold = self.fixture()
        bad=copy.deepcopy(gold)
        bad['source_hashes'][bundle.documents[0].id]='0'*64
        with self.assertRaisesRegex(ValueError,'hash mismatch'):
            score(bundle,bad)
        gold['expected_facts'][0]['evidence'][0]['start'] += 1
        with self.assertRaisesRegex(ValueError,'Gold evidence'):
            score(bundle,gold)

    def test_duplicate_does_not_inflate_recall(self):
        bundle,gold=self.fixture()
        duplicate=bundle.facts[0].model_copy(deep=True)
        duplicate.id='duplicate'
        bundle.facts.append(duplicate)
        result=score(bundle,gold)
        self.assertEqual(result['matched'],3)
        self.assertEqual(result['precision'],0.75)
        reconciled=score(bundle,gold,reconcile=True)
        self.assertEqual(reconciled['predicted'],3)
        self.assertEqual(reconciled['matched'],3)

    def test_repeated_quote_wrong_location_fails(self):
        bundle,gold=self.fixture('DEV-SOURCE-01')
        bundle.facts[1].evidence=copy.deepcopy(bundle.facts[0].evidence)
        self.assertEqual(score(bundle,gold)['matched'],1)

    def test_negative_control_has_no_invented_perfect_recall(self):
        bundle,gold=self.fixture('DEV-ALL-03')
        result=score(bundle,gold)
        self.assertIsNone(result['recall'])
        self.assertEqual(result['forbidden_claim_violations'],[])

    def test_global_matching_not_greedy(self):
        bundle,gold=self.fixture('DEV-MEAS-02')
        gold['expected_facts'][0]['concepts']=[]
        gold['expected_facts'][0]['fields'].pop('value')
        gold['expected_facts'][1]['concepts']=['systolic_blood_pressure']
        gold['expected_facts'][1]['fields']['value']['quantity']['value']=138
        self.assertEqual(score(bundle,gold)['matched'],2)

    def test_forbidden_claim_detected(self):
        bundle,gold=self.fixture('DEV-ALL-02')
        bundle.facts[0].assertion='affirmed'
        result=score(bundle,gold)
        self.assertEqual(result['matched'],0)
        self.assertEqual(len(result['forbidden_claim_violations']),1)


if __name__=='__main__':
    unittest.main()
