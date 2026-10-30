import tempfile
import unittest
from pathlib import Path
import json

from prep.extraction.structured import extract_structured
from prep.ingestion.documents import load_document, segment_document
from prep.preparation import prepare_patient


class StructuredTests(unittest.TestCase):
    def run_text(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "independent.json"
            path.write_text(json.dumps({"metadata": {"id": "test", "date": "2024-07-09"}, "text": text}, ensure_ascii=False), encoding="utf-8")
            doc = load_document(path)
            passages = segment_document(doc)
            facts, gaps = extract_structured(doc, passages)
            # Validate all source and relational links through the actual preparation flow.
            bundle = prepare_patient(Path(directory), "synthetic", "independent_synthetic")
            self.assertEqual(len(bundle.facts), len(facts))
            return facts, gaps

    def test_labelled_measurements_preserve_units_and_stated_bmi(self):
        facts, _ = self.run_text("Vitalparameter:<BR>Gewicht: 74,5 kg<BR>Größe: 1,82 m<BR>BMI: 30,1<BR>Körpertemperatur: 37,2°C")
        values = {f.concept: f.value.quantity for f in facts}
        self.assertEqual(values["body_weight"].value, 74.5)
        self.assertEqual(values["body_height"].unit, "m")
        self.assertEqual(values["body_mass_index"].value, 30.1)  # No silent repair.

    def test_bp_components_share_event_and_keep_header(self):
        facts, _ = self.run_text("RR bei Aufnahme:<BR>126/79 mmHg")
        self.assertEqual([f.value.quantity.value for f in facts], [126, 79])
        self.assertEqual(facts[0].event_id, facts[1].event_id)
        self.assertEqual(len(facts[0].evidence), 2)

    def test_unlabelled_pressure_not_interpreted(self):
        facts, _ = self.run_text("Sonstiges:<BR>126/79 mmHg")
        self.assertEqual(facts, [])

    def test_percent_unit_and_document_fallback(self):
        facts, _ = self.run_text("Labor:<BR>HbA1c: 7,3%<BR><BR>Echo:<BR>LV-Funktion (EF 58%)")
        self.assertEqual({f.concept for f in facts}, {"hba1c", "ejection_fraction"})
        self.assertTrue(all(f.clinical_time.basis == "document_fallback" for f in facts))

    def test_negated_target_and_family_values_not_patient_measurements(self):
        for text in ("Kein HbA1c: 7,3% dokumentiert", "Zielwert HbA1c: 7,3%", "Familienanamnese:<BR>HbA1c: 7,3%"):
            facts, gaps = self.run_text(text)
            self.assertEqual(facts, [])
            self.assertTrue(gaps)

    def test_ranges_and_wrong_units_not_truncated(self):
        facts, _ = self.run_text("BMI: 24 mmol/mol<BR>HF 48-90/min<BR>Gewicht: 74 lb")
        self.assertEqual(facts, [])

    def test_allergy_reactions_and_negative_statement(self):
        facts, _ = self.run_text("Allergien:<BR>Penicillin-Allergie (Exanthem, Juckreiz)")
        self.assertEqual(facts[0].value.substance, "Penicillin")
        self.assertEqual(facts[0].value.reactions, ["Exanthem", "Juckreiz"])
        negative, _ = self.run_text("Allergien:<BR>Keine bekannten Allergien.")
        self.assertEqual(negative[0].assertion, "negated")

    def test_missing_or_unclear_allergy_not_no_allergy(self):
        facts, gaps = self.run_text("Allergien:<BR>Unklar")
        self.assertEqual(facts, [])
        self.assertTrue(gaps)
        facts, _ = self.run_text("Anamnese:<BR>Patient wohlauf.")
        self.assertEqual(facts, [])

    def test_tnm_is_recorded_not_inferred(self):
        facts, _ = self.run_text("Histologie:<BR>T1 N0 M0 V0 G1")
        self.assertEqual(facts[0].value.value, "T1 N0 M0 V0 G1")
        facts, _ = self.run_text("Tumorgröße: 2 cm")
        self.assertEqual(facts, [])

    def test_receptor_status_percent_and_allred_stay_associated(self):
        facts, _ = self.run_text("Profil:<BR>Östrogenrezeptor: positiv (90% rezeptorpositive Tumorzellen) Allred-Score: 7 Progesteronrezeptor: positiv (40% rezeptorpositive Tumorzellen) Allred-Score: 5 Her2neu-Expression: negativ")
        by_concept = {f.concept: f for f in facts}
        self.assertEqual(by_concept["estrogen_receptor_percent"].value.quantity.value, 90)
        self.assertEqual(by_concept["progesterone_receptor_allred"].value.quantity.value, 5)
        self.assertEqual(by_concept["her2"].value.value, "negativ")
        self.assertEqual(by_concept["her2"].assertion, "affirmed")  # An affirmed negative test result.

    def test_ki67_and_unknown_result(self):
        facts, _ = self.run_text("Ki67-Proliferationsrate: 18%<BR>HER2: unklar")
        self.assertEqual([f.concept for f in facts], ["ki67"])

    def test_explicit_dates_and_invalid_date_gap(self):
        facts, gaps = self.run_text("Aufnahme am 02/07/2024 | Entlassen am 09/07/20244<BR>Entnahmedatum: 04.07.2024")
        self.assertEqual({f.concept for f in facts}, {"admission", "specimen_collection"})
        self.assertTrue(all(f.clinical_time.basis == "explicit" for f in facts))
        self.assertEqual(len(gaps), 1)

    def test_multiple_values_same_line_do_not_collide(self):
        facts, _ = self.run_text("HbA1c: 7,3%; HbA1c: 7,4%")
        self.assertEqual(len(facts), 2)
        self.assertNotEqual(facts[0].id, facts[1].id)

    def test_suspected_stage_not_confirmed(self):
        facts, gaps = self.run_text("Verdacht auf T2 N1 M0 V0 G2")
        self.assertEqual(facts, [])
        self.assertTrue(gaps)

    def test_planned_admission_not_completed(self):
        facts, gaps = self.run_text("Geplante Aufnahme am 02/08/2024")
        self.assertEqual(facts, [])
        self.assertTrue(gaps)


if __name__ == "__main__":
    unittest.main()
