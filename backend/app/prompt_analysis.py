"""Block 5b: prompt analysis.

prompt -> QueryPlan, in three steps:

1. Keyword path (tree.py): match, activate, score. Reports which prompt words it could
   not account for.
2. LLM step, when something is unaccounted for (mode "auto") or always (mode "always").
   The model sees the whole prompt, the keyword interpretation and the graph catalogue,
   and returns only catalogue IDs plus search terms:
     - role / add_nodes / remove_nodes : corrections to the interpretation
     - add_items                       : checklist items the graph missed
     - item_terms                      : German and English search terms per item
     - custom_questions                : needs no item covers, with search terms
   Everything it returns is validated; unknown IDs are dropped and reported. The graph
   then re-scores with the corrected nodes, so rules and suppressions still apply.
3. Hand-off check: deterministic sanity checks before the plan goes to retrieval.
   Problems are listed in QueryPlan.issues; nothing is silently dropped.

If the LLM fails or times out, the keyword result is used and the failure is an issue.

Speed: the graph answers in milliseconds; the LLM adds about 1.5 s. So the LLM runs only
when the graph left words unaccounted for, its answers are cached per prompt, and
`analyse_with_refinement` returns the keyword plan at once while the LLM refines it in the
background (retrieval can start on the keyword plan in the meantime).
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Literal

from . import vault
from .contracts import Coverage, CustomQuestion, QueryPlan
from .llm_client import LLMClient, LLMError
from .tree import ASKED_SCORE, PRIORITY_WEIGHT, DecisionTree, normalize

CACHE_FILE = Path(__file__).resolve().parent.parent / ".cache" / "prompt_llm_cache.json"
_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="prompt-llm")

LLMMode = Literal["off", "auto", "always"]
LLM_NODE_ACTIVATION = 0.9
LLM_CRITICAL_SCORE = 0.85
COMPACT_BELOW_TOKENS = 8000  # local models with small context windows get IDs only
MAX_LIST = {"add_nodes": 6, "remove_nodes": 4, "add_items": 8, "custom_questions": 4,
            "item_terms": 10, "issues": 5}
MAX_TERMS = 8
MAX_TERM_LEN = 40

SYSTEM_PROMPT = """\
You help a clinical documentation tool understand a clinician's request. The clinician
types their role and task in English or German (for example "anaesthetist, pre-operative
check before breast surgery"). The tool then searches German clinical documents for the
facts that task needs.

A keyword matcher has already interpreted the request. Your job:
1. Check the interpretation. Correct the role if it is missing or wrong. Add nodes from the
   catalogue that the request implies. Remove nodes that were matched by mistake (for
   example "operation" in "after the operation" is not a planned operation).
2. Account for every unaccounted word: map it to catalogue nodes or items, or turn it into a
   custom question if no item covers it.
3. For each item that matters most for this request, give German search terms as they
   appear in German clinical letters (include abbreviations and brand or generic drug
   names), plus English terms.

Rules:
- Use only IDs from the catalogue. Never invent IDs.
- Never state patient facts. You do not see the patient record.
- Keep lists short and specific. Empty lists are fine.
- role: one role ID only if the request names that profession or specialty. If it names a
  profession that is not in the catalogue, return "" and say so in issues. Never guess a
  related specialty instead.
- as_of: a date in YYYY-MM-DD only if the request gives the reference date, else "".
- all_accounted: true if every part of the request is now covered.
"""

_STR_LIST = {"type": "array", "items": {"type": "string"}}
_PRIORITY = {"type": "string", "enum": ["critical", "high", "normal"]}
RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["role", "add_nodes", "remove_nodes", "add_items", "item_terms",
                 "custom_questions", "as_of", "issues", "all_accounted"],
    "properties": {
        "role": {"type": "string"},
        "add_nodes": _STR_LIST,
        "remove_nodes": _STR_LIST,
        "add_items": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["item_id", "priority", "reason"],
            "properties": {"item_id": {"type": "string"}, "priority": _PRIORITY,
                           "reason": {"type": "string"}}}},
        "item_terms": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["item_id", "terms_de", "terms_en"],
            "properties": {"item_id": {"type": "string"}, "terms_de": _STR_LIST,
                           "terms_en": _STR_LIST}}},
        "custom_questions": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["question", "search_terms_de", "search_terms_en", "priority"],
            "properties": {"question": {"type": "string"}, "search_terms_de": _STR_LIST,
                           "search_terms_en": _STR_LIST, "priority": _PRIORITY}}},
        "as_of": {"type": "string"},
        "issues": _STR_LIST,
        "all_accounted": {"type": "boolean"},
    },
}


def _as_list(value) -> list:
    """Small models sometimes return a string or null where a list is expected."""
    if value is None:
        return []
    if isinstance(value, (str, dict)):
        return [value]
    return list(value) if isinstance(value, (list, tuple)) else []


def _clean_terms(terms) -> list[str]:
    out: list[str] = []
    for t in _as_list(terms):
        if isinstance(t, str):
            t = " ".join(t.split())
            if 0 < len(t) <= MAX_TERM_LEN and t.lower() not in {x.lower() for x in out}:
                out.append(t)
    return out[:MAX_TERMS]


def default_settings() -> dict[str, str]:
    """The best measured setup (docs/prompt-analysis-report.html, unseen 'blind 3' prompts):
    graph with the generated vocabulary, no model call while the clinician waits. Gemini and
    the embedding step added no accuracy there but 1.6-2.6 s per prompt.

      PROMPT_LLM         off (default) | auto (Gemini when words are unknown) | always
      PROMPT_EMBEDDINGS  off (default) | jina | gemini (embedding step for unknown words)
    """
    return {"llm": os.environ.get("PROMPT_LLM", "off"),
            "embeddings": os.environ.get("PROMPT_EMBEDDINGS", "off")}


def make_default_analyzer(tree: DecisionTree | None = None, client: LLMClient | None = None
                          ) -> "PromptAnalyzer":
    """The analyser every caller should use unless it is running an experiment."""
    from .llm_client import load_env_file, make_client
    from .semantic import make_linker

    load_env_file()
    tree = tree or DecisionTree.load()
    cfg = default_settings()
    linker = make_linker(tree, provider=cfg["embeddings"]) if cfg["embeddings"] != "off" else None
    if cfg["llm"] != "off" and client is None:
        try:
            client = make_client()
        except Exception:
            client = None
    return PromptAnalyzer(tree, client if cfg["llm"] != "off" else None,
                          llm_mode=cfg["llm"] if cfg["llm"] in ("auto", "always") else "off",
                          linker=linker)


class PromptAnalyzer:
    def __init__(self, tree: DecisionTree, client: LLMClient | None = None,
                 llm_mode: LLMMode = "auto", timeout: float = 20.0,
                 cache_file: Path | None = CACHE_FILE, linker=None) -> None:
        """linker: optional semantic.SemanticLinker, the embedding step between the
        keyword graph and the LLM."""
        self.tree = tree
        self.linker = linker
        self.client = client
        self.llm_mode = llm_mode if client is not None else "off"
        self.timeout = timeout
        self._catalogue_full = self._render_catalogue(compact=False)
        self._catalogue_compact = self._render_catalogue(compact=True)
        self._cache_file = cache_file
        self._cache_lock = threading.Lock()
        self._cache: dict[str, dict] = {}
        if cache_file and cache_file.exists():
            try:
                self._cache = json.loads(vault.read_text(cache_file))
            except (OSError, json.JSONDecodeError, vault.VaultError):
                self._cache = {}

    # --- cache: one LLM answer per (normalised prompt, graph version, model) ---------
    def _cache_key(self, prompt: str) -> str:
        version = getattr(self.tree, "source_sha256", "")
        model = getattr(self.client, "model", "")
        return hashlib.sha256(f"{version}|{model}|{normalize(prompt)}".encode()).hexdigest()

    def _cache_put(self, key: str, data: dict) -> None:
        with self._cache_lock:
            self._cache[key] = data
            if self._cache_file:
                try:
                    vault.write_text(self._cache_file, json.dumps(self._cache, ensure_ascii=False))
                except OSError:
                    pass  # the cache is an optimisation, never a failure

    def _log_suggestion(self, unaccounted: list[str], data: dict, llm_nodes: set[int]) -> None:
        """Record which unknown words the LLM mapped to what, for the team to add to
        tree.yaml. Every word added there is one LLM call fewer next time."""
        if not self._cache_file or not unaccounted:
            return
        entry = {
            "words": unaccounted,
            "nodes": sorted(self.tree.nodes[i]["id"] for i in llm_nodes),
            "items": sorted({e.get("item_id") for e in _as_list(data.get("add_items"))
                             if isinstance(e, dict) and e.get("item_id") in self.tree.item_index}),
            "terms": {e["item_id"]: _clean_terms(_as_list(e.get("terms_de")) + _as_list(e.get("terms_en")))
                      for e in _as_list(data.get("item_terms"))
                      if isinstance(e, dict) and e.get("item_id") in self.tree.item_index},
        }
        try:
            with self._cache_lock, open(self._cache_file.parent / "vocab_suggestions.jsonl", "a",
                                        encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def needs_llm(self, plan: QueryPlan) -> bool:
        """True when keywords and embeddings may have left the plan incomplete."""
        if self.llm_mode == "always":
            return True
        if self.llm_mode == "off":
            return False
        named_role = any(h.kind == "role" and h.source in ("prompt", "fuzzy", "semantic") for h in plan.nodes)
        return bool(plan.coverage.unaccounted) or not named_role

    def analyse_with_refinement(self, prompt: str) -> tuple[QueryPlan, Future | None]:
        """Graph (+ embedding) plan now; LLM-refined plan later, or None if not needed.

        The caller can start retrieval on the first plan and swap in the refined one."""
        fast = self.analyse(prompt, use_llm=False)
        if not self.needs_llm(fast):
            return fast, None
        return fast, _EXECUTOR.submit(self.analyse, prompt)

    def _render_catalogue(self, compact: bool) -> str:
        """Full: one 'id: label' line per entry. Compact (small local models): IDs only."""
        cat = self.tree.catalogue()
        parts = []
        for kind in ("role", "task", "context", "concept", "item"):
            if compact:
                parts.append(f"{kind.upper()} IDS: " + ", ".join(i for i, _ in cat[kind]))
            else:
                parts.append(f"{kind.upper()} IDS:\n" + "\n".join(f"  {i}: {label}" for i, label in cat[kind]))
        return "\n".join(parts)

    # ------------------------------------------------------------------------
    def analyse(self, prompt: str, use_llm: bool = True) -> QueryPlan:
        tree = self.tree
        m = tree.match(prompt)
        seeds = dict(m.activation)
        asked = {i: ASKED_SCORE for i in m.asked_items}
        act, how = tree.activate(seeds)
        checklist = tree.score(act, asked)
        issues: list[str] = []
        custom: list[CustomQuestion] = []
        as_of: date | None = None
        llm_nodes: set[int] = set()
        llm_terms: dict[int, list[str]] = {}
        llm_ms = None
        method = "keywords"
        reasons: dict[int, str] = {}
        semantic_links: list[str] = []
        semantic_ms = None

        if self.linker is not None and m.coverage.unaccounted:
            t = time.perf_counter()
            try:
                links = self.linker.link(m.coverage.unaccounted)
                linked_words: set[str] = set()
                for link in links:
                    if link.target_kind == "node":
                        a = min(link.similarity, 0.85)
                        if a > seeds.get(link.target, 0):
                            seeds[link.target] = a
                            m.source[link.target] = "semantic"
                        m.words.setdefault(link.target, []).append(link.phrase)
                    else:
                        asked[link.target] = max(asked.get(link.target, 0), 0.7)
                        reasons[link.target] = "semantic"
                    linked_words |= set(link.phrase.split())
                    semantic_links.append(f"{link.phrase} -> {link.alias} ({link.similarity:.2f})")
                if links:
                    remaining = [w for w in m.coverage.unaccounted if w not in linked_words]
                    m.coverage = Coverage(
                        content_words=m.coverage.content_words,
                        accounted_words=m.coverage.accounted_words + len(m.coverage.unaccounted) - len(remaining),
                        unaccounted=remaining)
                    act, how = tree.activate(seeds)
                    checklist = tree.score(act, asked, reasons)
            except Exception as e:  # embeddings are an optimisation, never a failure
                issues.append(f"Embedding step failed ({type(e).__name__}: {e}).")
            semantic_ms = (time.perf_counter() - t) * 1000

        prompt_role = any(tree.nodes[i]["kind"] == "role" and m.source.get(i) in ("prompt", "semantic")
                          for i in seeds)
        needs_llm = bool(m.coverage.unaccounted) or not prompt_role
        if use_llm and (self.llm_mode == "always" or (self.llm_mode == "auto" and needs_llm)):
            try:
                key = self._cache_key(prompt)
                data = self._cache.get(key)
                if data is not None:
                    llm_ms = 0.0
                else:
                    result = self.client.complete_json(
                        SYSTEM_PROMPT,
                        lambda ctx: self._user_message(prompt, act, how, m, checklist,
                                                       compact=ctx < COMPACT_BELOW_TOKENS),
                        RESPONSE_SCHEMA, self.timeout)
                    llm_ms = result.ms
                    data = result.data
                method = "keywords+llm"
                seeds, asked, custom, as_of, llm_nodes, llm_terms = self._merge(
                    data, seeds, asked, m, issues)
                if llm_ms:  # cache only answers that passed validation
                    self._cache_put(key, data)
                    self._log_suggestion(m.coverage.unaccounted, data, llm_nodes)
                act, how = tree.activate(seeds)
                checklist = tree.score(act, asked, {i: reasons.get(i, "llm") for i in asked
                                                    if i not in m.asked_items})
            except LLMError as e:
                issues.append(f"LLM step failed ({e}); keyword result used.")
            except Exception as e:  # never let the LLM step break a request
                issues.append(f"LLM step failed ({type(e).__name__}: {e}); keyword result used.")

        for entry in checklist.entries:
            terms = llm_terms.get(tree.item_index[entry.item_id])
            if terms:
                entry.terms["llm"] = terms
        plan = QueryPlan(prompt=prompt, nodes=tree.hits(act, how, m, llm_nodes),
                         checklist=checklist, custom_questions=custom, as_of=as_of,
                         coverage=m.coverage, method=method, llm_ms=llm_ms, issues=issues,
                         semantic_links=semantic_links, semantic_ms=semantic_ms)
        self._handoff_check(plan)
        return plan

    # ------------------------------------------------------------------------
    def _user_message(self, prompt, act, how, m, checklist, compact: bool = False) -> str:
        order = sorted(act, key=lambda i: -act[i])
        if compact:
            payload = {
                "request": prompt,
                "detected_nodes": [self.tree.nodes[i]["id"] for i in order],
                "checklist": [e.item_id for e in checklist.entries],
                "unaccounted_words": m.coverage.unaccounted,
            }
            return (json.dumps(payload, ensure_ascii=False)
                    + "\nKeep the answer short: at most 3 item_terms with 4 terms each, "
                      "at most 2 custom_questions, at most 4 add_items."
                    + "\nCATALOGUE\n" + self._catalogue_compact)
        payload = {
            "request": prompt,
            "detected_nodes": [{"id": self.tree.nodes[i]["id"], "kind": self.tree.nodes[i]["kind"],
                                "how": m.source.get(i) or how.get(i, "implied")} for i in order],
            "checklist": [f"{e.item_id} ({e.priority})" for e in checklist.entries],
            "unaccounted_words": m.coverage.unaccounted,
        }
        return (json.dumps(payload, ensure_ascii=False, indent=1)
                + "\n\nCATALOGUE\n" + self._catalogue_full)

    def _merge(self, data: dict, seeds: dict, asked: dict, m, issues: list[str]):
        if not isinstance(data, dict):
            raise LLMError("LLM answer is not a JSON object")
        tree = self.tree
        seeds = dict(seeds)
        asked = dict(asked)
        llm_nodes: set[int] = set()
        dropped: list[str] = []

        def node(nid):
            i = tree.node_index.get(nid) if isinstance(nid, str) else None
            if i is None:
                dropped.append(str(nid))
            return i

        current_role = next((i for i in seeds if tree.nodes[i]["kind"] == "role"
                             and m.source.get(i) == "prompt"), None)
        role = data.get("role") or ""
        role = role if isinstance(role, str) else ""
        if role:
            i = node(role)
            if i is not None and tree.nodes[i]["kind"] != "role":
                dropped.append(role)
            elif i is not None and i not in seeds:
                ancestors = set()
                p = tree.nodes[i]["parent"]
                while p is not None:
                    ancestors.add(p)
                    p = tree.nodes[p]["parent"]
                if current_role is None or current_role in ancestors:
                    seeds[i] = 1.0
                    llm_nodes.add(i)
                else:
                    issues.append(f"LLM suggested role {role}; kept "
                                  f"{tree.nodes[current_role]['id']} from the prompt.")

        for nid in _as_list(data.get("add_nodes"))[:MAX_LIST["add_nodes"]]:
            i = node(nid)
            if i is None or tree.nodes[i]["kind"] == "role":
                continue
            if seeds.get(i, 0) < LLM_NODE_ACTIVATION:
                seeds[i] = LLM_NODE_ACTIVATION
                llm_nodes.add(i)

        for nid in _as_list(data.get("remove_nodes"))[:MAX_LIST["remove_nodes"]]:
            i = node(nid)
            if i is None or i not in seeds:
                continue
            if tree.nodes[i]["kind"] == "role" and m.source.get(i) == "prompt":
                issues.append(f"LLM asked to remove role {nid}; kept because the prompt names it.")
                continue
            del seeds[i]
            issues.append(f"Removed {nid} on LLM review.")

        for entry in _as_list(data.get("add_items"))[:MAX_LIST["add_items"]]:
            iid = entry.get("item_id") if isinstance(entry, dict) else None
            i = tree.item_index.get(iid)
            if i is None:
                dropped.append(str(iid))
                continue
            p = entry.get("priority", "high")
            score = LLM_CRITICAL_SCORE if p == "critical" else PRIORITY_WEIGHT.get(p, 0.7)
            if score > asked.get(i, 0):
                asked[i] = score

        llm_terms: dict[int, list[str]] = {}
        for entry in _as_list(data.get("item_terms"))[:MAX_LIST["item_terms"]]:
            iid = entry.get("item_id") if isinstance(entry, dict) else None
            i = tree.item_index.get(iid)
            if i is None:
                dropped.append(str(iid))
                continue
            terms = _clean_terms(_as_list(entry.get("terms_de")) + _as_list(entry.get("terms_en")))
            if terms:
                llm_terms[i] = _clean_terms(llm_terms.get(i, []) + terms)

        custom: list[CustomQuestion] = []
        for q in _as_list(data.get("custom_questions"))[:MAX_LIST["custom_questions"]]:
            if not isinstance(q, dict) or not str(q.get("question", "")).strip():
                continue
            de, en = _clean_terms(q.get("search_terms_de")), _clean_terms(q.get("search_terms_en"))
            if not de and not en:
                issues.append(f"Dropped custom question without search terms: {q.get('question')}")
                continue
            prio = q.get("priority") if q.get("priority") in PRIORITY_WEIGHT else "high"
            custom.append(CustomQuestion(question=str(q["question"]).strip()[:200],
                                         search_terms_de=de, search_terms_en=en, priority=prio))

        as_of = None
        if data.get("as_of"):
            try:
                as_of = date.fromisoformat(str(data["as_of"]))
            except ValueError:
                dropped.append(f"as_of={data['as_of']}")

        for text in _as_list(data.get("issues"))[:MAX_LIST["issues"]]:
            if isinstance(text, str) and text.strip():
                issues.append("LLM: " + text.strip()[:200])
        if dropped:
            issues.append("Ignored unknown IDs from the LLM: " + ", ".join(sorted(set(dropped))))
        if data.get("all_accounted") is False:
            issues.append("LLM reports that parts of the request are still not covered.")
        return seeds, asked, custom, as_of, llm_nodes, llm_terms

    # ------------------------------------------------------------------------
    def _handoff_check(self, plan: QueryPlan) -> None:
        """Deterministic checks before the plan goes to retrieval (blocks 6 and 7)."""
        roles = [h for h in plan.nodes if h.kind == "role"]
        if all(h.source in ("ancestor", "default") for h in roles):
            plan.issues.append("No role recognised; using the generic physician checklist.")
        if not plan.checklist.entries:
            plan.issues.append("Checklist is empty.")
        for e in plan.checklist.entries:
            if e.priority == "critical" and not any(e.terms.values()):
                plan.issues.append(f"Critical item {e.item_id} has no search terms.")
        if plan.method == "keywords" and plan.coverage.unaccounted:
            plan.issues.append("Not interpreted: " + ", ".join(plan.coverage.unaccounted))
