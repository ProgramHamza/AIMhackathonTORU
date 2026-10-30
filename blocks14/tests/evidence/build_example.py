"""Rebuild the independently authored contract fixture; not a clinical generator."""
import hashlib
import json
from pathlib import Path

from prep.evidence.schema import EvidenceBundle

ROOT = Path(__file__).resolve().parents[2]


def build():
    texts = {
        "synthetic-d1": "Synthetischer Testbrief, 08.02.2024\nGewicht: 86 kg\n",
        "synthetic-d2": (
            "Synthetischer Testbrief, 12.03.2024\n"
            "Hinweis: vollständig erfundener Softwaretest 🧪\n"
            "Gewicht: 82 kg\nGröße: 180 cm\nBMI: 31,0\n"
            "Testpräparat Alpha 8 mg oral 1 0 0,5 0 Tabletten\n"
            "Kontrolle in zwei Monaten empfohlen.\n"
            "Keine Übelkeit.\n"
        ),
    }
    documents, passages = [], []
    for doc_id, text in texts.items():
        documents.append({"id": doc_id, "title": "Independent synthetic test letter",
                          "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
                          "document_date": "2024-02-08" if doc_id.endswith("1") else "2024-03-12",
                          "original_text": text, "normalized_text": text, "normalization_version": "identity-fixture-v1"})
        cursor = 0
        for number, line in enumerate(text.splitlines(keepends=True)):
            body = line.rstrip("\n")
            passages.append({"id": f"{doc_id}:p{number}", "document_id": doc_id, "kind": "paragraph",
                             "start": cursor, "end": cursor + len(body), "text": body})
            cursor += len(line)

    def ref(doc_id, quote):
        p = next(p for p in passages if p["document_id"] == doc_id and p["text"] == quote)
        return {"passage_id": p["id"], "start": p["start"], "end": p["end"], "quote": quote}

    def fact(id, category, concept, value, quote, doc="synthetic-d2", **extra):
        return {"id": id, "category": category, "concept": concept, "label": concept,
                "value": value, "assertion": "affirmed", "clinical_status": "unknown",
                "clinical_time": {"precision": "day", "value": "2024-02-08" if doc.endswith("1") else "2024-03-12",
                                  "basis": "document_fallback"},
                "evidence": [ref(doc, quote)], "extraction_method": "rule", "extractor_version": "manual-independent-fixture-v1",
                "validation": {"quote_match": "passed", "field_check": "passed", "semantic_check": "not_checked",
                               "notes": ["Independent contract fixture authored by an AI assistant; not clinician-reviewed."]}, **extra}

    facts = [
        fact("weight-old", "vitals", "body_weight", {"kind": "measurement", "quantity": {"value": 86, "unit": "kg"}}, "Gewicht: 86 kg", "synthetic-d1"),
        fact("weight-new", "vitals", "body_weight", {"kind": "measurement", "quantity": {"value": 82, "unit": "kg"}}, "Gewicht: 82 kg"),
        fact("height", "vitals", "body_height", {"kind": "measurement", "quantity": {"value": 180, "unit": "cm"}}, "Größe: 180 cm"),
        fact("bmi-stated", "vitals", "body_mass_index", {"kind": "measurement", "quantity": {"value": 31, "unit": "kg/m2"}}, "BMI: 31,0"),
        fact("medication", "medications", "test_preparation_alpha", {
            "kind": "medication", "drug_name": "Testpräparat Alpha", "strength": {"value": 8, "unit": "mg"},
            "route": "oral", "schedule": {"morning": 1, "midday": 0, "evening": 0.5, "night": 0,
                                            "dose_unit": "tablet", "original_text": "1 0 0,5 0 Tabletten"}},
             "Testpräparat Alpha 8 mg oral 1 0 0,5 0 Tabletten"),
        fact("followup", "followups", "clinical_review", {"kind": "event", "name": "Kontrolle", "timing_text": "in zwei Monaten"},
             "Kontrolle in zwei Monaten empfohlen.", clinical_status="recommended",
             clinical_time={"precision": "relative", "value": "in zwei Monaten", "basis": "explicit", "original_text": "in zwei Monaten"}),
        fact("nausea", "symptoms", "nausea", {"kind": "assertion", "text": "Keine Übelkeit."}, "Keine Übelkeit.", assertion="negated"),
    ]
    derived = [
        {"id": "bmi-calculated", "category": "vitals", "concept": "body_mass_index", "label": "Calculated BMI",
         "calculation": "bmi", "calculation_version": "bmi-v1", "input_fact_ids": ["weight-new", "height"],
         "result": {"value": round(82 / 1.8**2, 1), "unit": "kg/m2"}, "explanation": "82 / (180 / 100)^2, rounded to one decimal"},
        {"id": "weight-change", "category": "vitals", "concept": "body_weight_change", "label": "Weight change",
         "calculation": "weight_change", "calculation_version": "difference-v1", "input_fact_ids": ["weight-old", "weight-new"],
         "result": {"value": -4, "unit": "kg"}, "explanation": "Later minus earlier recorded weight: 82 - 86"},
    ]
    bundle = {"manifest": {"bundle_id": "independent-example", "patient_id": "synthetic-example-01",
                           "dataset_kind": "independent_synthetic", "evidence_version": "example-v1",
                           "prepared_at": "2026-10-30T00:00:00Z", "pipeline_version": "contract-example-only",
                           "configuration_hash": hashlib.sha256(b"manual-independent-fixture-v1").hexdigest(), "status": "complete"},
              "documents": documents, "passages": passages, "facts": facts, "derived_facts": derived,
              "contradictions": [{"id": "bmi-conflict", "kind": "numeric_inconsistency", "status": "accepted",
                                  "claim_ids": ["bmi-stated", "bmi-calculated"],
                                  "explanation": "Recorded BMI differs from calculation using height and weight in the same letter.",
                                  "evidence": [facts[i]["evidence"][0] for i in (3, 1, 2)],
                                  "detector_version": "manual-independent-fixture-v1", "review_method": "rules"}]}
    return EvidenceBundle.model_validate(bundle)


if __name__ == "__main__":
    target = ROOT / "contracts/examples/independent-patient.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build().model_dump_json(indent=2) + "\n", encoding="utf-8")
