import json
import tempfile
import unittest
from pathlib import Path

from prep.evidence.schema import EvidenceBundle
from prep.extraction.medication import extract_medications, parse_row
from prep.ingestion.documents import load_document, normalize, segment_document
from prep.preparation import prepare_patient, write_bundle


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def source(self, text, doc_id="independent-test", meta_date="2024-03-08"):
        path = self.root / f"{doc_id}.json"
        path.write_text(json.dumps({"metadata": {"id": doc_id, "title": "Independent fixture", "date": meta_date},
                                    "text": text}, ensure_ascii=False), encoding="utf-8")
        return load_document(path)

    def table(self, rows, header="Applikation mo mi ab na Einheit Info"):
        return "Ort, am 08.03.2024<BR><BR>Entlassungsmedikation:<BR>" + header + "<BR>" + rows + "<BR>Mit freundlichen Grüßen<BR>Signatur"

    def test_normalization_retains_comparisons_and_unicode(self):
        self.assertEqual(normalize("ä 🧪<BR/>a &gt; b\r\n<SPAN class='x'>x</SPAN>&nbsp;y"), "ä 🧪\na > b\nx y")

    def test_paragraphs_preserve_abbreviations_and_line_context(self):
        doc = self.source("Anamnese:<BR>Pat. berichtet am 03.02.2024<BR>keine Beschwerden.<BR><BR>Weitere Angaben.")
        passages = segment_document(doc)
        self.assertEqual(len(passages), 3)
        self.assertEqual(passages[1].text, "Pat. berichtet am 03.02.2024\nkeine Beschwerden.")
        for p in passages:
            self.assertEqual(doc.normalized_text[p.start:p.end], p.text)

    def test_ids_stable_and_source_versioned(self):
        doc = self.source("Abschnitt 🧪<BR>Text")
        a = segment_document(doc)
        self.assertEqual(a, segment_document(doc))
        revised = self.source("Abschnitt 🧪<BR>Text geändert")
        self.assertNotEqual(a[0].id, segment_document(revised)[0].id)

    def test_letter_date_overrides_metadata_without_repair(self):
        doc = self.source("Ort, am 08.03.2024<BR>Text", meta_date="2025-01-01")
        self.assertEqual(doc.document_date.isoformat(), "2024-03-08")
        invalid = self.source("Ort, am 31.02.2024<BR>Text", meta_date="2025-01-01")
        self.assertIsNone(invalid.document_date)

    def test_arbitrary_names_fraction_and_decimal_strength(self):
        value = parse_row("Testmittel Zeta 7,5 mg   oral  1 0 1/2 0 ST")
        self.assertEqual(value["drug_name"], "Testmittel Zeta")
        self.assertEqual(value["strength"], {"value": 7.5, "unit": "mg"})
        self.assertEqual(value["schedule"]["evening"], 0.5)
        self.assertEqual(value["schedule"]["night"], 0)
        self.assertNotIn("dose", value)

    def test_weekly_has_no_invented_daily_slots(self):
        for suffix in ("ST 1x/Woche 1 Tabl.", "1x/Woche 1 Tabl."):
            value = parse_row("Testmittel Eta 35mg oral " + suffix)
            self.assertEqual(value["schedule"]["frequency_text"], suffix)
            self.assertNotIn("morning", value["schedule"])

    def test_subcutaneous_and_missing_dose_unit(self):
        value = parse_row("Testmittel Theta 3 mcg s. c. 1 0 1 0")
        self.assertEqual(value["route"], "subcutaneous")
        self.assertEqual(value["strength"]["unit"], "µg")
        self.assertIsNone(value["schedule"]["dose_unit"])

    def test_unlabelled_quantity_is_not_guessed(self):
        with self.assertRaises(ValueError):
            parse_row("Testmittel Theta 3 mcg 0,7 s.c. 1 0 1 0")

    def test_conditional_and_discontinued_rows_are_not_active(self):
        for row in ("Testmittel abgesetzt 5mg oral 1 0 0 0 ST", "Testmittel 5mg oral 1 0 0 0 ST bei Bedarf"):
            with self.assertRaises(ValueError):
                parse_row(row)

    def test_bad_fraction_cannot_produce_fact(self):
        doc = self.source(self.table("Testmittel 5mg oral 1 0 1/0 0 ST"))
        facts, gaps = extract_medications(doc, segment_document(doc))
        self.assertEqual(facts, [])
        self.assertEqual(len(gaps), 1)

    def test_header_required_for_four_slot_interpretation(self):
        doc = self.source(self.table("Testmittel 5mg oral 1 0 0 0 ST", "Applikation ab mo mi na"))
        facts, gaps = extract_medications(doc, segment_document(doc))
        self.assertEqual(facts, [])
        self.assertGreater(len(gaps), 0)

    def test_row_header_and_section_cited(self):
        doc = self.source(self.table("Testmittel 5mg oral 1 0 0 0 ST"))
        facts, gaps = extract_medications(doc, segment_document(doc))
        self.assertEqual(len(facts), 1)
        self.assertEqual(gaps, [])
        self.assertEqual(len(facts[0].evidence), 3)
        self.assertEqual(facts[0].clinical_status, "unknown")
        self.assertEqual(facts[0].clinical_time.basis, "document_fallback")

    def test_outside_table_is_not_misclassified(self):
        doc = self.source("Anamnese:<BR>Testmittel 5mg oral 1 0 0 0 ST")
        facts, _ = extract_medications(doc, segment_document(doc))
        self.assertEqual(facts, [])

    def test_same_quote_gets_distinct_occurrence_offsets(self):
        row = "Testmittel 5mg oral 1 0 0 0 ST"
        doc = self.source(self.table(row + "<BR>" + row))
        facts, _ = extract_medications(doc, segment_document(doc))
        self.assertEqual(len(facts), 2)
        self.assertNotEqual(facts[0].evidence[0].start, facts[1].evidence[0].start)
        self.assertNotEqual(facts[0].id, facts[1].id)

    def test_end_to_end_write_version_and_explicit_partial_scope(self):
        self.source(self.table("Testmittel 5mg oral 1 0 0 0 ST"))
        bundle = prepare_patient(self.root, "synthetic-only", "independent_synthetic")
        again = prepare_patient(self.root, "synthetic-only", "independent_synthetic")
        self.assertEqual(bundle.manifest.evidence_version, again.manifest.evidence_version)
        self.assertEqual(bundle.manifest.status, "partial")
        self.assertEqual(len(bundle.facts), 1)
        output = self.root / "out" / "bundle.json"
        write_bundle(bundle, output)
        self.assertEqual(EvidenceBundle.model_validate_json(output.read_text(encoding="utf-8")), bundle)
        self.assertEqual(list(output.parent.iterdir()), [output])

    def test_malformed_source_fails_before_writing(self):
        (self.root / "bad.json").write_text('{"text": 12}', encoding="utf-8")
        with self.assertRaises(ValueError):
            prepare_patient(self.root, "synthetic-only")


if __name__ == "__main__":
    unittest.main()
