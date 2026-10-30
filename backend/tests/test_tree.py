"""Tests for block 5a, the decision graph.

The situation prompts are paraphrased from cases/situations.md. They check which
checklist items a request produces, not patient facts.
"""
import time

import pytest

from app.tree import Automaton, DecisionTree, compile_tree, normalize


@pytest.fixture(scope="module")
def tree() -> DecisionTree:
    compile_tree()
    return DecisionTree.load()


def items(checklist, priority=None):
    return {e.item_id for e in checklist.entries if priority is None or e.priority == priority}


def nodes(hits, sources=None):
    return {h.node_id for h in hits if sources is None or h.source in sources}


# --- the five situations ---------------------------------------------------------

def test_anaesthesia_preop(tree):
    hits, cl, _ = tree.plan(
        "Pre-operative anaesthesia check. You are the anaesthetist. Breast surgery is scheduled.")
    assert {"anaesthesiology", "preop", "surgery_planned", "region_breast"} <= nodes(hits)
    assert {"anticoagulants", "allergies", "cardiac_function"} <= items(cl, "critical")
    assert {"airway_aspiration_risk", "previous_anaesthesia"} <= items(cl, "critical")
    assert "tumour_receptors" not in items(cl)
    assert "tumour_receptors" in cl.suppressed


def test_surgeon_after_tumour_board(tree):
    hits, cl, _ = tree.plan(
        "Surgery planning after the tumour board. You are the surgeon planning her operation.")
    assert {"surgery", "surgery_planning", "tumour_board"} <= nodes(hits)
    assert {"cancer_histology", "cancer_staging", "tumour_receptors",
            "tumour_board_plan"} <= items(cl, "critical")


def test_gp_diabetes_review(tree):
    hits, cl, _ = tree.plan("Diabetes review at the GP. You are her GP, reviewing her diabetes.")
    assert {"general_practice", "chronic_review", "focus_diabetes"} <= nodes(hits)
    assert {"glucose_lowering", "diabetes_control", "weight_bmi"} <= items(cl, "critical")


def test_emergency_dizziness_vision(tree):
    hits, cl, _ = tree.plan(
        "Emergency department at night. You are the emergency physician. She arrives with "
        "dizziness and blurred vision.")
    assert {"emergency_medicine", "emergency", "symptom_neuro_vision"} <= nodes(hits)
    assert {"prior_similar_events", "anticoagulants", "allergies"} <= items(cl, "critical")
    assert {"contrast_reaction", "kidney_function", "contrast_relevant_meds",
            "antihypertensives"} <= items(cl)


def test_gp_open_followups(tree):
    hits, cl, _ = tree.plan("Open follow-ups from the hospital stay. You are her GP and check "
                            "which follow-ups are still open.")
    assert {"general_practice", "followup_review"} <= nodes(hits)
    assert {"followups_recommended", "followups_completed"} <= items(cl, "critical")
    assert "vascular_findings" in items(cl)


# --- generalisation --------------------------------------------------------------

def test_anaesthetist_liver_surgery(tree):
    _, cl, _ = tree.plan("anaesthetist, pre-operative check for liver surgery")
    assert "liver_function" in items(cl, "critical")
    assert "coagulation_bleeding" in items(cl)


def test_same_surgery_differs_by_role(tree):
    _, anaesthesia, _ = tree.plan("anaesthetist, pre-operative check before breast cancer surgery")
    _, surgeon, _ = tree.plan("surgeon, surgery planning for breast cancer")
    assert "tumour_receptors" in items(surgeon, "critical")
    assert "tumour_receptors" not in items(anaesthesia)
    assert "airway_aspiration_risk" in items(anaesthesia, "critical")
    assert "airway_aspiration_risk" not in items(surgeon)


def test_german_prompt(tree):
    hits, cl, _ = tree.plan("Anästhesistin, Prämedikation vor Leberoperation")
    assert {"anaesthesiology", "preop", "region_liver"} <= nodes(hits)
    assert "liver_function" in items(cl, "critical")


def test_unknown_role_falls_back_to_physician(tree):
    hits, cl, coverage = tree.plan("speech therapist assessment after discharge")
    assert nodes(hits, {"default"}) == {"physician"}
    assert "allergies" in items(cl, "critical")
    assert "speech" in coverage.unaccounted


def test_role_inherits_from_parent(tree):
    hits, cl, _ = tree.plan("senologist")  # names only breast_surgery
    assert {"surgery", "perioperative", "physician"} <= nodes(hits, {"ancestor"})
    assert {"anticoagulants", "allergies"} <= items(cl, "critical")


def test_typo_tolerance(tree):
    hits, _, coverage = tree.plan("anesthetsit, preoperative check")
    assert "anaesthesiology" in nodes(hits, {"fuzzy"})
    assert not coverage.unaccounted


