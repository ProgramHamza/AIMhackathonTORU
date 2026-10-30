"""Tests for block 8 with invented passages and a scripted fake LLM (no network, no dataset)."""
import time
from datetime import date

import pytest

from app.contracts import (Checklist, ChecklistEntry, ContradictionCandidate, Coverage, Flag,
                           ItemEvidence, LocalizedText, QueryPlan, RecordRelevance, RemarkerResult)
from app.llm_client import LLMError, LLMResult
from app.summary import Finalizer, check_claim

PATIENT = {"id": "x-1", "name": "Test Person", "sex": "female", "dateOfBirth": "1960-06-01"}


def flag(seg, text, doc="D1", d=date(2020, 1, 10), polarity="affirmed", sides=(), ridx=0.9, current=True):
    return Flag(segment_id=seg, doc_id=doc, start=0, end=len(text), text=text, section="", doc_date=d,
                ridx=ridx, signals={}, matched_terms=[], polarity=polarity, sides=list(sides), current=current)


def entry(item_id, priority="critical", time_rule="current"):
    return ChecklistEntry(item_id=item_id, label=LocalizedText(en=item_id, de=item_id),
                          question=f"What about {item_id}?", priority=priority, score=1.0, domains=[],
                          time_rule=time_rule, reasons=[])


def evidence(item_id, flags, priority="critical", status="found"):
    return ItemEvidence(item_id=item_id, label=LocalizedText(en=item_id.title(), de=item_id.title()),
                        priority=priority, status=status, flags=flags)


@pytest.fixture
def case():
    items = [
        evidence("blood_thinner", [flag("D1#1", "Drug A 100mg oral 1 0 0 0", doc="D1"),
                                   flag("D2#4", "Mentions dizziness only", doc="D2", ridx=0.55)]),
        evidence("allergy", [flag("D1#2", "Allergie: Kontrastmittel (Übelkeit)")]),
        evidence("kidney", [], priority="high", status="not_documented"),
        evidence("stenosis", [flag("D2#5", "60% Stenose der A. carotis links", doc="D2", sides=["left"])],
                 priority="high"),
    ]
    plan = QueryPlan(prompt="test doctor, test task", nodes=[],
                     checklist=Checklist(entries=[entry(e.item_id, e.priority) for e in items], suppressed=[]),
                     coverage=Coverage(content_words=0, accounted_words=0, unaccounted=[]))
    rem = RemarkerResult(
        patient_id="x-1", as_of=date(2020, 2, 1), items=items,
        records=[RecordRelevance(doc_id=d, title=d, date=date(2020, 1, 10), doc_type="t", score=0,
                                 label_counts={}, top_flags=[]) for d in ("D1", "D2", "D3")],
        contradictions=[ContradictionCandidate(segment_ids=["D2#5", "D3#7"], doc_ids=["D2", "D3"],
                                               differing=["links", "rechts"], kind="laterality")])
    return plan, rem


class Fake:
    def __init__(self, data=None, error=None, delay=0.0, model="fake"):
        self.data, self.error, self.delay, self.model = data or {}, error, delay, model
        self.messages = []

    def complete_json(self, system, user, schema, timeout):
        self.messages.append(user)
        time.sleep(self.delay)
        if self.error:
            raise LLMError(self.error)
        return LLMResult(self.data, self.delay * 1000, self.model)


def check(drops=(), order=()):
    return Fake({"drops": list(drops), "order": list(order)}, model="check")


def summ(entries=(), conflicts=()):
    return Fake({"summary": list(entries), "conflicts": list(conflicts)}, model="summary")


def llm(text, cites, item_id="stenosis", kind="finding"):
    return {"template": "", "text": text, "cites": cites, "item_id": item_id, "kind": kind}


def pid(fake, segment_text):
    """Find the passage ID the finalizer gave to a text, from the prompt it sent."""
    import json
    payload = json.loads(fake.messages[0])
    return next(p["id"] for p in payload["passages"] if p["text"].startswith(segment_text))


# --- claim checks ---------------------------------------------------------------------

@pytest.mark.parametrize("text,reason", [
    ("Drug A 100 mg in the morning.", None),
    ("Drug A 200 mg in the morning.", "numbers"),
    ("No allergy is documented.", "negation"),
    ("Stenosis of the right carotid artery.", "side"),
    ("Metformin is taken daily.", "drug"),
])
def test_check_claim(text, reason):
    cited = [flag("a", "Drug A 100mg oral 1 0 0 0"), flag("b", "Allergie: Kontrastmittel"),
             flag("c", "60% Stenose links", sides=["left"])]
    result = check_claim(text, cited, "finding")
    assert (result is None) if reason is None else (reason in result)


