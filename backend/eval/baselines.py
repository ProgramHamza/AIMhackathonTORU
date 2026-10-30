"""Baselines for report 5. Each turns (prompt, patient) into a Screen: the statements a
clinician would see, each optionally linked to a document and a quote.

A  LLM-only:   the whole record and the request in ONE model call ("here is the data,
               here is what I need"). Same model as our final step (Gemini Flash-Lite),
               same outbound gate, no graph, no retrieval, no checks.
B  Rules-only: if/else on words in the request picks topics; each topic is a fixed list of
               German keywords; every sentence containing one is shown verbatim. Generic
               clinical vocabulary only, nothing specific to this patient.
Our system is adapted to the same Screen shape (full, and without any LLM).
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.segmenter import load_documents, segment_document
from app.keywords import DOC_NAMES
from app.summary import summary_keys
from app.llm_client import GeminiClient, LLMError


@dataclass
class Statement:
    text: str
    doc_id: str | None = None
    quote: str | None = None
    kind: str = "finding"          # finding | not_documented | conflict


@dataclass
class Screen:
    system: str
    statements: list[Statement]
    ms: float
    llm_calls: int = 0
    error: str | None = None
    extra: dict = field(default_factory=dict)


def _docs_text(patient: Path) -> dict[str, dict]:
    return {d.doc_id: {"title": d.title, "date": d.date.isoformat() if d.date else "", "text": d.text}
            for d in load_documents(patient)}


# ---------------------------------------------------------------------------
# A: one LLM call
# ---------------------------------------------------------------------------
LLM_SYSTEM = """\
You are a clinical assistant. A clinician tells you their role and task. You get all of the
patient's documents (German). Produce the screen the clinician needs for this task:
- the patient facts this task needs, most important first, each with the document ID and an
  exact quote copied from that document;