def test_asked_item_overrides_suppression(tree):
    _, cl, _ = tree.plan("anaesthetist, pre-op check before breast surgery, also show the HER2 receptor status")
    entry = {e.item_id: e for e in cl.entries}["tumour_receptors"]
    assert entry.priority in ("critical", "high")
    assert "asked" in entry.reasons
    assert "tumour_receptors" not in cl.suppressed


def test_contrast_context(tree):
    _, cl, _ = tree.plan("radiologist, CT angiography with contrast")
    assert {"contrast_reaction", "kidney_function", "contrast_relevant_meds"} <= items(cl, "critical")


def test_reasons_are_recorded(tree):
    _, cl, _ = tree.plan("anaesthetist, pre-operative check")
    entry = {e.item_id: e for e in cl.entries}["airway_aspiration_risk"]
    assert entry.reasons == ["anaesthesia_preop"]


# --- graph mechanics ----------------------------------------------------------------

def test_concept_implies_context(tree):
    hits, cl, _ = tree.plan("gastroenterologist, ERCP")  # "*scopy" words match directly
    active = {h.node_id: h for h in hits}
    assert active["endoscopy"].source == "prompt"
    assert active["invasive_procedure"].source == "implied"
    assert active["invasive_procedure"].activation == pytest.approx(0.9)
    assert "anticoagulants" in items(cl, "critical")


def test_drug_class_by_word_ending(tree):
    hits, cl, coverage = tree.plan("cardiologist, patient on edoxaban and ramipril")
    assert {"anticoagulant_drug", "antihypertensive_drug"} <= {h.node_id for h in hits}
    assert {"anticoagulants", "antihypertensives"} <= items(cl, "critical")
    assert not coverage.unaccounted


def test_suffix_pattern(tree):
    hits, _, _ = tree.plan("anaesthetist, preop for cholecystectomy")
    assert "surgery_planned" in nodes(hits, {"prompt"})


def test_drug_concept_chain(tree):
    hits, cl, _ = tree.plan("oncologist, doxorubicin")
    assert {"cardiotoxic_therapy", "systemic_cancer_therapy", "focus_cancer"} <= nodes(hits)
    assert "cardiac_function" in items(cl, "critical")


def test_item_link_adds_related_item(tree):
    _, cl, _ = tree.plan("dentist, implant")  # no rule adds coagulation directly with a link only
    entry = {e.item_id: e for e in cl.entries}
    assert "anticoagulants" in entry


def test_link_never_beats_suppression(tree):
    act, _ = tree.activate({tree.node_index["anaesthesiology"]: 1.0, tree.node_index["preop"]: 1.0})
    cl = tree.score(act)
    assert "imaging_findings" in cl.suppressed and "imaging_findings" not in items(cl)


def test_llm_suggestion_cannot_unsuppress(tree):
    act, _ = tree.activate({tree.node_index["anaesthesiology"]: 1.0, tree.node_index["preop"]: 1.0})
    receptors = tree.item_index["tumour_receptors"]
    cl = tree.score(act, {receptors: 0.85}, {receptors: "llm"})
    assert "tumour_receptors" in cl.suppressed


def test_coverage_counts_content_words(tree):
    _, _, coverage = tree.plan("You are the anaesthetist, she has a rare zebra disease")
    assert set(coverage.unaccounted) == {"rare", "zebra", "disease"}
    assert coverage.content_words == 4


def test_normalize():
    assert normalize("Prä-Operative  Abklärung!") == "prae operative abklaerung"
    assert normalize("St.p. CHE.") == "st.p che"


def test_automaton_word_boundaries():
    a = Automaton()
    a.add("ent", False, "x")
    a.add("anaesthetist", True, "y")
    a.add("ectomy", False, "z", open_start=True)
    a.build()
    text = "patient anaesthetists ent cholecystectomy ectomyx"
    found = [(text[s:e], a.patterns[p][3]) for s, e, p in a.find(text)]
    assert ("ent", "x") in found and ("anaesthetist", "y") in found
    assert sum(1 for _, v in found if v == "x") == 1  # not inside "patient"
    assert sum(1 for _, v in found if v == "z") == 1  # suffix match, not "ectomyx"


def test_speed(tree):
    t = time.perf_counter()
    DecisionTree.load()
    load_ms = (time.perf_counter() - t) * 1000
    t = time.perf_counter()
    for _ in range(200):
        tree.plan("anaesthetist, pre-operative check before breast surgery")
    plan_ms = (time.perf_counter() - t) * 1000 / 200
    assert load_ms < 500  # once at startup; the graph has ~2,700 phrases
    assert plan_ms < 5
