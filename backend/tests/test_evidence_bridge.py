"""Blocks 1-4 merged with 5-8, on the evidence backend's own independent synthetic
fixture (blocks14/contracts/examples/independent-patient.json). No network, no challenge
data: dense search off, LLM off, and the outbound gate configured for the fixture patient."""
import json
from pathlib import Path

import pytest

from app import outbound
from app.evidence_bridge import BLOCKS14, build_layer, load_bundle_file
from app.pipeline import Pipeline
from app.prompt_analysis import PromptAnalyzer
from app.remarker import Remarker
from app.summary import Finalizer
from app.tree import DecisionTree

FIXTURE = BLOCKS14 / "contracts" / "examples" / "independent-patient.json"
pytestmark = pytest.mark.skipif(not FIXTURE.exists(), reason="blocks14 fixture not present")


@pytest.fixture(scope="module")
def patient_dir(tmp_path_factory):
    """A patient folder in our input format, written from the fixture's documents."""
    bundle, _ = load_bundle_file(FIXTURE)
    root = tmp_path_factory.mktemp("independent-patient")
    (root / "documents").mkdir()
    docs_meta = []
    for d in bundle.documents:
        meta = {"id": d.id, "title": d.title, "type": "Arztbrief", "date": d.document_date.isoformat() if d.document_date else "",
                "hospital": "Testspital Ost", "department": "Innere"}
        docs_meta.append(meta)
        (root / "documents" / f"{d.id}.json").write_text(
            json.dumps({"metadata": meta, "text": d.original_text}, ensure_ascii=False), encoding="utf-8")
    (root / "patient.json").write_text(json.dumps(
        {"id": bundle.manifest.patient_id, "name": "Erika Beispiel", "sex": "female", "dateOfBirth": "1961-07-23"}),
        encoding="utf-8")
    (root / "documents.json").write_text(json.dumps({"documents": docs_meta}), encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def remarker(patient_dir):
    bundle, history = load_bundle_file(FIXTURE)
    return Remarker.for_patient(patient_dir, DecisionTree.load(), dense=False, rerank=False,
                                rebuild=True, evidence=(bundle, history))


def test_layer_maps_every_fact_to_our_segments(remarker):
    layer = remarker.evidence
    assert layer is not None and remarker.evidence_issue is None
    assert len(layer.facts) == 7 and layer.unmapped_quotes == 0
    assert all(f.segment_ids for f in layer.facts.values())
    assert len(layer.derived) == 2 and all(d.segment_ids for d in layer.derived)
    assert [c.status for c in layer.contradictions] == ["accepted"]


def test_facts_strengthen_flags_and_carry_structure(remarker):
    plan = PromptAnalyzer(remarker.tree, None, "off").analyse("GP, diabetes review, weight and medication")
    res = remarker.remark(plan)
    flagged = [f for it in res.items for f in it.flags if f.fact_ids]
    assert flagged, "no flag carries a verified fact"
    assert any("fact" in f.signals for f in flagged)
    med = next((f for f in flagged if f.structured and f.structured.get("kind") == "medication"), None)
    assert med is not None and med.structured["drug"]
    assert res.coverage["verified_facts"] == 7 and res.coverage["documents"] == 2


def test_derived_values_and_accepted_contradiction_reach_the_result(remarker):
    plan = PromptAnalyzer(remarker.tree, None, "off").analyse("GP, how did her weight change")
    res = remarker.remark(plan)
    concepts = {d.concept for d in res.derived}
    assert {"body_mass_index", "body_weight_change"} <= concepts
    change = next(d for d in res.derived if d.concept == "body_weight_change")
    assert change.value == -4.0 and "weight_bmi" in change.items and change.segment_ids
    accepted = [c for c in res.contradictions if c.status == "accepted"]
    assert accepted and accepted[0].source == "evidence_bundle" and accepted[0].kind == "number"


def test_end_to_end_without_network(remarker, patient_dir):
    outbound.reset_stats()
    patient = json.loads((patient_dir / "patient.json").read_text(encoding="utf-8"))
    pipe = Pipeline(PromptAnalyzer(remarker.tree, None, "off"), remarker, Finalizer(None, None, use_cache=False), patient)
    res = pipe.run("GP, diabetes review: weight change and current medication")
    f = res.final
    assert f.mode == "template_only" and f.summary
    assert any(c.kind == "finding" and "kg" in c.text for c in f.summary), [c.text for c in f.summary]
    assert f.conflicts and f.conflicts[0].confirmed_by == "rule"
    assert f.coverage["segments_searched"] > 0 and "verified_facts" in f.coverage
    assert f.privacy["refused"] == 0
    assert res.timings_ms["total"] < 2000
    # every cited passage exists and its text equals the document slice (traceability)
    docs = {d: v["text"] for d, v in remarker.ix.docs.items()}
    segs = {sg.seg.segment_id: sg.seg for sg in remarker.ix.segs}
    for c in f.summary:
        for sid in c.cites:
            s = segs[sid]
            assert docs[s.doc_id][s.start:s.end] == s.text


def test_missing_bundle_is_reported_not_fatal(patient_dir):
    rm = Remarker.for_patient(patient_dir, DecisionTree.load(), dense=False, rerank=False, evidence=True)
    assert rm.evidence is None and "Evidence package not used" in (rm.evidence_issue or "")
    plan = PromptAnalyzer(rm.tree, None, "off").analyse("GP review")
    res = rm.remark(plan)
    assert any("Evidence package not used" in i for i in res.issues)


def test_index_cache_on_disk_is_encrypted(remarker, patient_dir):
    from app import vault
    from app.remarker import CACHE_DIR
    folders = [p.parent for p in (CACHE_DIR / "remarker" / patient_dir.name).rglob("index.json")]
    assert folders
    for folder in folders:
        assert vault.is_encrypted(folder / "index.json") and vault.is_encrypted(folder / "arrays.npz")
        assert b"Gewicht" not in (folder / "index.json").read_bytes()  # document text unreadable on disk