- facts the task needs that the documents do not contain, as "not documented";
- contradictions between or within documents, with the document IDs and quotes involved.
Present-tense questions mean as of the latest document. Answer in English; quotes stay in
the original German. Use only the documents.
"""
LLM_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["facts", "not_documented", "contradictions"],
    "properties": {
        "facts": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                             "required": ["statement", "doc_id", "quote"],
                                             "properties": {"statement": {"type": "string"}, "doc_id": {"type": "string"},
                                                            "quote": {"type": "string"}}}},
        "not_documented": {"type": "array", "items": {"type": "string"}},
        "contradictions": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                      "required": ["description", "doc_ids", "quotes"],
                                                      "properties": {"description": {"type": "string"},
                                                                     "doc_ids": {"type": "array", "items": {"type": "string"}},
                                                                     "quotes": {"type": "array", "items": {"type": "string"}}}}},
    },
}


class LLMOnlyBaseline:
    name = "LLM only (one call)"

    def __init__(self, patient: Path, model: str = "gemini-flash-lite-latest", timeout: float = 90.0):
        self.docs = _docs_text(patient)
        keys = summary_keys()
        self.client = GeminiClient(model, api_key=keys[0]) if keys else None
        if self.client:
            self.client.api_keys = keys
            self.client.models = [model]
        self.timeout = timeout
        record = "\n\n".join(f"=== Document {d} | {v['title']} | {v['date']} ===\n{v['text']}" for d, v in self.docs.items())
        self.record = record

    def run(self, prompt: str) -> Screen:
        t = time.perf_counter()
        if not self.client:
            return Screen(self.name, [], 0, error="no Gemini key")
        user = f"Clinician request: {prompt}\n\nPatient documents:\n{self.record}"
        try:
            res = self.client.complete_json(LLM_SYSTEM, user, LLM_SCHEMA, self.timeout)
        except LLMError as e:
            return Screen(self.name, [], (time.perf_counter() - t) * 1000, llm_calls=1, error=str(e)[:200])
        d = res.data
        st = [Statement(f.get("statement", ""), str(f.get("doc_id", "")).strip() or None, f.get("quote") or None)
              for f in d.get("facts", []) if isinstance(f, dict)]
        st += [Statement(f"{x}: not documented" if "not documented" not in x.lower() else x, kind="not_documented")
               for x in d.get("not_documented", []) if isinstance(x, str)]
        for c in d.get("contradictions", []):
            if isinstance(c, dict):
                ids = [str(x) for x in c.get("doc_ids", [])]
                st.append(Statement(c.get("description", ""), ids[0] if ids else None,
                                    (c.get("quotes") or [None])[0], kind="conflict"))
        return Screen(self.name, st, (time.perf_counter() - t) * 1000, llm_calls=1)


# ---------------------------------------------------------------------------
# B: if/else rules
# ---------------------------------------------------------------------------
TOPICS = {
    "allergies": ["allergi", "unverträglich", "cave", "km-allergie", "kontrastmittelallergie"],
    "anticoagulants": ["ass ", "aspirin", "marcumar", "heparin", "clopidogrel", "xarelto", "eliquis", "antikoag",
                       "thrombozytenaggregation"],
    "medication": ["entlassungsmedikation", " mg ", "mg oral", "tabl", "tropfen", "s.c."],
    "heart": ["ef ", "ejektionsfraktion", "lv-funktion", "echokardiograph", "ekg"],
    "diabetes": ["hba1c", "diabetes", "metformin", "insulin", "antidiabet"],
    "weight": ["gewicht", "bmi", "größe"],
    "blood_pressure": ["blutdruck", "rr ", "mmhg", "hypertonie", "antihypertensiv"],
    "cancer": ["karzinom", "histolog", "tnm", "rezeptor", "her2", "ki67", "tumorboard", "biopsie"],
    "imaging": ["sonograph", "ultraschall", "ct", "mrt", "duplex", "mammograph", "befund"],
    "vascular": ["stenose", "carotis", "karotis", "plaque"],
    "followups": ["kontrolle", "empfohlen", "nachsorge", "procedere", "geplant", "in 2 monaten"],
    "kidney": ["kreatinin", "egfr", "niere"],
    "previous_events": ["krise", "schwindel", "amaurosis", "sehstörung", "z.n.", "st.p."],
}
ROLE_RULES = [  # (words in the request, topics to show)
    (["anaesth", "anesth", "anästh"], ["allergies", "anticoagulants", "heart", "medication", "kidney"]),
    (["surgeon", "chirurg", "surgery planning", "tumour board", "tumor board"], ["cancer", "imaging", "anticoagulants", "allergies"]),
    (["oncolog", "onkolog"], ["cancer", "imaging", "medication"]),
    (["emergency", "notarzt", "notfall", "night duty"], ["allergies", "anticoagulants", "medication", "previous_events", "kidney"]),
    (["gp", "general practitioner", "hausarzt", "family doctor"], ["medication", "blood_pressure", "weight", "followups"]),
    (["cardiolog", "kardiolog"], ["heart", "blood_pressure", "anticoagulants", "medication"]),
    (["radiolog"], ["allergies", "kidney", "imaging"]),
    (["neurolog"], ["previous_events", "vascular", "anticoagulants"]),
    (["nurse", "pflege"], ["allergies", "medication"]),
    (["pharmac", "apothek"], ["medication", "allergies", "kidney"]),
]
TASK_RULES = [
    (["diabet"], ["diabetes", "weight"]), (["follow"], ["followups", "vascular", "imaging"]),
    (["contrast", "kontrastmittel"], ["allergies", "kidney"]), (["dizz", "vision", "schwindel"], ["previous_events", "vascular"]),
    (["weight"], ["weight"]), (["blood pressure", "blutdruck"], ["blood_pressure"]),
    (["pre-op", "preop", "pre-operative", "präoperativ"], ["allergies", "anticoagulants", "heart"]),
]
DEFAULT_TOPICS = ["allergies", "medication", "previous_events"]
MAX_PER_TOPIC = 4


class RulesBaseline:
    name = "Rules only (if/else)"

    def __init__(self, patient: Path):
        self.docs = load_documents(patient)
        self.sentences = [(s.doc_id, s.text) for d in self.docs for s in segment_document(d)
                          if s.kind in ("sentence", "field", "table_row")]

    def run(self, prompt: str) -> Screen:
        t = time.perf_counter()
        low = prompt.lower()
        topics: list[str] = []
        for words, ts in ROLE_RULES + TASK_RULES:
            if any(w in low for w in words):
                topics += [x for x in ts if x not in topics]
        if not topics:
            topics = list(DEFAULT_TOPICS)
        st: list[Statement] = []
        for topic in topics:
            hits = []
            for doc, text in self.sentences:
                padded = " " + " ".join(text.lower().split()) + " "
                if any(k in padded for k in TOPICS[topic]) and (doc, text) not in hits:
                    hits.append((doc, text))
            if not hits:
                st.append(Statement(f"{topic.replace('_', ' ')}: not documented", kind="not_documented"))
            for doc, text in hits[:MAX_PER_TOPIC]:
                st.append(Statement(f"{topic.replace('_', ' ')}: {' '.join(text.split())}", doc, text))
        return Screen(self.name, st, (time.perf_counter() - t) * 1000)


# ---------------------------------------------------------------------------
# Our system, as a Screen
# ---------------------------------------------------------------------------
def _doc_name(final, doc_id: str) -> str:
    return final.doc_labels.get(doc_id, {}).get("en") or doc_id


def screen_from_final(name: str, res, calls: int) -> Screen:
    f = res.final
    st: list[Statement] = []
    segs = {}
    for it in f.items:
        for fl in it.flags:
            segs[fl.segment_id] = fl
    for c in f.summary:
        if c.kind == "conflict":
            continue
        cite = segs.get(c.cites[0]) if c.cites else None
        kind = ("not_documented" if c.kind in ("not_documented", "incomplete")
                else "derived" if c.claim_id.startswith("V") else "finding")
        st.append(Statement(c.text, cite.doc_id if cite else None, cite.text if cite else None, kind))
    for it in f.items:  # the ranked list under the summary
        if it.status in ("not_documented", "processing_incomplete"):
            st.append(Statement(f"{it.label.en}: not documented", kind="not_documented"))
        elif it.flags:
            fl = it.flags[0]
            key = fl.keyword or ' '.join(fl.text.split())
            st.append(Statement(f"{it.label.en}: {key} ({_doc_name(f, fl.doc_id)})", fl.doc_id, fl.text))
    for cf in f.conflicts:
        st.append(Statement(f"Conflict: {cf.explanation} ({', '.join(_doc_name(f, d) for d in cf.doc_ids)})",
                            cf.doc_ids[0] if cf.doc_ids else None, None, "conflict"))
    return Screen(name, st, res.timings_ms["total"], llm_calls=calls)


# ---------------------------------------------------------------------------
# Code-checked metrics on a Screen
# ---------------------------------------------------------------------------
_WS = re.compile(r"\s+")
_NAMES = "|".join(re.escape(n) for _, en, de in DOC_NAMES for n in (en, de))
# source tags, not content: "[90010018, 2016-04-15]", "(90010018, 2016-04-15)", "(Arztbrief 04/2016)"
_TAG = re.compile(r"[\[(]\d{6,}(?:,\s*(?:\d{4}-\d{2}-\d{2}|\?))?[\])]"
                  rf"|\((?:{_NAMES}) (?:\d{{2}}/\d{{4}}|\d{{2}}\.\d{{2}}\.\d{{4}})\)")


def _num(n: str) -> str:
    n = n.replace(",", ".")
    return n.rstrip("0").rstrip(".") if "." in n else (n.lstrip("0") or "0")
_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def _norm(s: str) -> str:
    return _WS.sub(" ", s or "").strip().lower()


def code_metrics(screen: Screen, docs: dict[str, str]) -> dict:
    all_text = _norm(" ".join(docs.values()))
    findings = [s for s in screen.statements if s.kind == "finding"]
    linked = [s for s in findings if s.doc_id and s.doc_id in docs]
    traceable = [s for s in linked if s.quote and _norm(s.quote) in _norm(docs[s.doc_id])]
    unsupported = 0
    for s in findings:
        # source tags like "[90010018, 2016-04-15]" are citations, not claims
        text = _TAG.sub(" ", s.text)
        cited = [d for d in docs if d in s.text] or ([s.doc_id] if s.doc_id in docs else [])
        src = _norm(" ".join(docs[d] for d in cited)) if cited else all_text
        nums = {_num(n) for n in _NUM.findall(text)}
        src_nums = {_num(n) for n in _NUM.findall(src)}
        if nums - src_nums - {str(y) for y in range(2014, 2018)}:
            unsupported += 1
    return {"statements": len(screen.statements), "findings": len(findings),
            "linked_to_document": len(linked), "quote_exact": len(traceable),
            "traceability": round(len(traceable) / len(findings), 4) if findings else None,
            "unsupported_numbers": unsupported,
            "not_documented_lines": sum(s.kind == "not_documented" for s in screen.statements),
            "derived_lines": sum(s.kind == "derived" for s in screen.statements),
            "conflict_lines": sum(s.kind == "conflict" for s in screen.statements)}
