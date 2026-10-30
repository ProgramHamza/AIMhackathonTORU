"""Tests for the segmenter and the remarker on an invented mini patient (no real data, no network)."""
import json
import zlib
from datetime import date

import numpy as np
import pytest

from app.contracts import CustomQuestion
from app.prompt_analysis import PromptAnalyzer
from app.remarker import Remarker, RemarkerIndex, _polarity
from app.segmenter import Document, clean_text, segment_document
from app.tree import DecisionTree, normalize

LETTER_2015 = ("Frau<BR>Testpatientin<BR>PLZ Ort<BR><BR>Diagnosen:<BR>Arterielle Hypertonie<BR>"
               "Vorhofflimmern<BR><BR>Allergien:<BR>Penicillin-Allergie (Exanthem)<BR><BR>"
               "Befunde:<BR>Gewicht: 80 kg<BR>Kein Perikarderguss.<BR><BR>"
               "Therapie und Verlauf:<BR>Die Patientin wurde mit Schwindel aufgenommen. Die Ursache war eine<BR>"
               "hypertensive Entgleisung. Eine Kontrolle beim Hausarzt wird empfohlen.<BR><BR>"
               "Entlassungsmedikation:<BR>Xarelto 20mg oral 1 0 0 0 ST<BR>Ramipril 5mg oral 1 0 0 0 ST<BR>"
               "Mit freundlichen Grüßen<BR>Dr. Arzt")
LETTER_2016 = ("Frau<BR>Testpatientin<BR><BR>Diagnosen:<BR>Arterielle Hypertonie<BR><BR>"
               "Befunde:<BR>Gewicht: 72 kg<BR><BR>"
               "Entlassungsmedikation:<BR>Xarelto 20mg oral 1 0 0 0 ST<BR>Ramipril 5mg oral 1 0 1 0 ST<BR>"
               "Mit freundlichen Grüßen<BR>Dr. Arzt")
DUPLEX_A = "Befund:<BR>Links zeigt sich an der A. carotis interna eine Stenose von etwa 50 Prozent durch Plaques."
DUPLEX_B = "Befund:<BR>Rechts zeigt sich an der A. carotis interna eine Stenose von etwa 50 Prozent durch Plaques."


def _doc(i, d, text, title="Patientenbrief"):
    return {"metadata": {"id": i, "title": title, "type": "Arztbrief", "date": d}, "text": text}


@pytest.fixture(scope="module")
def patient_dir(tmp_path_factory):
    p = tmp_path_factory.mktemp("patient-test")
    (p / "documents").mkdir()
    docs = [_doc("D1", "2015-06-20", LETTER_2015), _doc("D2", "2016-04-15", LETTER_2016),
            _doc("R1", "2015-06-18", DUPLEX_A, "Radiologischer Befund"),
            _doc("R2", "2015-06-19", DUPLEX_B, "Radiologischer Befund")]
    for d in docs:
        (p / "documents" / f"{d['metadata']['id']}.json").write_text(json.dumps(d), encoding="utf-8")
    (p / "patient.json").write_text(json.dumps({"id": "test-0001"}), encoding="utf-8")
    med = {"values": [{"name": "B01", "values": [{"code": {"value": "B01AF01"}, "name": "Rivaroxaban",
           "values": [{"text": "Xarelto 20mg   oral   1   0   0   0   ST", "documentIds": ["D2"]}]}]},
                      {"name": "C09", "values": [{"code": {"value": "C09AA05"}, "name": "Ramipril",
           "values": [{"text": "Ramipril 5mg oral 1 0 1 0 ST", "documentIds": ["D2"]},
                      {"text": "Ramipril 5mg oral 1 0 0 0 ST", "documentIds": ["D1"]}]}]}]}
    (p / "medication.json").write_text(json.dumps(med), encoding="utf-8")
    return p


class FakeEmbedder:
    """Deterministic bag-of-words vectors, so dense search works offline."""

    def __init__(self):
        self.calls = 0

    def embed(self, texts, task, timeout=30.0, wait_on_quota=False):
        self.calls += 1
        m = np.zeros((len(texts), 256), np.float32)
        for r, t in enumerate(texts):
            for w in normalize(t).split():
                m[r, zlib.crc32(w.encode()) % 256] += 1
        n = np.linalg.norm(m, axis=1, keepdims=True)
        return m / np.where(n == 0, 1, n)


@pytest.fixture(scope="module")
def tree():
    return DecisionTree.load()


@pytest.fixture(scope="module")
def remarker(patient_dir, tree):
    emb = FakeEmbedder()
    ix = RemarkerIndex.build(patient_dir, tree, emb, None)
    return Remarker(ix, tree, emb)


def plan(tree, prompt):
    return PromptAnalyzer(tree, None, "off").analyse(prompt)


def evidence(result, item):
    return next(e for e in result.items if e.item_id == item)


# --- segmenter -----------------------------------------------------------------------

def test_segments_have_exact_offsets_and_kinds():
    doc = Document("D1", "Brief", "Arztbrief", date(2015, 6, 20), clean_text(LETTER_2015))
    segs = segment_document(doc)
    assert all(doc.text[s.start:s.end] == s.text for s in segs)
    kinds = {s.text: s.kind for s in segs}
    assert kinds["Diagnosen:"] == "header" and kinds["Gewicht: 80 kg"] == "field"
    assert kinds["Xarelto 20mg oral 1 0 0 0 ST"] == "table_row"
    assert kinds["Frau"] == "boilerplate"


