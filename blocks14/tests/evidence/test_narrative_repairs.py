import copy
import json
import tempfile
import unittest
from pathlib import Path

from prep.evidence.schema import ClinicalTime
from prep.extraction.chunks import section_batches
from prep.extraction.narrative import extract_passages, checked_candidate
from prep.extraction.narrative_models import ExtractionResponse
from prep.extraction.source_checks import check_time, check_status, check_measurement
from prep.ingestion.documents import load_document, segment_document
from prep.llm.client import ModelError
from tests.evidence.test_narrative import FakeClient


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        p = Path(self.temp.name) / 'independent.json'
        p.write_text(json.dumps({'metadata': {'id': 'independent', 'date': '2024-07-09'},
            'text': 'Befund:<BR>Keine Dyspnoe.<BR><BR>Entlassen am 09/07/20244.<BR>Entlassen am 09.07.2024.'}), encoding='utf-8')
        self.doc = load_document(p)
        self.passages = segment_document(self.doc)

    def base(self):
        return FakeClient().generate(system='', payload={'passages': [{'id':p.id,'text':p.text} for p in self.passages]}, response_type=ExtractionResponse)

    def test_invalid_quote_candidate_does_not_discard_valid_candidate(self):
        first = self.base().model_dump(mode='json')
        broken = copy.deepcopy(first['candidates'][0])
        broken['evidence'][0]['quote'] = 'fabricated quote'
        first['candidates'].append(broken)
        parsed = ExtractionResponse.model_validate(first)
        self.assertEqual(len(parsed.candidates), 2)
        self.assertEqual(len(parsed.candidates[1].evidence), 1)
        class Client(FakeClient):
            def generate(inner, **kwargs):
                if kwargs['response_type'] is ExtractionResponse:
                    inner.calls += 1
                    if inner.calls == 1:
                        return parsed
                    self.assertEqual(len(kwargs['payload']['repair_items']), 1)
                    self.assertEqual(len(kwargs['payload']['existing_facts']), 1)
                    raise ModelError('provider_timeout', True)
                return super().generate(**kwargs)
        result = extract_passages(self.doc, self.passages, Client())
        self.assertEqual(len(result.facts), 1)
        self.assertEqual(result.facts[0].validation.semantic_check, 'model_checked')
        self.assertTrue(any(g.reason == 'provider_timeout' for g in result.processing_gaps))

    def test_repair_can_return_only_corrected_candidate(self):
        first = self.base().model_dump(mode='json')
        broken = copy.deepcopy(first['candidates'][0]); broken['concept'] = 'another_claim'
        broken['evidence'][0]['quote'] = 'fabricated quote'
        first['candidates'].append(broken)
        second = copy.deepcopy(first); second['candidates'] = [broken]
        second['candidates'][0]['evidence'] = copy.deepcopy(first['candidates'][0]['evidence'])
        class Client(FakeClient):
            def generate(inner, **kwargs):
                if kwargs['response_type'] is ExtractionResponse:
                    inner.calls += 1
                    return ExtractionResponse.model_validate(first if inner.calls == 1 else second)
                return super().generate(**kwargs)
        self.assertEqual(len(extract_passages(self.doc, self.passages, Client()).facts), 2)

    def test_invalid_time_metadata_is_omitted_without_changing_claim(self):
        raw = self.base().candidates[0].model_dump(mode='json')
        raw['clinical_time'] = {'precision': 'unknown', 'basis': 'explicit', 'value': '2024-07-09'}
        response = ExtractionResponse.model_validate({'candidates': [raw], 'reviewed_passage_ids': [], 'unresolved': []})
        self.assertIsInstance(response.candidates[0], dict)
        fact, notes = checked_candidate(response.candidates[0], {p.id:p for p in self.passages}, self.doc, 'test')
        self.assertEqual(fact.clinical_time.precision, 'unknown')
        self.assertIsNone(fact.clinical_time.value)
        self.assertEqual(fact.assertion, 'negated')
        self.assertIn('invalid_time_metadata', notes)

    def test_malformed_date_cannot_support_corrected_day(self):
        t = ClinicalTime(precision='day', basis='explicit', value='2024-07-09', original_text='09/07/20244')
        with self.assertRaisesRegex(ValueError, 'date_not_supported'):
            check_time(t, ['Entlassen am 09/07/20244'], self.doc)
        t.original_text = '09.07.2024'
        check_time(t, ['Entlassen am 09.07.2024'], self.doc)

    def test_uncited_date_and_partial_date_precision(self):
        with self.assertRaises(ValueError):
            check_time(ClinicalTime(precision='day',basis='contextual',value='2024-07-09'), ['Keine Dyspnoe'], self.doc)
        check_time(ClinicalTime(precision='month',basis='explicit',value='2024-07'), ['Z.n. Krise 07/2024'],self.doc)
        with self.assertRaises(ValueError):
            check_time(ClinicalTime(precision='day',basis='explicit',value='2024-07-01'), ['07/2024'],self.doc)
        check_time(ClinicalTime(precision='day',basis='explicit',value='2024-07-09'), ['9. Juli 2024'],self.doc)

    def test_absence_is_not_resolution(self):
        candidate = self.base().candidates[0]
        candidate.clinical_status = 'resolved'
        with self.assertRaisesRegex(ValueError, 'absence_is_not_resolution'):
            check_status(candidate, ['Keine Dyspnoe'])
        check_status(candidate, ['Dyspnoe nicht mehr vorhanden'])

    def test_improvement_is_not_resolution(self):
        c = self.base().candidates[0]
        c.assertion = 'affirmed'
        c.clinical_status = 'resolved'
        with self.assertRaises(ValueError):
            check_status(c, ['Dyspnoe rückläufig'])

    def test_model_cannot_convert_duration_into_an_unsourced_number(self):
        from prep.extraction.narrative_models import Candidate
        raw = self.base().candidates[0].model_dump(mode='json')
        raw.update(category='functional_tests', value={'kind':'measurement','quantity':{'value':18.8833333,'unit':'h'}})
        candidate = Candidate.model_validate(raw)
        with self.assertRaisesRegex(ValueError, 'measurement_not_verbatim'):
            check_measurement(candidate, ['LZ-EKG über 21:10 Stunden'])
        candidate.value.quantity.value = 67
        check_measurement(candidate, ['HF von 47 - 100 (67)/min'])

    def test_chunking_covers_all_passages_preserving_offsets(self):
        batches = section_batches(self.passages, limit=40)
        self.assertGreater(len(batches), 1)
        self.assertEqual({p.id for p in self.passages}, {p.id for b in batches for p in b})
        for b in batches:
            self.assertEqual(len({p.id for p in b}),len(b))
            for p in b:
                self.assertEqual(self.doc.normalized_text[p.start:p.end],p.text)


if __name__ == '__main__':
    unittest.main()
