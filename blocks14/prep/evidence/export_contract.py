"""Run from repository root: python -m prep.evidence.export_contract."""
import json
from pathlib import Path
from prep.evidence.catalog import CATEGORIES
from prep.evidence.schema import EvidenceBundle
from prep.evidence.normalization import NormalizationIndex, ALIASES, VERSION
from prep.evidence.reconciliation import ReconciliationIndex
from prep.evidence.contradictions import ContradictionReport


def main():
    target = Path(__file__).resolve().parents[2] / "contracts"
    target.mkdir(exist_ok=True)
    (target / "evidence-bundle.schema.json").write_text(
        json.dumps(EvidenceBundle.model_json_schema(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    catalog = {"version": "1.0.0", "categories": [
        {"id": key, "label": label, "scope": scope, "suggested_ui": ui}
        for key, label, scope, ui in CATEGORIES
    ]}
    (target / "evidence-categories.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (target / "normalization-index.schema.json").write_text(
        json.dumps(NormalizationIndex.model_json_schema(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (target / "concept-aliases.json").write_text(
        json.dumps({"version": VERSION, "aliases": ALIASES}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (target / "reconciliation-index.schema.json").write_text(
        json.dumps(ReconciliationIndex.model_json_schema(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (target / "contradiction-report.schema.json").write_text(
        json.dumps(ContradictionReport.model_json_schema(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
