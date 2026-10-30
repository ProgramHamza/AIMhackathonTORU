"""Tests for block 5b with a scripted fake LLM (no network)."""
import pytest

from app.llm_client import FallbackClient, LLMError, LLMResult, render_user
from functools import partial

from app.prompt_analysis import PromptAnalyzer as _PromptAnalyzer

PromptAnalyzer = partial(_PromptAnalyzer, cache_file=None)  # no shared disk cache in tests
from app.tree import DecisionTree


class FakeClient:
    provider = "fake"
    model = "fake"

    def __init__(self, data=None, error=None, context_tokens=1_000_000):
        self.data, self.error, self.calls = data or {}, error, []
        self.context_tokens = context_tokens

    def complete_json(self, system, user, schema, timeout):
        self.calls.append(render_user(user, self.context_tokens))
        if self.error:
            raise LLMError(self.error)
        base = {"role": "", "add_nodes": [], "remove_nodes": [], "add_items": [], "item_terms": [],
                "custom_questions": [], "as_of": "", "issues": [], "all_accounted": True}
        return LLMResult({**base, **self.data}, 12.0, "fake")


@pytest.fixture(scope="module")
def tree():
    return DecisionTree.load()


def items(plan):
    return {e.item_id: e for e in plan.checklist.entries}


def test_auto_mode_skips_llm_when_everything_is_accounted(tree):
    client = FakeClient()
    plan = PromptAnalyzer(tree, client, "auto").analyse("anaesthetist, pre-operative check")
    assert client.calls == [] and plan.method == "keywords" and not plan.issues


def test_auto_mode_calls_llm_for_unaccounted_words(tree):
    client = FakeClient({"add_nodes": ["immunosuppressive_therapy"],
                         "item_terms": [{"item_id": "liver_function", "terms_de": ["GOT", "GPT"],
                                         "terms_en": ["ALT"]}]})
    plan = PromptAnalyzer(tree, client, "auto").analyse("dermatologist before starting leflunomide")
    assert len(client.calls) == 1 and "leflunomide" in client.calls[0]
    assert plan.method == "keywords+llm" and plan.llm_ms == 12.0
    assert {h.node_id: h.source for h in plan.nodes}["immunosuppressive_therapy"] == "llm"
    entry = items(plan)["liver_function"]
    assert entry.priority == "critical" and entry.terms["llm"] == ["GOT", "GPT", "ALT"]


def test_llm_sets_missing_role(tree):
    plan = PromptAnalyzer(tree, FakeClient({"role": "pulmonology"}), "auto").analyse(
        "lung doc reviewing inhalers")
    assert {h.node_id: h.source for h in plan.nodes}["pulmonology"] == "llm"


def test_llm_cannot_replace_role_named_in_prompt(tree):
    plan = PromptAnalyzer(tree, FakeClient({"role": "cardiology"}), "always").analyse(
        "anaesthetist, pre-operative check")
    roles = {h.node_id for h in plan.nodes if h.kind == "role" and h.source != "ancestor"}
    assert roles == {"anaesthesiology"}
    assert any("kept anaesthesiology" in i for i in plan.issues)


def test_llm_may_refine_role_to_a_descendant(tree):
    plan = PromptAnalyzer(tree, FakeClient({"role": "breast_surgery"}), "always").analyse(
        "surgeon, wound check")
    assert "breast_surgery" in {h.node_id for h in plan.nodes}


def test_unknown_ids_are_dropped_and_reported(tree):
    plan = PromptAnalyzer(tree, FakeClient({"add_nodes": ["made_up_node"],
                                            "add_items": [{"item_id": "made_up_item",
                                                           "priority": "high", "reason": ""}]}),
                          "always").analyse("anaesthetist, pre-op")
    assert any("made_up_item" in i and "made_up_node" in i for i in plan.issues)


def test_llm_removes_wrongly_matched_context(tree):
    plan = PromptAnalyzer(tree, FakeClient({"remove_nodes": ["surgery_planned"]}), "always").analyse(
        "nurse, patient back on the ward after the operation")
    assert "surgery_planned" not in {h.node_id for h in plan.nodes}
    assert any("Removed surgery_planned" in i for i in plan.issues)


def test_custom_question_needs_search_terms(tree):
    data = {"custom_questions": [
        {"question": "Thyroid function?", "search_terms_de": ["TSH", "Schilddrüse"],
         "search_terms_en": ["TSH"], "priority": "high"},
        {"question": "No terms", "search_terms_de": [], "search_terms_en": [], "priority": "high"}]}
    plan = PromptAnalyzer(tree, FakeClient(data), "always").analyse("endocrinologist, thyroid nodule")
    assert [c.question for c in plan.custom_questions] == ["Thyroid function?"]
    assert any("without search terms" in i for i in plan.issues)


