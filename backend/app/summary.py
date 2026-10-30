"""Block 8: final step. Checks the remarker's ranking and writes the cited summary.

Inputs : QueryPlan (block 5), RemarkerResult (blocks 6/7), patient.json, UI language.
Output : FinalResult (final_contracts.py) for the UI.

Flow (target 2-3 s, hard budget SUMMARY_BUDGET_S, default 3 s):
1. Templates (code): every item gets a claim built from its passages, in EN and DE.
   High-risk facts (allergies, drugs and doses, measurements, sides, "not documented")
   are only ever shown in this quoted form.
2. Two LLM calls in parallel, on short IDs (P1.. passages, T1.. templates, C1.. candidates):
   A  ranking check: which passages do not answer their item, and the item order.
   B  summary: pick templates, write a few connecting sentences that cite passages,
      judge contradiction candidates.
   Neither call can add evidence; they only choose among what the remarker found.
3. Code checks: drops apply; every LLM sentence must cite kept passages, and its numbers,
   drug names, negations, sides and done-vs-planned wording must match those passages.
   A sentence that fails is replaced by its template. Conflicts need two passages.
4. Fallback: no key, an error or the budget running out -> template-only result.
Results are cached by input (memory and .cache/summary).

CLI
  python -m app.summary "anaesthetist, pre-operative check before breast surgery" --patient <dir>
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from collections import OrderedDict
from datetime import date
from pathlib import Path

from .contracts import ContradictionCandidate, Flag, ItemEvidence, QueryPlan, RecordRelevance, RemarkerResult
from .final_contracts import (Claim, Conflict, DroppedFlag, FinalResult, ItemResult, Lang,
                              PatientStrip)
from .llm_client import (AnthropicClient, GeminiClient, LLMClient, LLMError, gemini_key,
                         load_env_file)
from .tree import PRIORITY_WEIGHT
from . import outbound, vault

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "summary"
DEFAULT_BUDGET_S = 3.0
CACHE_VERSION = 8           # bump when the finalizer's logic changes; old cache entries then miss
DEFAULT_CHECK_MODEL = "gemini-flash-lite-latest"
DEFAULT_SUMMARY_MODEL = "gemini-flash-lite-latest"
FLAGS_PER_ITEM = 3          # passages per critical item sent to the LLM
FLAGS_PER_ITEM_OTHER = 2    # per high / normal item (smaller prompt, faster answer)
PASSAGE_CHARS = 200
LIST_PASSAGES = 6           # template quotes for a "current" list item: every drug, up to this many
TEMPLATE_PASSAGES_TOP = 3   # template quotes for other critical / high items
TEMPLATE_PASSAGES = 2       # and for normal items
DUPLICATE_OVERLAP = 0.75    # share of the shorter passage's word stems and numbers found in a kept one
MAX_SUMMARY = 6
MAX_SUMMARY_WITH_CRITICAL = 8
KEEP_GUARD_RIDX = 0.9       # the check may not empty an item whose best passage is this strong
PRIORITY_ORDER = {"critical": 0, "high": 1, "normal": 2}
DROP_REASONS = {"irrelevant", "wrong_polarity", "superseded", "duplicate"}
CLAIM_KINDS = {"finding", "absent", "not_documented", "incomplete", "uncertain", "conflict"}

# ---------------------------------------------------------------------------
# Text checks
# ---------------------------------------------------------------------------
_FOLD = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower().translate(_FOLD))
    return "".join(c for c in text if not unicodedata.combining(c))


_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def _numbers(text: str) -> set[str]:
    out = set()
    for n in _NUM.findall(text):
        n = n.replace(",", ".")
        out.add(n.rstrip("0").rstrip(".") if "." in n else n.lstrip("0") or "0")
    return out


# Generic name -> other names (brands, German spellings, abbreviations). General drug
# knowledge, not patient data. A drug named in a claim must appear in its cited passages.
DRUG_GROUPS = {
    "acetylsalicylic acid": ["aspirin", "ass", "thrombo ass", "acetylsalicylsaeure"],
    "clopidogrel": ["plavix"], "apixaban": ["eliquis"], "rivaroxaban": ["xarelto"],
    "dabigatran": ["pradaxa"], "edoxaban": ["lixiana"], "phenprocoumon": ["marcumar"],
    "warfarin": ["coumadin"], "heparin": [], "enoxaparin": ["lovenox", "clexane"],
    "metformin": ["glucophage"], "pioglitazone": ["actos", "pioglitazon"],
    "exenatide": ["byetta", "exenatid"], "insulin": [], "sitagliptin": ["januvia"],
    "empagliflozin": ["jardiance"], "candesartan": ["blopress", "atacand"],
    "ramipril": ["tritace"], "lisinopril": [], "enalapril": [], "bisoprolol": ["concor"],
    "metoprolol": ["beloc"], "amlodipine": ["norvasc", "amlodipin"],
    "hydrochlorothiazide": ["hct"], "furosemide": ["lasix", "furosemid"],
    "simvastatin": ["zocor"], "atorvastatin": ["sortis", "lipitor"],
    "colecalciferol": ["vitamin d3", "oleovit"], "alendronic acid": ["alendronate", "alendronat", "fosamax"],
    "denosumab": ["prolia"], "pantoprazole": ["pantoloc", "pantoprazol"], "omeprazole": [],
    "levothyroxine": ["euthyrox", "levothyroxin"], "prednisolone": ["prednisolon"],
    "methotrexate": ["methotrexat"], "lithium": [], "nitroglycerin": ["nitro", "glyceryl trinitrate"],
    "ibuprofen": [], "diclofenac": ["voltaren"], "paracetamol": ["acetaminophen"],
}
_DRUG_NAME_TO_GROUP = {}
for _g, _names in DRUG_GROUPS.items():
    for _n in [_g] + _names:
        _DRUG_NAME_TO_GROUP[_fold(_n)] = _g
_DRUG_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, _DRUG_NAME_TO_GROUP), key=len, reverse=True)) + r")\b")

_NEG = re.compile(r"\b(no|not|none|without|denies|negative|absent|never|kein\w*|nicht|ohne|negativ\w*)\b")
_SIDE = {
    "left": re.compile(r"\b(left|links|linke\w*|li|sinist\w*)\b"),
    "right": re.compile(r"\b(right|rechts|rechte\w*|re|dext\w*)\b"),
    "both": re.compile(r"\b(bilateral|both sides|beidseits|bds)\b"),
}
_DONE = re.compile(r"\b(underwent|performed|was done|took place|carried out|completed|was carried|"
                   r"durchgefuehrt|erfolgte|stattgefunden)\b")


def _sides_in(text: str) -> set[str]:
    t = _fold(text)
    return {s for s, rx in _SIDE.items() if rx.search(t)}


def check_claim(text: str, cited: list[Flag], kind: str) -> str | None:
    """Return why an LLM claim is unsupported by its cited passages, or None if it passes."""
    if not cited:
        return "no citation"
    flag_text = " ".join(f.text for f in cited)
    folded_claim, folded_flags = _fold(text), _fold(flag_text)

    allowed = _numbers(flag_text) | {f.doc_id for f in cited}
    for f in cited:
        if f.doc_date:
            allowed |= {str(f.doc_date.year), str(f.doc_date.month), str(f.doc_date.day)}
    missing = _numbers(text) - allowed
    if missing:
        return f"numbers not in sources: {sorted(missing)}"

    for name in _DRUG_RE.findall(folded_claim):
        group = _DRUG_NAME_TO_GROUP[name]
        names = [group] + DRUG_GROUPS[group]
        if not any(re.search(r"\b" + re.escape(_fold(n)) + r"\b", folded_flags) for n in names):
            return f"drug not in sources: {name}"

    claim_neg = bool(_NEG.search(folded_claim))
    flags_neg = any(f.polarity == "negated" for f in cited) or bool(_NEG.search(folded_flags))
    if claim_neg and not flags_neg and kind not in ("not_documented", "incomplete"):
        return "negation not in sources"
    if not claim_neg and kind == "finding" and cited and all(f.polarity == "negated" for f in cited):
        return "states as present what the sources negate"

    claim_sides = _sides_in(text)
    if claim_sides:
        flag_sides = set().union(*[set(f.sides) or _sides_in(f.text) for f in cited])
        if not claim_sides <= flag_sides:
            return f"side not in sources: {sorted(claim_sides - flag_sides)}"

    if _DONE.search(folded_claim) and all(f.polarity == "planned" for f in cited):
        return "describes as done what the sources only plan"
    return None


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
_TPL = {
    "en": {"not_documented": "{label}: not documented.",
           "processing_incomplete": "{label}: could not be fully checked.",
           "documented_absent": "{label}: documented as absent – {quotes}",
           "uncertain": "{label}: unclear – {quotes}",
           "found": "{label}: {quotes}",
           "conflict": "Conflicting documentation ({diff}): {quotes}",
           "derived": "{label}: {value} (calculated from the linked passages).",
           "conflict_expl": "The same finding is documented with different {what}: {diff}."},
    "de": {"not_documented": "{label}: nicht dokumentiert.",
           "processing_incomplete": "{label}: konnte nicht vollständig geprüft werden.",
           "documented_absent": "{label}: als nicht vorhanden dokumentiert – {quotes}",
           "uncertain": "{label}: unklar – {quotes}",
           "found": "{label}: {quotes}",
           "conflict": "Widersprüchliche Dokumentation ({diff}): {quotes}",
           "derived": "{label}: {value} (aus den verlinkten Passagen berechnet).",
           "conflict_expl": "Derselbe Befund ist mit unterschiedlicher {what} dokumentiert: {diff}."},
}
_KIND_OF_STATUS = {"found": "finding", "documented_absent": "absent", "uncertain": "uncertain",
                   "not_documented": "not_documented", "processing_incomplete": "incomplete"}


def _source(f: Flag, labels: dict | None, lang: Lang) -> str:
    """Short document name for a source link ("Arztbrief 04/2016"); document ID and date as fallback."""
    name = (labels or {}).get(f.doc_id, {}).get(lang)
    return name or f"{f.doc_id}, {f.doc_date.isoformat() if f.doc_date else '?'}"


def _quote(f: Flag, chars: int = 160, labels: dict | None = None, lang: Lang = "en") -> str:
    """The exact passage, for conflicts: both wordings must be read side by side."""
    text = " ".join(f.text.split())
    if len(text) > chars:
        text = text[:chars].rsplit(" ", 1)[0] + " …"
    return f"«{text}» ({_source(f, labels, lang)})"


def _key(f: Flag, labels: dict | None = None, lang: Lang = "en") -> str:
    """The keyword that answers the item, with its source: quick to read, no click needed."""
    text = f.keyword or _short(f.text, 80)
    return f"{text} ({_source(f, labels, lang)})"


def normalize_key(text: str) -> str:
    return " ".join(text.lower().split())


_TOKEN = re.compile(r"\d+(?:[.,]\d+)?[^\W\d_]*%?|[^\W\d_]+")


def _gist(text: str) -> set[str]:
    """Word stems (first 5 letters) and values ("6,4", "30mg", "70%"): enough to spot the same
    statement twice. Single digits are left out: dosing schedules (1 0 1 0) say nothing about which drug."""
    out = set()
    for w in _TOKEN.findall(text.lower()):
        if w[0].isdigit():
            if len(w) >= 2:
                out.add(w)
        elif len(w) >= 3:
            out.add(w[:5])
    return out


def _repeats(f: Flag, kept: list[Flag]) -> bool:
    for k in kept:  # the screen shows keywords: the same keyword twice is a repeat
        if f.keyword and k.keyword and normalize_key(f.keyword) == normalize_key(k.keyword):
            return True
    g = _gist(f.text)
    for k in kept:
        h = _gist(k.text)
        if g and h and len(g & h) / min(len(g), len(h)) >= DUPLICATE_OVERLAP:
            return True
    return False


def _template_flags(item: ItemResult, time_rule: str = "history") -> list[Flag]:
    """Passages quoted in an item's template line.

    current (drug lists): every current, distinct passage, so no drug of the list goes missing.
    latest / history: verified facts first, also from older documents (a pathology report holds the
    receptor percentages the later discharge letter only summarises); the date tag shows the age.
    """
    if item.status == "documented_absent":
        return [f for f in item.flags if f.polarity == "negated"][:1]
    positive = [f for f in item.flags if f.polarity != "negated"] or item.flags
    if item.status != "found":
        return sorted(positive, key=lambda f: -f.ridx)[:1]
    if time_rule == "current":
        pool = sorted([f for f in positive if f.current] or positive, key=lambda f: -f.ridx)
        n = LIST_PASSAGES
    else:
        pool = sorted(positive, key=lambda f: (not f.fact_ids, not f.current, -f.ridx))
        n = TEMPLATE_PASSAGES_TOP if item.priority in ("critical", "high") else TEMPLATE_PASSAGES
    kept: list[Flag] = []
    for f in pool:
        if len(kept) >= n:
            break
        if not _repeats(f, kept):
            kept.append(f)
    return kept


def template_claim(item: ItemResult, lang: Lang, cid: str, time_rule: str = "history",
                   labels: dict | None = None) -> Claim:
    t = _TPL[lang]
    label = getattr(item.label, lang)
    flags = [] if item.status in ("not_documented", "processing_incomplete") else _template_flags(item, time_rule)
    text = t[item.status].format(label=label, quotes="; ".join(_key(f, labels, lang) for f in flags))
    return Claim(claim_id=cid, item_id=item.item_id, text=text, lang=lang,
                 cites=[f.segment_id for f in flags], kind=_KIND_OF_STATUS[item.status],
                 rendered_by="template")


# ---------------------------------------------------------------------------
# LLM prompts
# ---------------------------------------------------------------------------
CHECK_SYSTEM = """\
You review search results for a clinical documentation tool. A clinician typed a role and
task. For each checklist item, a search marked passages from German clinical documents.

