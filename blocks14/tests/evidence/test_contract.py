import copy
import json
import unittest
from pathlib import Path
from typing import get_args

from pydantic import ValidationError
from prep.evidence.catalog import CATEGORIES
from prep.evidence.schema import Category, ClinicalTime, EvidenceBundle

ROOT = Path(__file__).resolve().parents[2]


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / "contracts/examples/independent-patient.json").read_text(encoding="utf-8"))

    def reject(self):
        with self.assertRaises(ValidationError):
            EvidenceBundle.model_validate(self.data)

    def test_example_roundtrip(self):
        bundle = EvidenceBundle.model_validate(self.data)
        self.assertEqual(EvidenceBundle.model_validate_json(bundle.model_dump_json()), bundle)

    def test_category_catalog_matches_enum(self):
        self.assertEqual(set(get_args(Category)), {c[0] for c in CATEGORIES})

    def test_generated_schema_is_current(self):
        schema = json.loads((ROOT / "contracts/evidence-bundle.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema, EvidenceBundle.model_json_schema())

    def test_fabricated_quote_rejected(self):
        self.data["facts"][0]["evidence"][0]["quote"] = "not in document"
        self.reject()

    def test_wrong_passage_offset_rejected(self):
        self.data["passages"][0]["start"] += 1
        self.reject()

    def test_repeated_quote_wrong_passage_rejected(self):
        original = self.data["passages"][0]
        duplicate = copy.deepcopy(original)
        duplicate["id"] += "-duplicate"
        doc = self.data["documents"][0]
        duplicate["start"] = len(doc["normalized_text"])
        doc["normalized_text"] += duplicate["text"]
        duplicate["end"] = len(doc["normalized_text"])
        self.data["passages"].append(duplicate)
        self.data["facts"][0]["evidence"][0] = {
            "passage_id": duplicate["id"], "start": original["start"], "end": original["end"], "quote": original["text"]}
        self.reject()

    def test_unicode_offsets_use_codepoints(self):
        bundle = EvidenceBundle.model_validate(self.data)
        doc = bundle.documents[1]
        fact = next(f for f in bundle.facts if f.id == "weight-new")
        ref = fact.evidence[0]
        self.assertEqual(doc.normalized_text[ref.start:ref.end], ref.quote)
        utf16_start = len(doc.normalized_text[:ref.start].encode("utf-16-le")) // 2
        self.assertEqual(utf16_start, ref.start + 1)

    def test_duplicate_fact_id_rejected(self):
        self.data["facts"].append(copy.deepcopy(self.data["facts"][0]))
        self.reject()

    def test_unknown_derived_input_rejected(self):
        self.data["derived_facts"][0]["input_fact_ids"][0] = "missing"
        self.reject()

    def test_conflict_requires_all_evidence(self):
        self.data["contradictions"][0]["evidence"].pop()
        self.reject()

    def test_processing_gap_requires_partial_status(self):
        self.data["processing_gaps"] = [{"id": "g1", "stage": "extraction", "document_ids": ["synthetic-d1"],
                                         "reason": "Model timeout", "retryable": True}]
        self.reject()
        self.data["manifest"]["status"] = "partial"
        EvidenceBundle.model_validate(self.data)

    def test_not_documented_is_not_a_fact_assertion(self):
        self.data["facts"][0]["assertion"] = "not_documented"
        self.reject()

    def test_partial_and_invalid_dates(self):
        value = ClinicalTime(precision="month", value="2024-03", basis="explicit")
        self.assertEqual(value.value, "2024-03")
        with self.assertRaises(ValidationError):
            ClinicalTime(precision="day", value="2024-02-31", basis="explicit")

    def test_strength_schedule_and_negation_are_preserved(self):
        bundle = EvidenceBundle.model_validate(self.data)
        med = next(f for f in bundle.facts if f.id == "medication")
        self.assertEqual(med.value.strength.value, 8)
        self.assertIsNone(med.value.dose)
        self.assertEqual(med.value.schedule.evening, 0.5)
        self.assertEqual(next(f for f in bundle.facts if f.id == "nausea").assertion, "negated")

    def test_incompatible_category_payload_rejected(self):
        self.data["facts"][0]["category"] = "medications"
        self.reject()

    def test_unknown_fields_rejected(self):
        self.data["facts"][0]["confidence_medically_correct"] = 0.99
        self.reject()


if __name__ == "__main__":
    unittest.main()