def test_terms_are_cleaned(tree):
    data = {"item_terms": [{"item_id": "allergies", "terms_de": ["KM", "km", " ", "x" * 80],
                            "terms_en": []}]}
    plan = PromptAnalyzer(tree, FakeClient(data), "always").analyse("radiologist")
    assert items(plan)["allergies"].terms["llm"] == ["KM"]


def test_llm_failure_falls_back_to_keywords(tree):
    plan = PromptAnalyzer(tree, FakeClient(error="timeout"), "auto").analyse(
        "dermatologist before starting leflunomide")
    assert plan.method == "keywords"
    assert any("LLM step failed" in i for i in plan.issues)
    assert any("Not interpreted" in i and "leflunomide" in i for i in plan.issues)
    assert plan.checklist.entries


def test_handoff_check_flags_missing_role(tree):
    plan = PromptAnalyzer(tree, None, "off").analyse("quick look please")
    assert any("No role recognised" in i for i in plan.issues)


def test_fallback_client_uses_next_model_on_failure(tree):
    cloud = FakeClient(error="no key")
    local = FakeClient({"role": "pulmonology"}, context_tokens=2048)
    plan = PromptAnalyzer(tree, FallbackClient(cloud, local), "auto").analyse("lung doc reviewing inhalers")
    assert len(cloud.calls) == 1 and len(local.calls) == 1
    assert "pulmonology" in {h.node_id for h in plan.nodes}


def test_small_context_gets_compact_catalogue(tree):
    big, small = FakeClient(), FakeClient(context_tokens=2048)
    PromptAnalyzer(tree, big, "always").analyse("anaesthetist")
    PromptAnalyzer(tree, small, "always").analyse("anaesthetist")
    assert "anaesthesiology: Anaesthesiology" in big.calls[0]
    assert "ROLE IDS: physician, perioperative" in small.calls[0]
    assert len(small.calls[0]) < len(big.calls[0]) / 2


def test_as_of_is_validated(tree):
    good = PromptAnalyzer(tree, FakeClient({"as_of": "2016-04-15"}), "always").analyse("GP review")
    bad = PromptAnalyzer(tree, FakeClient({"as_of": "spring"}), "always").analyse("GP review")
    assert str(good.as_of) == "2016-04-15" and bad.as_of is None


def test_cache_answers_repeated_prompt_without_llm(tmp_path, tree):
    cache = tmp_path / "cache.json"
    client = FakeClient({"add_nodes": ["immunosuppressive_therapy"]})
    first = _PromptAnalyzer(tree, client, "auto", cache_file=cache).analyse("dermatologist, leflunomide")
    second_client = FakeClient(error="must not be called")
    second = _PromptAnalyzer(tree, second_client, "auto", cache_file=cache).analyse("Dermatologist,  leflunomide!")
    assert first.llm_ms == 12.0 and second.llm_ms == 0.0 and second_client.calls == []
    assert "immunosuppressive_therapy" in {h.node_id for h in second.nodes}


def test_failed_answers_are_not_cached(tmp_path, tree):
    cache = tmp_path / "cache.json"
    _PromptAnalyzer(tree, FakeClient(error="down"), "auto", cache_file=cache).analyse("dermatologist, leflunomide")
    assert not cache.exists()


def test_refinement_returns_keyword_plan_first(tree):
    client = FakeClient({"add_nodes": ["immunosuppressive_therapy"]})
    fast, future = PromptAnalyzer(tree, client, "auto").analyse_with_refinement("dermatologist, leflunomide")
    assert fast.method == "keywords" and future is not None
    refined = future.result(timeout=5)
    assert refined.method == "keywords+llm"


def test_refinement_skipped_when_graph_covers_prompt(tree):
    fast, future = PromptAnalyzer(tree, FakeClient(), "auto").analyse_with_refinement(
        "anaesthetist, pre-operative check")
    assert future is None and fast.method == "keywords"


def test_default_analyzer_makes_no_model_calls(tree, monkeypatch):
    from app.prompt_analysis import make_default_analyzer
    monkeypatch.delenv("PROMPT_LLM", raising=False)
    monkeypatch.delenv("PROMPT_EMBEDDINGS", raising=False)
    analyzer = make_default_analyzer(tree)
    assert analyzer.client is None and analyzer.linker is None and analyzer.llm_mode == "off"
    plan = analyzer.analyse("Dermatologist before starting leflunomide")
    assert plan.method == "keywords" and plan.checklist.entries