def test_wrapped_lines_are_joined_into_sentences():
    doc = Document("D1", "Brief", "Arztbrief", None, clean_text(LETTER_2015))
    sentences = [s.text.replace("\n", " ") for s in segment_document(doc) if s.kind == "sentence"]
    assert "Die Ursache war eine hypertensive Entgleisung." in sentences


def test_abbreviations_do_not_split_sentences():
    doc = Document("X", "", "", None, "Befund:\nStenose der A. carotis li. Seite bei Dr. Muster.")
    texts = [s.text for s in segment_document(doc) if s.kind == "sentence"]
    assert texts == ["Stenose der A. carotis li. Seite bei Dr. Muster."]


# --- polarity ----------------------------------------------------------------------------

@pytest.mark.parametrize("text,term,expected", [
    ("Kein Perikarderguss", "perikarderguss", "negated"),
    ("Raumforderungen sind nicht erkennbar", "raumforderungen", "negated"),
    ("St.p. hypertensiver Krise", "hypertensiver krise", "past"),
    ("Fragestellung: Ischaemie?", "ischaemie", "uncertain"),
    ("Kontrolle in 2 Monaten empfohlen", "kontrolle", "planned"),
    ("Her2neu negativ", "her2neu", "affirmed"),
])
def test_polarity(text, term, expected):
    norm = normalize(text)
    s = norm.index(term)
    assert _polarity(norm, text, "", [(s, s + len(term))]) == expected


# --- remarker ----------------------------------------------------------------------------

def test_allergy_found_with_exact_highlight(remarker, tree):
    res = remarker.remark(plan(tree, "anaesthetist, pre-operative check"))
    ev = evidence(res, "allergies")
    assert ev.status == "found"
    top = ev.flags[0]
    assert "Penicillin" in top.text and remarker.ix.docs[top.doc_id]["text"][top.start:top.end] == top.text


def test_current_value_comes_from_newest_document(remarker, tree):
    res = remarker.remark(plan(tree, "emergency physician, dizziness"))
    ev = evidence(res, "anticoagulants")
    current = {f.doc_id for f in ev.flags if f.current}
    assert current == {"D2"}


def test_changed_dose_is_not_merged_as_duplicate(remarker, tree):
    res = remarker.remark(plan(tree, "GP, blood pressure review"))
    ev = evidence(res, "antihypertensives")
    docs = {f.doc_id for f in ev.flags} | {d.split("#")[0] for f in ev.flags for d in f.duplicates}
    assert {"D1", "D2"} <= docs
    assert [f.doc_id for f in ev.flags if f.current] == ["D2"]


def test_laterality_contradiction_candidate(remarker):
    kinds = {(tuple(sorted(c.doc_ids)), c.kind) for c in remarker.ix.contradictions}
    assert (("R1", "R2"), "laterality") in kinds


def test_dose_change_between_stays_is_not_a_contradiction(remarker):
    assert not any(c.kind == "number" and set(c.doc_ids) == {"D1", "D2"} for c in remarker.ix.contradictions)


def test_llm_terms_reach_new_passages_with_their_polarity(remarker, tree):
    p = plan(tree, "cardiologist, heart function")
    entry = next(e for e in p.checklist.entries if e.item_id == "cardiac_function")
    entry.terms["llm"] = ["Perikarderguss"]
    boost = remarker._llm_terms(p)["cardiac_function"]
    k = next(k for k, sg in enumerate(remarker.ix.segs) if "Perikarderguss" in sg.seg.text)
    assert boost[k] > 0 and remarker.ix.segs[k].polarity == "negated"


def test_as_of_excludes_newer_documents(remarker, tree):
    p = plan(tree, "GP, weight review").model_copy(update={"as_of": date(2015, 12, 31)})
    res = remarker.remark(p)
    assert all(f.doc_date <= date(2015, 12, 31) for e in res.items for f in e.flags)


def test_prior_episode_uses_prompt_symptoms(remarker, tree):
    res = remarker.remark(plan(tree, "emergency physician, she has dizziness again"))
    ev = evidence(res, "prior_similar_events")
    assert ev.status == "found" and any("Schwindel" in f.text for f in ev.flags)


def test_no_api_call_without_custom_questions(remarker, tree):
    before = remarker.embedder.calls
    res = remarker.remark(plan(tree, "anaesthetist, pre-operative check"))
    assert res.api_calls == 0 and remarker.embedder.calls == before


def test_custom_questions_are_one_batched_call(remarker, tree):
    p = plan(tree, "GP review").model_copy(update={"custom_questions": [
        CustomQuestion(question="Rash after antibiotics?", search_terms_de=["Exanthem", "Penicillin"],
                       search_terms_en=["rash"]),
        CustomQuestion(question="Weight?", search_terms_de=["Gewicht"], search_terms_en=["weight"])]})
    res = remarker.remark(p)
    assert res.api_calls == 1
    assert res.custom[0].status == "found" and "Penicillin" in res.custom[0].flags[0].text


def test_records_are_ranked(remarker, tree):
    res = remarker.remark(plan(tree, "anaesthetist, pre-operative check"))
    scores = [r.score for r in res.records]
    assert scores == sorted(scores, reverse=True) and res.records[0].label_counts


def test_index_round_trip(remarker, tmp_path):
    remarker.ix.save(tmp_path, "fp1")
    loaded = RemarkerIndex.load(tmp_path, "fp1")
    assert loaded is not None and np.allclose(loaded.base, remarker.ix.base)
    assert RemarkerIndex.load(tmp_path, "other") is None