Decide for each passage whether it actually answers its item's question for this request.
List only the passages to drop, each with one reason:
- irrelevant: shares a word with the question but does not answer it
- wrong_polarity: it says the finding is absent or only suspected, but the item needs it present
- superseded: an older value, and a newer passage of the same item gives the current value
  (only for items marked time "current" or "latest")
- duplicate: repeats information another kept passage of the same item already gives
When unsure, keep the passage. Then list the item IDs in order of importance for this
clinician's task, most important first (at most 10).
"""

SUMMARY_SYSTEM = """\
You write the summary panel of a clinical documentation tool for a clinician. Use only the
passages and templates given. Never add advice, interpretation or any fact that is not
written in the cited passages.

Return 3 to 6 entries, most important first for this role and task. Each entry is either:
- a template: set "template" to its ID (T…), leave the other fields empty; or
- your own sentence: "text" (at most 30 words), "cites" (the P… IDs it rests on),
  "item_id" and "kind" (finding, absent or uncertain).
Use templates for allergies, drugs and doses, measurements, sides and anything not
documented. Write your own sentence only to connect facts across passages, for example an
earlier event and the cause the documents give for it. Do not mention document IDs.

For each contradiction candidate (C…), decide if its passages cannot both be true ("real")
or differ only by time, measurement noise or because they describe different things.
Explain in one short sentence.