def test_check_claim_rejects_planned_as_done():
    cited = [flag("a", "Duplex control in 2 months recommended", polarity="planned")]
    assert "plan" in check_claim("A duplex control was performed.", cited, "finding")


def test_check_claim_accepts_comma_decimal():
    assert check_claim("HbA1c was 6.4%.", [flag("a", "HbA1c 6,4%")], "finding") is None


# --- finalize -------------------------------------------------------------------------

def test_template_only_without_llm(case):
    plan, rem = case
    res = Finalizer(None, None, use_cache=False).finalize(plan, rem, PATIENT)
    assert res.mode == "template_only"
    texts = " ".join(c.text for c in res.summary)
    assert "Drug A 100mg" in texts and "Allergie" in texts
    assert all(c.rendered_by == "template" for c in res.summary)
    assert res.patient.age_at_as_of == 59


def test_drop_removes_flag_and_updates_records(case):
    plan, rem = case
    a, b = check(), summ()
    Finalizer(a, b, use_cache=False).finalize(plan, rem, PATIENT)  # learn passage IDs
    p = pid(a, "Mentions dizziness")
    a2 = check(drops=[{"item_id": "blood_thinner", "passage": p, "reason": "irrelevant"}],
               order=["allergy", "blood_thinner"])
    res = Finalizer(a2, summ(), use_cache=False).finalize(plan, rem, PATIENT)
    bt = next(i for i in res.items if i.item_id == "blood_thinner")
    assert [f.segment_id for f in bt.flags] == ["D1#1"]
    assert bt.dropped[0].reason == "irrelevant"
    assert [i.item_id for i in res.items][:2] == ["allergy", "blood_thinner"]
    d2 = next(r for r in res.records if r.doc_id == "D2")
    assert "blood_thinner" not in d2.label_counts


def test_guard_keeps_strongest_passage(case):
    plan, rem = case
    a = check()
    Finalizer(a, summ(), use_cache=False).finalize(plan, rem, PATIENT)
    p = pid(a, "Allergie")
    res = Finalizer(check([{"item_id": "allergy", "passage": p, "reason": "irrelevant"}]), summ(),
                    use_cache=False).finalize(plan, rem, PATIENT)
    allergy = next(i for i in res.items if i.item_id == "allergy")
    assert allergy.status == "found" and len(allergy.flags) == 1
    assert any("kept the strongest" in i for i in res.issues)


def test_supported_llm_claim_is_kept_and_unsupported_replaced(case):
    plan, rem = case
    a, b = check(), summ()
    Finalizer(a, b, use_cache=False).finalize(plan, rem, PATIENT)
    p = pid(b, "60% Stenose")
    good = llm("Carotid stenosis of 60% on the left.", [p])
    bad = llm("Carotid stenosis of 80% on the right.", [p])
    res = Finalizer(check(), summ([good]), use_cache=False).finalize(plan, rem, PATIENT)
    assert any(c.rendered_by == "llm" and "60%" in c.text for c in res.summary)
    res = Finalizer(check(), summ([bad]), use_cache=False).finalize(plan, rem, PATIENT)
    assert not any(c.rendered_by == "llm" for c in res.summary)
    assert res.dropped_claims and "numbers" in res.dropped_claims[0]["reason"]
    assert any(c.item_id == "stenosis" and c.rendered_by == "template" for c in res.summary)


def test_claim_without_citation_is_dropped(case):
    plan, rem = case
    res = Finalizer(check(), summ([llm("Everything is fine.", [])]), use_cache=False).finalize(plan, rem, PATIENT)
    assert res.dropped_claims[0]["reason"] == "no citation"


def test_critical_items_always_in_summary(case):
    plan, rem = case
    res = Finalizer(check(), summ([]), use_cache=False).finalize(plan, rem, PATIENT)
    assert {"blood_thinner", "allergy"} <= {c.item_id for c in res.summary}


def test_conflict_rule_and_llm_verdict(case):
    plan, rem = case
    res = Finalizer(None, None, use_cache=False).finalize(plan, rem, PATIENT)
    assert len(res.conflicts) == 1 and res.conflicts[0].confirmed_by == "rule"