Write all text in {language}.
"""

_STR_LIST = {"type": "array", "items": {"type": "string"}}
CHECK_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["drops", "order"],
    "properties": {
        "drops": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["item_id", "passage", "reason"],
            "properties": {"item_id": {"type": "string"}, "passage": {"type": "string"},
                           "reason": {"type": "string", "enum": sorted(DROP_REASONS)}}}},
        "order": _STR_LIST,
    },
}
SUMMARY_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["summary", "conflicts"],
    "properties": {
        "summary": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["template", "text", "cites", "item_id", "kind"],
            "properties": {"template": {"type": "string"}, "text": {"type": "string"},
                           "cites": _STR_LIST, "item_id": {"type": "string"},
                           "kind": {"type": "string", "enum": ["finding", "absent", "uncertain", ""]}}}},
        "conflicts": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["candidate", "real", "explanation"],
            "properties": {"candidate": {"type": "string"}, "real": {"type": "boolean"},
                           "explanation": {"type": "string"}}}},
    },
}


DERIVED_LABELS = {
    "body_weight_change": {"en": "Weight change, earliest to latest documented weight",
                           "de": "Gewichtsveränderung, frühestes bis spätestes dokumentiertes Gewicht"},
    "body_mass_index": {"en": "BMI from the documented height and weight",
                        "de": "BMI aus dokumentierter Größe und Gewicht"},
}


def _short(text: str, limit: int = 120) -> str:
    text = " ".join(text.split())
    cut = text.find(". ")
    text = text[:cut] if 0 < cut < limit else text
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " …"


def _select_derived(derived, doc_dates):
    """Changes over time first, then one value per concept: the one from the newest document."""
    def newest(d):
        return max((doc_dates.get(x) for x in d.doc_ids if doc_dates.get(x)), default=None)
    changes = [d for d in derived if d.concept.endswith("_change")]
    latest = {}
    for d in derived:
        if d.concept.endswith("_change"):
            continue
        cur = latest.get(d.concept)
        if cur is None or (newest(d) or date.min) > (newest(cur) or date.min):
            latest[d.concept] = d
    return changes + list(latest.values())


def _n_flags(item) -> int:
    return FLAGS_PER_ITEM if item.priority == "critical" else FLAGS_PER_ITEM_OTHER


class _Ids:
    """Short IDs for the prompt: P1.. passages, T1.. templates, C1.. candidates."""

    def __init__(self):
        self.p_of_seg: dict[str, str] = {}
        self.flag_of_p: dict[str, Flag] = {}
        self.items_of_p: dict[str, set[str]] = {}
        self.t_of: dict[str, Claim] = {}
        self.c_of: dict[str, ContradictionCandidate] = {}

    def passage(self, f: Flag, item_id: str | None) -> str:
        pid = self.p_of_seg.get(f.segment_id)
        if pid is None:
            pid = f"P{len(self.p_of_seg) + 1}"
            self.p_of_seg[f.segment_id] = pid
            self.flag_of_p[pid] = f
        if item_id:
            self.items_of_p.setdefault(pid, set()).add(item_id)
        return pid


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------
_MEMO: "OrderedDict[str, FinalResult]" = OrderedDict()


def summary_keys() -> list[str]:
    """Gemini keys for the LLM steps: GEMINI_API_KEY_2 first, so they don't share quota with
    embeddings (first key), then every other key as a fallback on rate limits."""
    from .llm_client import gemini_keys
    second = os.environ.get("GEMINI_API_KEY_2")
    return list(dict.fromkeys(([second] if second else []) + gemini_keys()))


def default_clients() -> tuple[LLMClient | None, LLMClient | None]:
    """(check client, summary client). Gemini when a key is set, else Claude, else none."""
    load_env_file()
    keys = summary_keys()
    if keys:
        def gem(model, first):
            # the two parallel calls start on different keys, so one request costs each key
            # one call per minute instead of two; both still rotate on a rate limit
            order = keys[first:] + keys[:first]
            c = GeminiClient(model, api_key=order[0])
            c.api_keys = order
            c.models = list(dict.fromkeys([model, DEFAULT_CHECK_MODEL]))  # no slow detours
            return c
        return (gem(os.environ.get("SUMMARY_CHECK_MODEL", DEFAULT_CHECK_MODEL), 0),
                gem(os.environ.get("SUMMARY_MODEL", DEFAULT_SUMMARY_MODEL), 1 % len(keys)))
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return AnthropicClient(), AnthropicClient()
        except ImportError:
            pass
    return None, None


def patient_strip(patient: dict, as_of: date | None) -> PatientStrip:
    dob = date.fromisoformat(patient["dateOfBirth"]) if patient.get("dateOfBirth") else None
    age = None
    if dob and as_of:
        age = as_of.year - dob.year - ((as_of.month, as_of.day) < (dob.month, dob.day))
    return PatientStrip(patient_id=patient.get("id", ""), name=patient.get("name", ""),
                        sex=patient.get("sex", ""), date_of_birth=dob, age_at_as_of=age, as_of=as_of)


class Finalizer:
    def __init__(self, check_client: LLMClient | None = None, summary_client: LLMClient | None = None,
                 budget_s: float | None = None, use_cache: bool = True):
        self.check_client = check_client
        self.summary_client = summary_client
        self.budget_s = budget_s or float(os.environ.get("SUMMARY_BUDGET_S", DEFAULT_BUDGET_S))
        self.use_cache = use_cache

    @classmethod
    def from_env(cls, **kw) -> "Finalizer":
        a, b = default_clients()
        return cls(a, b, **kw)

    # ------------------------------------------------------------------------
    def finalize(self, plan: QueryPlan, rem: RemarkerResult, patient: dict, lang: Lang = "en") -> FinalResult:
        t0 = time.perf_counter()
        key = self._cache_key(plan, rem, lang)
        cached = self._cache_get(key) if self.use_cache else None
        if cached is not None:
            cached.cached = True
            cached.timings_ms = {"total": round((time.perf_counter() - t0) * 1000, 1)}
            return cached

        issues: list[str] = []
        questions = {e.item_id: e.question for e in plan.checklist.entries}
        time_rules = {e.item_id: e.time_rule for e in plan.checklist.entries}
        items = self._items(rem.items)
        custom = self._items(rem.custom)
        ids = _Ids()
        templates: dict[str, Claim] = {}
        for it in items + custom:
            cid = f"T{len(templates) + 1}"
            templates[it.item_id] = template_claim(it, lang, cid, time_rules.get(it.item_id, "history"), rem.doc_labels)
            ids.t_of[cid] = templates[it.item_id]
        for it in items + custom:
            for f in it.flags[:_n_flags(it)]:
                ids.passage(f, it.item_id)
        seg_flags = {f.segment_id: f for it in items + custom for f in it.flags}
        for n, cand in enumerate(rem.contradictions):
            if cand.status == "candidate" and cand.segment_ids and all(s in seg_flags for s in cand.segment_ids):
                ids.c_of[f"C{n + 1}"] = cand
                for s in cand.segment_ids:
                    ids.passage(seg_flags[s], None)
        payload = self._payload(plan, items + custom, ids, questions, time_rules, lang)
        t_build = time.perf_counter()

        check_data, summary_data, models = self._call_llms(payload, lang, issues)
        t_llm = time.perf_counter()

        self._apply_check(items + custom, check_data, ids, issues)
        items.sort(key=lambda it: (PRIORITY_ORDER[it.priority], it.order))
        for n, it in enumerate(items):
            it.order = n
        for it in items + custom:  # templates must reflect the checked passages
            old = templates[it.item_id]
            templates[it.item_id] = template_claim(it, lang, old.claim_id, time_rules.get(it.item_id, "history"), rem.doc_labels)
            ids.t_of[old.claim_id] = templates[it.item_id]
        kept_segs = {f.segment_id for it in items + custom for f in it.flags}
        summary, dropped_claims = self._summary(items, custom, summary_data, templates, ids, kept_segs, lang)
        conflicts = self._conflicts(rem.contradictions, summary_data, ids, lang, kept_segs | set(seg_flags))
        # A conflict joins the summary only when it concerns this request: one of its passages
        # (or a duplicate of one) is a kept passage of a checklist item. All conflicts stay listed.
        flagged = kept_segs | {d for it in items + custom for f in it.flags for d in f.duplicates}
        relevant = [c for c in conflicts if c.items or flagged & set(c.segment_ids)]
        if relevant and len(summary) < MAX_SUMMARY_WITH_CRITICAL:
            c = relevant[0]
            quotes = "; ".join(_quote(seg_flags[s], 90, rem.doc_labels, lang) for s in c.segment_ids if s in seg_flags) \
                or ", ".join(c.doc_ids)
            summary.append(Claim(claim_id=f"X{len(summary) + 1}", item_id=None, lang=lang,
                                 text=_TPL[lang]["conflict"].format(diff=" / ".join(c.differing) or _short(c.explanation), quotes=quotes),
                                 cites=c.segment_ids, kind="conflict", rendered_by="template"))
        doc_dates = {r.doc_id: r.date for r in rem.records}
        for d in _select_derived(rem.derived, doc_dates):
            if len(summary) >= MAX_SUMMARY_WITH_CRITICAL or not d.segment_ids:
                break
            if not any(it.item_id in d.items for it in items):
                continue
            label = DERIVED_LABELS.get(d.concept, {}).get(lang, d.label)
            when = " → ".join(dict.fromkeys(f"{doc} {doc_dates[doc]}" for doc in d.doc_ids if doc in doc_dates and doc_dates[doc]))
            value = f"{d.value_text} ({when})" if when else d.value_text
            summary.append(Claim(claim_id=f"V{len(summary) + 1}", item_id=d.items[0] if d.items else None,
                                 lang=lang, text=_TPL[lang]["derived"].format(label=label, value=value),
                                 cites=d.segment_ids, kind="finding", rendered_by="template"))
        records = self._records(items + custom, rem.records)
        t_end = time.perf_counter()

        llm_parts = [k for k in ("check", "summary") if k in models]
        mode = "llm" if len(llm_parts) == 2 else "partial" if llm_parts else "template_only"
        as_of = plan.as_of or rem.as_of
        result = FinalResult(
            patient=patient_strip(patient, as_of), lang=lang, summary=summary, items=items,
            custom=custom, conflicts=conflicts, records=records, mode=mode, models=models,
            timings_ms={"build": round((t_build - t0) * 1000, 1),
                        "llm": round((t_llm - t_build) * 1000, 1),
                        "check": round((t_end - t_llm) * 1000, 1),
                        "total": round((t_end - t0) * 1000, 1)},
            issues=issues, dropped_claims=dropped_claims, derived=list(rem.derived),
            coverage=dict(rem.coverage), privacy=outbound.stats(), doc_labels=dict(rem.doc_labels))
        if self.use_cache and mode == "llm":
            self._cache_put(key, result)
        return result

    # ------------------------------------------------------------------------
    @staticmethod
    def _items(evidence: list[ItemEvidence]) -> list[ItemResult]:
        return [ItemResult(item_id=e.item_id, label=e.label, priority=e.priority, status=e.status,
                           order=n, flags=[f.model_copy(deep=True) for f in e.flags], note=e.note)
                for n, e in enumerate(evidence)]

    @staticmethod
    def _payload(plan, items, ids: _Ids, questions, time_rules, lang) -> dict:
        roles = [h.node_id for h in plan.nodes if h.kind in ("role", "task", "context", "concept")
                 and h.source not in ("ancestor", "default")]
        passages = []
        for pid, f in ids.flag_of_p.items():
            passages.append({"id": pid, "doc": f.doc_id,
                             "date": f.doc_date.isoformat() if f.doc_date else "",
                             "section": f.section, "polarity": f.polarity,
                             "text": " ".join(f.text.split())[:PASSAGE_CHARS]})
        item_rows = [{"id": it.item_id, "question": questions.get(it.item_id, it.label.en),
                      "priority": it.priority, "status": it.status,
                      "time": time_rules.get(it.item_id, "history"),
                      "passages": [ids.p_of_seg[f.segment_id] for f in it.flags[:_n_flags(it)]]}
                     for it in items]
        return {
            "request": plan.prompt, "understood_as": roles,
            "as_of": (plan.as_of.isoformat() if plan.as_of else "latest document"),
            "items": item_rows, "passages": passages,
            "templates": [{"id": cid, "item": c.item_id, "text": c.text} for cid, c in ids.t_of.items()],
            "contradiction_candidates": [{"id": cid, "passages": [ids.p_of_seg[s] for s in c.segment_ids],
                                          "differing": c.differing} for cid, c in ids.c_of.items()],
        }

    def _call_llms(self, payload: dict, lang: Lang, issues: list[str]):
        check_data = summary_data = None
        models: dict[str, str] = {}
        if not (self.check_client or self.summary_client):
            issues.append("No LLM configured; template-only summary.")
            return None, None, models
        deadline = time.perf_counter() + self.budget_s
        check_msg = json.dumps({k: payload[k] for k in ("request", "understood_as", "as_of", "items", "passages")},
                               ensure_ascii=False)
        summary_msg = json.dumps(payload, ensure_ascii=False)
        language = "English" if lang == "en" else "German"
        jobs = {}
        pool = cf.ThreadPoolExecutor(max_workers=2)
        try:
            if self.check_client:
                jobs["check"] = pool.submit(self.check_client.complete_json, CHECK_SYSTEM, check_msg,
                                            CHECK_SCHEMA, self.budget_s)
            if self.summary_client:
                jobs["summary"] = pool.submit(self.summary_client.complete_json,
                                              SUMMARY_SYSTEM.format(language=language), summary_msg,
                                              SUMMARY_SCHEMA, self.budget_s)
            for name, fut in jobs.items():
                try:
                    res = fut.result(timeout=max(0.05, deadline - time.perf_counter()))
                    models[name] = res.model
                    if name == "check":
                        check_data = res.data
                    else:
                        summary_data = res.data
                except cf.TimeoutError:
                    issues.append(f"LLM {name} exceeded the {self.budget_s:.1f} s budget; templates used.")
                except LLMError as e:
                    issues.append(f"LLM {name} failed ({str(e)[:160]}); templates used.")
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        return check_data, summary_data, models

    @staticmethod
    def _apply_check(items: list[ItemResult], data: dict | None, ids: _Ids, issues: list[str]) -> None:
        if not data:
            return
        by_id = {it.item_id: it for it in items}
        drops: dict[str, dict[str, str]] = {}
        ignored = 0
        for d in data.get("drops") or []:
            it = by_id.get(d.get("item_id"))
            f = ids.flag_of_p.get(d.get("passage"))
            if not it or not f or d.get("reason") not in DROP_REASONS or \
                    f.segment_id not in {x.segment_id for x in it.flags[:_n_flags(it)]}:
                ignored += 1
                continue
            drops.setdefault(it.item_id, {})[f.segment_id] = d["reason"]
        if ignored:
            issues.append(f"Ignored {ignored} invalid drop(s) from the ranking check.")
        for item_id, segs in drops.items():
            it = by_id[item_id]
            kept = [f for f in it.flags if f.segment_id not in segs]
            if not kept and it.flags and it.flags[0].ridx >= KEEP_GUARD_RIDX:
                best = it.flags[0]
                segs.pop(best.segment_id, None)
                kept = [best]
                issues.append(f"{item_id}: kept the strongest passage although the check dropped all.")
            it.dropped = [DroppedFlag(segment_id=s, reason=r) for s, r in segs.items()]
            it.flags = kept
            if not kept and it.status in ("found", "uncertain", "documented_absent"):
                it.status = "not_documented"
                it.note = "All marked passages were rejected by the ranking check."
        order = [o for o in (data.get("order") or []) if o in by_id]
        rank = {o: n for n, o in enumerate(order)}
        for it in items:
            it.order = rank.get(it.item_id, len(rank) + it.order)

    def _summary(self, items, custom, data, templates, ids: _Ids, kept_segs, lang):
        by_id = {it.item_id: it for it in items + custom}
        out: list[Claim] = []
        used_items: set[str] = set()
        dropped: list[dict] = []

        def add_template(item_id):
            c = templates.get(item_id)
            if c and item_id not in used_items:
                if c.kind in ("finding", "absent", "uncertain") and not set(c.cites) <= kept_segs:
                    return
                out.append(c.model_copy(update={"claim_id": f"S{len(out) + 1}"}))
                used_items.add(item_id)

        for entry in (data or {}).get("summary") or []:
            if len(out) >= MAX_SUMMARY:
                break
            tid = (entry.get("template") or "").strip()
            if tid:
                c = ids.t_of.get(tid)
                if c:
                    add_template(c.item_id)
                continue
            text = " ".join((entry.get("text") or "").split())
            if not text:
                continue
            cites = [ids.flag_of_p[p] for p in entry.get("cites") or [] if p in ids.flag_of_p]
            cites = [f for f in cites if f.segment_id in kept_segs]
            item_id = entry.get("item_id") if entry.get("item_id") in by_id else None
            if item_id is None and cites:
                item_id = next(iter(sorted(ids.items_of_p.get(ids.p_of_seg[cites[0].segment_id], {None}) - {None})), None)
            kind = entry.get("kind") if entry.get("kind") in CLAIM_KINDS else "finding"
            reason = "too long" if len(text) > 320 else check_claim(text, cites, kind)
            if reason:
                dropped.append({"text": text, "reason": reason})
                if item_id:
                    add_template(item_id)
                continue
            if item_id in used_items:
                continue
            out.append(Claim(claim_id=f"S{len(out) + 1}", item_id=item_id, text=text, lang=lang,
                             cites=[f.segment_id for f in cites], kind=kind, rendered_by="llm"))
            if item_id:
                used_items.add(item_id)

        for it in items:  # critical items are always visible
            if it.priority == "critical" and len(out) < MAX_SUMMARY_WITH_CRITICAL:
                add_template(it.item_id)
        # free slots go to the next items in ranked order, so what the summary shows does not
        # depend on how many lines the LLM happened to pick
        for it in items:
            if len(out) >= MAX_SUMMARY:
                break
            add_template(it.item_id)
        return out, dropped

    @staticmethod
    def _conflicts(cands, data, ids: _Ids, lang, known_segs) -> list[Conflict]:
        verdicts = {c.get("candidate"): c for c in (data or {}).get("conflicts") or []}
        out = []
        for n, cand in enumerate(cands):
            cid = f"C{n + 1}"
            if cand.status == "accepted" and len(cand.segment_ids) >= 1:
                out.append(Conflict(segment_ids=cand.segment_ids, doc_ids=cand.doc_ids, kind=cand.kind,
                                    differing=cand.differing, explanation=cand.explanation or "",
                                    confirmed_by="rule", items=list(cand.items)))
                continue
            v = verdicts.get(cid) if cid in ids.c_of else None
            what = {"laterality": ("sides", "Seitenangabe"), "number": ("values", "Zahlenangabe"),
                    "date": ("dates", "Datumsangabe"), "status": ("status", "Status"),
                    "other": ("content", "Inhalt")}.get(cand.kind, ("content", "Inhalt"))
            rule_expl = _TPL[lang]["conflict_expl"].format(what=what[0] if lang == "en" else what[1],
                                                           diff=" / ".join(cand.differing))
            if v is not None:
                if not v.get("real"):
                    continue
                expl = " ".join((v.get("explanation") or "").split())[:300]
                flags = [ids.flag_of_p[ids.p_of_seg[s]] for s in cand.segment_ids if s in ids.p_of_seg]
                if not expl or _numbers(expl) - _numbers(" ".join(f.text for f in flags)):
                    expl = rule_expl
                out.append(Conflict(segment_ids=cand.segment_ids, doc_ids=cand.doc_ids, kind=cand.kind,
                                    differing=cand.differing, explanation=expl, confirmed_by="llm",
                                    items=list(cand.items)))
            elif cand.kind == "laterality" and len(cand.segment_ids) >= 2:
                # near-identical passages that name different sides cannot both be true
                out.append(Conflict(segment_ids=cand.segment_ids, doc_ids=cand.doc_ids, kind=cand.kind,
                                    differing=cand.differing, explanation=rule_expl, confirmed_by="rule",
                                    items=list(cand.items)))
        # neighbouring sentences of one passage pair are one contradiction, counted once
        merged: list[Conflict] = []
        for c in out:
            for m in merged:
                same_docs = bool(set(m.doc_ids) & set(c.doc_ids))
                same_segs = bool(set(m.segment_ids) & set(c.segment_ids))
                if m.kind == c.kind and (same_segs or (same_docs and c.kind != "number")):
                    m.segment_ids += [s for s in c.segment_ids if s not in m.segment_ids]
                    m.doc_ids += [d for d in c.doc_ids if d not in m.doc_ids]
                    m.differing += [d for d in c.differing if d not in m.differing]
                    m.items += [i for i in c.items if i not in m.items]
                    if len(c.explanation) > len(m.explanation):
                        m.explanation = c.explanation
                    break
            else:
                merged.append(c)
        return merged

    @staticmethod
    def _records(items: list[ItemResult], old: list[RecordRelevance]) -> list[RecordRelevance]:
        total = sum(PRIORITY_WEIGHT[it.priority] for it in items) or 1.0
        per: dict[str, dict] = {r.doc_id: {"score": 0.0, "labels": {}, "flags": []} for r in old}
        for it in items:
            best: dict[str, float] = {}
            for f in it.flags:
                for doc in {f.doc_id} | {s.split("#")[0] for s in f.duplicates}:
                    if doc not in per:
                        continue
                    best[doc] = max(best.get(doc, 0), f.ridx)
                    per[doc]["labels"][it.item_id] = per[doc]["labels"].get(it.item_id, 0) + 1
                if f.doc_id in per:
                    per[f.doc_id]["flags"].append((f.ridx * PRIORITY_WEIGHT[it.priority], f.segment_id))
            for doc, r in best.items():
                per[doc]["score"] += PRIORITY_WEIGHT[it.priority] * r
        out = []
        for r in old:
            v = per[r.doc_id]
            out.append(r.model_copy(update={
                "score": round(100 * v["score"] / total, 1), "label_counts": v["labels"],
                "top_flags": [s for _, s in sorted(v["flags"], reverse=True)][:5]}))
        out.sort(key=lambda r: -r.score)
        return out

    # ------------------------------------------------------------------------
    def _cache_key(self, plan: QueryPlan, rem: RemarkerResult, lang: str) -> str:
        models = [getattr(c, "model", "") for c in (self.check_client, self.summary_client) if c]
        basis = {
            "version": CACHE_VERSION, "lang": lang, "models": models, "prompt": plan.prompt,
            "items": [(e.item_id, e.priority, e.status, [(f.segment_id, round(f.ridx, 2), f.polarity)
                                                         for f in e.flags]) for e in rem.items + rem.custom],
            "cands": [(c.segment_ids, c.items) for c in rem.contradictions],
        }
        return hashlib.sha256(json.dumps(basis, sort_keys=True, default=str).encode()).hexdigest()[:24]

    def _cache_get(self, key: str) -> FinalResult | None:
        if key in _MEMO:
            _MEMO.move_to_end(key)
            return _MEMO[key].model_copy(deep=True)
        path = CACHE_DIR / f"{key}.json"
        if path.exists():
            try:
                res = FinalResult.model_validate_json(vault.read_text(path))
                _MEMO[key] = res
                return res.model_copy(deep=True)
            except (ValueError, vault.VaultError):
                return None
        return None

    def _cache_put(self, key: str, result: FinalResult) -> None:
        _MEMO[key] = result.model_copy(deep=True)
        while len(_MEMO) > 64:
            _MEMO.popitem(last=False)
        vault.write_text(CACHE_DIR / f"{key}.json", result.model_dump_json())


# ---------------------------------------------------------------------------
def _main(argv: list[str]) -> int:
    from .prompt_analysis import PromptAnalyzer
    from .remarker import Remarker

    ap = argparse.ArgumentParser(prog="python -m app.summary")
    ap.add_argument("prompt")
    ap.add_argument("--patient", type=Path, default=os.environ.get("PATIENT_DIR"))
    ap.add_argument("--lang", default="en", choices=["en", "de"])
    ap.add_argument("--no-llm", action="store_true", help="template-only summary")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--json", action="store_true", help="print the full FinalResult")
    args = ap.parse_args(argv)
    if not args.patient:
        print("Pass --patient <folder with patient.json and documents/> or set PATIENT_DIR.")
        return 2
    rm = Remarker.for_patient(args.patient)
    t = time.perf_counter()
    plan = PromptAnalyzer(rm.tree, None, "off").analyse(args.prompt)
    t_plan = time.perf_counter()
    rem = rm.remark(plan)
    t_rem = time.perf_counter()
    fin = (Finalizer(None, None) if args.no_llm else Finalizer.from_env(use_cache=not args.no_cache))
    patient = json.loads((args.patient / "patient.json").read_text(encoding="utf-8"))
    res = fin.finalize(plan, rem, patient, args.lang)
    t_end = time.perf_counter()
    if args.json:
        print(res.model_dump_json(indent=1))
        return 0
    p = res.patient
    print(f"{p.name}, {p.sex}, born {p.date_of_birth}, age {p.age_at_as_of} as of {p.as_of}")
    print(f"mode {res.mode} {res.models} cached={res.cached}")
    print("SUMMARY")
    for c in res.summary:
        print(f"  [{c.rendered_by}/{c.kind}] {c.text}  -> {c.cites}")
    print("RANKED ITEMS")
    for it in res.items:
        drops = ", ".join(f"{d.segment_id}:{d.reason}" for d in it.dropped)
        print(f"  {it.priority:<8} {it.item_id:<26} {it.status:<16} kept {len(it.flags)}"
              + (f"  dropped {drops}" if drops else ""))
    for c in res.conflicts:
        print(f"CONFLICT ({c.confirmed_by}) {c.segment_ids}: {c.explanation}")
    if res.dropped_claims:
        print("dropped LLM claims:", res.dropped_claims)
    if res.issues:
        print("issues:", res.issues)
    print(f"timings: plan {(t_plan - t) * 1000:.0f} ms, remark {(t_rem - t_plan) * 1000:.0f} ms, "
          f"final {res.timings_ms}, end-to-end {(t_end - t) * 1000:.0f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