def test_llm_failure_and_timeout_fall_back(case):
    plan, rem = case
    res = Finalizer(Fake(error="boom"), Fake(delay=1.0), budget_s=0.3, use_cache=False).finalize(plan, rem, PATIENT)
    assert res.mode == "template_only"
    assert any("failed" in i for i in res.issues) and any("budget" in i for i in res.issues)
    assert res.timings_ms["total"] < 900
    assert res.summary


def test_calls_run_in_parallel(case):
    plan, rem = case
    t = time.perf_counter()
    Finalizer(Fake({"drops": [], "order": []}, delay=0.4), Fake({"summary": [], "conflicts": []}, delay=0.4),
              use_cache=False).finalize(plan, rem, PATIENT)
    assert time.perf_counter() - t < 0.7


def test_german_templates(case):
    plan, rem = case
    from app.summary import template_claim
    res = Finalizer(None, None, use_cache=False).finalize(plan, rem, PATIENT, lang="de")
    assert res.summary and all(c.lang == "de" for c in res.summary)
    kidney = next(i for i in res.items if i.item_id == "kidney")
    assert template_claim(kidney, "de", "T1").text == "Kidney: nicht dokumentiert."


def test_conflict_in_summary_only_when_relevant(case):
    plan, rem = case
    far = rem.model_copy(deep=True)
    far.contradictions[0].segment_ids = ["D3#1", "D3#2"]  # passages no item flagged
    res = Finalizer(None, None, use_cache=False).finalize(plan, far, PATIENT)
    assert res.conflicts and not any(c.kind == "conflict" for c in res.summary)
    far.contradictions[0].items = ["stenosis"]          # the remarker says it concerns an item
    res = Finalizer(None, None, use_cache=False).finalize(plan, far, PATIENT)
    assert any(c.kind == "conflict" for c in res.summary)


def _item(flags, priority="critical"):
    from app.final_contracts import ItemResult
    return ItemResult(item_id="x", label=LocalizedText(en="X", de="X"), priority=priority, status="found",
                      order=0, flags=flags)


def test_current_list_item_quotes_every_current_drug():
    from app.summary import template_claim
    old = date(2019, 1, 1)
    it = _item([flag("D1#1", "Drug A 30mg oral 0 1 0 0"), flag("D1#2", "Drug B 1000mg oral 1 1 1 0"),
                flag("D1#3", "Drug C 5 mcg s.c. 1 0 1 0"),
                flag("D0#1", "Drug C 5mcg 0,5 s.c. 1 0 1 0", doc="D0", d=old, current=False)])
    text = template_claim(it, "en", "T1", "current").text
    assert all(d in text for d in ("Drug A", "Drug B", "Drug C 5 mcg")) and "0,5" not in text


def test_history_item_drops_repeats_and_keeps_distinct_recommendations():
    from app.summary import template_claim
    it = _item([flag("D1#1", "Regelmäßige Augenkontrollen werden empfohlen."),
                flag("D2#1", "Regelmäßige augenärztliche Kontrollen empfohlen.", doc="D2"),
                flag("D1#2", "Karotis-Duplex in 3 Monaten.", ridx=0.85),
                flag("D1#3", "Regelmäßige Blutdruckkontrollen durch den Hausarzt.", ridx=0.8)], priority="high")
    c = template_claim(it, "en", "T1", "history")
    assert c.cites == ["D1#1", "D1#2", "D1#3"]


def test_repeat_check_keeps_different_numbers():
    from app.summary import _repeats
    assert not _repeats(flag("a", "HbA1c 7,1%"), [flag("b", "HbA1c 6,4%")])
    assert _repeats(flag("a", "Hormonrezeptor positiv, Ki67 20%"),
                    [flag("b", "Histologie: Karzinom, Hormonrezeptor positiv, Ki67 20%, G2")])


def test_latest_item_prefers_verified_older_value_over_vague_newer_line():
    from app.summary import template_claim
    vague = flag("D2#1", "Diab. Mell. II", doc="D2", d=date(2021, 1, 1), ridx=0.88)
    value = flag("D1#1", "HbA1c von 6,4%", doc="D1", d=date(2020, 1, 1), ridx=0.99, current=False)
    value.fact_ids = ["F1"]
    c = template_claim(_item([vague, value]), "en", "T1", "latest")
    assert c.cites[0] == "D1#1" and "2020-01-01" in c.text
