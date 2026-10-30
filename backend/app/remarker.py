"""Blocks 6/7: the remarker. Marks the passages each checklist item needs.

Offline, once per patient (cached in .cache/remarker/<patient>/):
  * segment the documents (segmenter.py) and tag every segment:
      polarity (negated / uncertain / past / planned / affirmed), sides (left/right/both),
      fact domains from its section or label, decision-graph nodes it mentions,
      ICD/ATC codes from the IBM extraction (an index only; the text is the source).
  * near-duplicates across documents are grouped; near-duplicates that differ only in a
    side or a number become contradiction candidates.
  * score EVERY (checklist item, segment) pair once. Items are a fixed list, so a role or
    task never changes these scores, only which items are asked for. Signals:
      lexical  item terms found in the segment (Aho-Corasick, idf-weighted, compounds)
      dense    Gemini embedding similarity (item question vs segment)
      rerank   Jina cross-encoder on each item's top candidates (optional)
      code     an IBM mention with a matching ICD/ATC code sits in the segment
      section  the segment's section domain matches the item's domains
    ridx = noisy-OR of the signals, then a section boost.

Online, per QueryPlan (no API call unless the plan has custom questions):
  * read the precomputed rows of the plan's items,
  * add context terms (e.g. the presenting symptoms for "similar previous episodes"),
    LLM-added search terms, and the as-of date,
  * pick flags, collapse duplicates, mark superseded values, decide the item status,
  * custom questions: one batched embedding call for all of them,
  * rank documents for the record list.

CLI
  python -m app.remarker build --patient <patient dir> [--no-dense] [--rerank]
  python -m app.remarker query --patient <patient dir> "anaesthetist, pre-op check"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np

from .contracts import (DerivedValue, ContradictionCandidate, Flag, ItemEvidence, LocalizedText, QueryPlan,
                        RecordRelevance, RemarkerResult, Segment)
from . import vault
from .evidence_bridge import BundleError, EvidenceLayer, build_layer, load_bundle
from .outbound import configure as configure_outbound
from .deidentify import Deidentifier
from .embeddings import CACHE_DIR, EmbeddingError, GeminiEmbedder, JinaReranker
from .segmenter import load_documents, segment_document
from .tree import PRIORITY_WEIGHT, Automaton, DecisionTree, normalize

INDEX_VERSION = "1"
FLAG_THRESHOLD = 0.5
MAX_FLAGS = 6
RERANK_CANDIDATES = 20

# signal weights for the noisy-OR: ridx = 1 - prod(1 - w * signal)
W_LEXICAL, W_DENSE, W_RERANK, W_CODE = 0.7, 0.55, 0.6, 0.75
W_SECTION, W_CONTEXT, W_LLM_TERMS = 0.35, 0.55, 0.8
W_FACT = 0.6  # a verified fact (blocks 1-4) that fits the item sits in the segment
FACT_MIN_BASE = 0.35  # the segment must already score this much for the item before a fact counts
# fact kind -> item domains it belongs to (the item's domains must include one of these)
FACT_KIND_DOMAINS = {"medication": {"medications"}, "allergy": {"allergies", "alerts"},
                     "measurement": {"vital_signs", "results_lab", "results_pathology"}}
LEXICAL_SCALE = 4.0       # idf sum that gives ~63% lexical strength
HEADER_LEXICAL = 0.6      # lexical strength of a passage listed under a header that names the item
IDF_MIN_PASSAGES = 150    # term rarity is judged as in a record of at least this size: in a small imported
                          # record every word looks common and a drug name alone would never flag
DENSE_LOW_PCT, DENSE_HIGH_PCT = 75, 99.5
RERANK_LOW, RERANK_SPAN = 0.05, 0.25

# items whose meaning depends on the request (e.g. "did this happen before?")
CONTEXTUAL_ITEMS = {"prior_similar_events", "imaging_findings", "neuro_findings", "eye_findings",
                    "vascular_findings", "recent_admissions", "planned_procedures", "active_problems"}
# a "completed" item only counts after the recommendation it completes
COMPLETES = {"followups_completed": "followups_recommended"}
# derived values from blocks 1-4 -> the checklist items they answer
DERIVED_ITEMS = {"body_weight_change": ["weight_bmi"], "body_mass_index": ["weight_bmi"]}
NOT_EVIDENCE = {"followups_completed": {"planned", "uncertain"}}

NEG_PRE = {"kein", "keine", "keinen", "keiner", "keinem", "keines", "ohne", "nicht", "weder",
           "no", "not", "without", "negative for"}
NEG_POST = ("nicht erkennbar", "nicht nachweisbar", "nicht vorhanden", "ausgeschlossen",
            "not seen", "ruled out")
UNCERTAIN = {"verdacht", "vd.a", "v.a", "fraglich", "suspected", "fragestellung"}
PAST = ("st.p", "z.n", "zustand nach", "status post", "s.p")
PLANNED = ("geplant", "geplante", "geplanter", "empfohlen", "empfehlung", "terminisiert",
           "naechste", "sollten", "in 2 monaten", "wird empfohlen", "vorgesehen")
SIDES = {
    "left": {"links", "linke", "linken", "linker", "linkes", "li", "sin", "sinister", "sinistra", "left"},
    "right": {"rechts", "rechte", "rechten", "rechter", "rechtes", "re", "dex", "dexter", "dextra", "right"},
    "both": {"bds", "beidseits", "beidseitig", "bilateral"},
}
SECTION_DOMAINS = [
    ("allergi", {"allergies", "alerts"}), ("cave", {"alerts", "allergies"}),
    ("diagnose", {"problems", "past_problems"}),
    ("anamnese", {"problems", "past_problems", "encounters", "social_history", "family_history"}),
    ("medikation", {"medications"}), ("therapie", {"medications", "procedures", "plan_of_care", "encounters"}),
    ("verlauf", {"encounters", "procedures", "plan_of_care", "medications"}),
    ("procedere", {"plan_of_care", "procedures", "medications"}),
    ("empfehlung", {"plan_of_care"}), ("lungenfunktion", {"results_lab", "functional_status"}),
    ("blutgas", {"results_lab"}),
    ("labor", {"results_lab"}),
    ("histolog", {"results_pathology"}), ("mikroskop", {"results_pathology"}),
    ("makroskop", {"results_pathology"}), ("immunhisto", {"results_pathology"}),
    ("rezeptor", {"results_pathology"}), ("ki67", {"results_pathology"}),
    ("echokardio", {"results_imaging"}), ("ekg", {"results_imaging"}), ("ct", {"results_imaging"}),
    ("sonograph", {"results_imaging"}), ("ultraschall", {"results_imaging"}),
    ("duplex", {"results_imaging"}), ("hirnversorgend", {"results_imaging"}),
    ("radiolog", {"results_imaging"}), ("gesamtbeurteilung", {"results_imaging"}),
    ("befundzusammenfassung", {"results_imaging", "problems"}), ("augenkonsil", {"results_imaging", "problems"}),
    ("erhobene befunde", {"vital_signs", "results_imaging"}), ("befunde", {"vital_signs", "results_imaging"}),
    ("vitalparameter", {"vital_signs"}), ("rr bei", {"vital_signs"}), ("interpretation", {"vital_signs"}),
    ("status", {"functional_status", "vital_signs"}),
    ("groesse", {"vital_signs"}), ("gewicht", {"vital_signs"}), ("bmi", {"vital_signs"}),
    ("temperatur", {"vital_signs"}), ("hf", {"vital_signs"}), ("rr", {"vital_signs"}),
    ("mmse", {"functional_status"}), ("ventrikelfunktion", {"results_imaging"}),
]
DOC_TYPE_DOMAINS = [
    ("histo", {"results_pathology"}), ("radiolog", {"results_imaging"}), ("sono", {"results_imaging"}),
    ("ekg", {"results_imaging"}), ("rr-messung", {"vital_signs", "results_imaging"}),
    ("augen", {"results_imaging", "problems"}),
]
SCORED_KINDS = {"sentence", "field", "table_row"}


def _domains_for(text: str, rules) -> set[str]:
    t = normalize(text)
    out: set[str] = set()
    for key, doms in rules:
        if re.search(rf"(^|\s){re.escape(key)}", t):
            out |= doms
    return out


def _pattern(raw: str) -> tuple[str, bool, bool]:
    raw = raw.strip()
    open_end = raw.endswith("*")
    pat = normalize(raw.strip("*"))
    open_start = len(pat) >= 6 and " " not in pat  # find long terms inside German compounds
    return pat, open_end or open_start, open_start


def _tokens(norm: str) -> list[str]:
    return norm.split(" ") if norm else []


def _token_index(norm: str, char_pos: int) -> int:
    return norm.count(" ", 0, char_pos)


def _polarity(norm: str, raw: str, label_section: str, term_spans: list[tuple[int, int]]) -> str:
    toks = _tokens(norm)
    ls = normalize(label_section)
    if "fragestellung" in ls or "?" in raw:
        return "uncertain"
    for start, end in term_spans or [(0, 0)]:
        ti, te = _token_index(norm, start), _token_index(norm, end)
        pre = " ".join(toks[max(0, ti - 5):ti]) if term_spans else " ".join(toks[:3])
        post = " ".join(toks[te:te + 4]) if term_spans else ""
        pre_set = set(pre.split())
        if pre_set & NEG_PRE or any(p in post for p in NEG_POST):
            return "negated"
        if pre_set & UNCERTAIN:
            return "uncertain"
        if any(p in pre for p in PAST) or (not term_spans and any(norm.startswith(p) for p in PAST)):
            return "past"
    if any(re.search(rf"(^|\s){re.escape(p)}(\s|$)", norm) for p in PLANNED) or "procedere" in ls:
        return "planned"
    return "affirmed"


def _sides(norm: str) -> list[str]:
    toks = set(_tokens(norm))
    return sorted(side for side, words in SIDES.items() if toks & words)


@dataclass
class _Seg:
    seg: Segment
    norm: str
    tokens: set[str]
    domains: set[str]
    nodes: set[int]
    codes: set[str]
    sides: list[str]
    polarity: str  # segment-level, for pairs without a term hit
    group: int = -1  # near-duplicate group


# ---------------------------------------------------------------------------
# IBM extraction as a code index
# ---------------------------------------------------------------------------
def _ibm_mentions(patient_dir: Path):
    """Yield (doc_id, normalised mention text, code, status) from diagnoses and medication."""
    for name in ("diagnoses.json", "medication.json"):
        path = patient_dir / name
        if not path.exists():
            continue
        tree = json.loads(path.read_text(encoding="utf-8"))

        def walk(node, code=None, status=None):
            code = (node.get("code") or {}).get("value") or code
            status = node.get("status") or status
            if "documentIds" in node and "values" not in node:
                text = re.sub(r"<SPAN[^>]*>|</SPAN>", "", node.get("text", ""))
                text = normalize(re.sub(r"&\w+;", " ", text))
                for doc in node["documentIds"]:
                    if code and text:
                        yield doc, text, code, status or "positive"
                return
            for child in node.get("values", []) or []:
                yield from walk(child, code, status)

        for top in tree.get("values", []):
            yield from walk(top)


def configure_for_patient(patient_dir: Path) -> None:
    """Point the outbound gate at this patient's identifiers (name, birth date, IDs,
    facilities) so nothing of them reaches a cloud model."""
    patient, docs = {}, []
    try:
        patient = json.loads((patient_dir / "patient.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    try:
        docs = json.loads((patient_dir / "documents.json").read_text(encoding="utf-8")).get("documents", [])
    except (OSError, json.JSONDecodeError):
        pass
    configure_outbound(Deidentifier.for_patient(patient, docs))


@dataclass
# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------
class RemarkerIndex:
    patient_id: str
    docs: dict[str, dict]
    segs: list[_Seg]
    item_ids: list[str]
    base: np.ndarray                    # items x segments, ridx before query-time signals
    signals: dict[str, np.ndarray]      # name -> items x segments
    matched: dict[tuple[int, int], list[str]]
    pair_polarity: dict[tuple[int, int], str]
    seg_vectors: np.ndarray | None
    dense_lo: float
    dense_hi: float
    contradictions: list[ContradictionCandidate]
    term_df: dict[str, int]
    build_info: dict = field(default_factory=dict)

    # --- build -------------------------------------------------------------------
    @classmethod
    def build(cls, patient_dir: Path, tree: DecisionTree, embedder: GeminiEmbedder | None = None,
              reranker: JinaReranker | None = None) -> "RemarkerIndex":
        t0 = time.perf_counter()
        info: dict = {"issues": []}
        patient = json.loads((patient_dir / "patient.json").read_text(encoding="utf-8"))
        documents = load_documents(patient_dir)
        docs = {d.doc_id: {"title": d.title, "type": d.doc_type,
                           "date": d.date.isoformat() if d.date else None, "text": d.text}
                for d in documents}

        segs: list[_Seg] = []
        for d in documents:
            doc_domains = _domains_for(d.doc_type + " " + d.title, DOC_TYPE_DOMAINS)
            for s in segment_document(d):
                norm = normalize(s.text)
                if norm.startswith("applikation mo mi ab na"):
                    s.kind = "boilerplate"  # the medication table header, never evidence
                doms = _domains_for(s.section, SECTION_DOMAINS) | _domains_for(s.label, SECTION_DOMAINS)
                segs.append(_Seg(s, norm, set(_tokens(norm)), doms or set(doc_domains), set(), set(),
                                 _sides(norm), _polarity(norm, s.text, s.label + " " + s.section, [])))

        # decision-graph nodes mentioned in each segment (same automaton as the prompt matcher)
        for sg in segs:
            for _, _, pid in tree.automaton.find(sg.norm):
                kind, idx = tree.automaton.patterns[pid][3]
                if kind == "node":
                    sg.nodes.add(idx)

        # IBM codes, located by their mention text
        by_doc: dict[str, list[_Seg]] = {}
        for sg in segs:
            by_doc.setdefault(sg.seg.doc_id, []).append(sg)
        for doc, text, code, status in _ibm_mentions(patient_dir):
            if status == "negative":
                continue
            for sg in by_doc.get(doc, []):
                if text in sg.norm:
                    sg.codes.add(code)

        # near-duplicates and contradiction candidates
        contradictions = _near_duplicates(segs) + _allergy_conflicts(segs)

        # lexical: one automaton over all item terms
        items = tree.items
        auto = Automaton()
        item_patterns: dict[int, set[str]] = {}
        for i, it in enumerate(items):
            for key, terms in it["terms"].items():
                for raw in terms:
                    pat, open_end, open_start = _pattern(raw)
                    if len(pat) >= 2:
                        auto.add(pat, open_end, i, open_start)
                        item_patterns.setdefault(i, set()).add(pat)
        auto.build()
        scored = [k for k, sg in enumerate(segs) if sg.seg.kind in SCORED_KINDS]
        hits: dict[tuple[int, int], dict[str, tuple[int, int]]] = {}
        term_df: dict[str, int] = {}
        for k in scored:
            seen = set()
            for start, end, pid in auto.find(segs[k].norm):
                pat, _, _, i = auto.patterns[pid]
                hits.setdefault((i, k), {}).setdefault(pat, (start, end))
                seen.add(pat)
            for pat in seen:
                term_df[pat] = term_df.get(pat, 0) + 1
        n = max(IDF_MIN_PASSAGES, len(scored))

        def idf(pat):
            df = term_df.get(pat, 0)
            return math.log(1 + (n - df + 0.5) / (df + 0.5))

        I, S = len(items), len(segs)
        lexical = np.zeros((I, S), np.float32)
        matched: dict[tuple[int, int], list[str]] = {}
        pair_pol: dict[tuple[int, int], str] = {}
        for (i, k), pats in hits.items():
            lexical[i, k] = 1 - math.exp(-sum(idf(p) for p in pats) / LEXICAL_SCALE)
            matched[(i, k)] = sorted(pats)
            sg = segs[k]
            pair_pol[(i, k)] = _polarity(sg.norm, sg.seg.text, sg.seg.label + " " + sg.seg.section,
                                         sorted(pats.values()))

        # a line listed under a header that names the item ("Diagnosen:", "Allergien:", "Labor:") is
        # evidence for it even when the line itself never repeats the word; the section must also fit
        # the item's domains, so a "Diagnosen" header cannot make a drug item match
        header_items: dict[str, set[int]] = {}
        for k in scored:
            head = segs[k].seg.section
            if not head:
                continue
            if head not in header_items:
                header_items[head] = {auto.patterns[pid][3] for _, _, pid in auto.find(normalize(head))}
            for i in header_items[head]:
                if lexical[i, k] < HEADER_LEXICAL and set(items[i]["domains"]) & segs[k].domains:
                    lexical[i, k] = HEADER_LEXICAL
                    pair_pol.setdefault((i, k), segs[k].polarity)

        code = np.zeros((I, S), np.float32)
        section = np.zeros((I, S), np.float32)
        for i, it in enumerate(items):
            prefixes = [p for v in (it.get("codes") or {}).values() for p in v]
            doms = set(it["domains"])
            for k in scored:
                sg = segs[k]
                if prefixes and any(c.startswith(p) for c in sg.codes for p in prefixes):
                    code[i, k] = 1.0
                if doms & sg.domains:
                    section[i, k] = 1.0

        # dense
        dense = np.zeros((I, S), np.float32)
        seg_vectors = None
        lo = hi = 0.0
        if embedder is not None:
            try:
                seg_texts = [_embed_text(docs[sg.seg.doc_id]["title"], sg.seg) for sg in segs]
                seg_vectors = embedder.embed(seg_texts, "RETRIEVAL_DOCUMENT", wait_on_quota=True)
                item_vectors = embedder.embed([_item_text(it) for it in items], "RETRIEVAL_QUERY",
                                               wait_on_quota=True)
                cos = item_vectors @ seg_vectors.T
                vals = cos[:, scored].ravel()
                lo, hi = float(np.percentile(vals, DENSE_LOW_PCT)), float(np.percentile(vals, DENSE_HIGH_PCT))
                dense = np.clip((cos - lo) / max(hi - lo, 1e-6), 0, 1).astype(np.float32)
                info["embed_calls"] = embedder.calls
            except EmbeddingError as e:
                info["issues"].append(f"Dense search unavailable: {e}")
        else:
            info["issues"].append("Dense search disabled.")
        mask = np.zeros(S, bool)
        mask[scored] = True
        dense[:, ~mask] = 0

        # rerank each item's top candidates
        rerank = np.zeros((I, S), np.float32)
        if reranker is not None:
            pre = np.maximum.reduce([lexical, dense, code])
            try:
                for i, it in enumerate(items):
                    cand = [k for k in np.argsort(-pre[i])[:RERANK_CANDIDATES] if pre[i, k] > 0]
                    if not cand:
                        continue
                    texts = [_embed_text(docs[segs[k].seg.doc_id]["title"], segs[k].seg) for k in cand]
                    for k, s in zip(cand, reranker.scores(_item_text(it), texts)):
                        rerank[i, k] = min(1.0, max(0.0, (s - RERANK_LOW) / RERANK_SPAN))
                info["rerank_calls"] = reranker.calls
            except EmbeddingError as e:
                info["issues"].append(f"Reranker unavailable: {e}")

        base = 1 - ((1 - W_LEXICAL * lexical) * (1 - W_DENSE * dense)
                    * (1 - W_RERANK * rerank) * (1 - W_CODE * code))
        base = base + (1 - base) * W_SECTION * section * np.minimum(1.0, 2 * base)
        base[:, ~mask] = 0

        info["build_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        info["segments"] = S
        return cls(patient["id"], docs, segs, [it["id"] for it in items], base.astype(np.float32),
                   {"lexical": lexical, "dense": dense, "rerank": rerank, "code": code, "section": section},
                   matched, pair_pol, seg_vectors, lo, hi, contradictions, term_df, info)

    # --- persistence -----------------------------------------------------------------
    @staticmethod
    def fingerprint(patient_dir: Path, tree: DecisionTree, dense: bool, rerank: bool) -> str:
        h = hashlib.sha1(INDEX_VERSION.encode())
        here = Path(__file__).resolve().parent
        for src in ("remarker.py", "segmenter.py"):  # code changes invalidate the index
            h.update((here / src).read_bytes())
        for f in sorted((patient_dir / "documents").glob("*.json")):
            h.update(f.read_bytes())
        for name in ("diagnoses.json", "medication.json", "patient.json"):
            if (patient_dir / name).exists():
                h.update((patient_dir / name).read_bytes())
        h.update(json.dumps(tree.items, sort_keys=True).encode())
        h.update(json.dumps(sorted(tree.node_index.items())).encode())
        h.update(f"{dense}{rerank}{os.environ.get('EMBED_MODEL', '')}".encode())
        return h.hexdigest()[:16]

    def save(self, folder: Path, fingerprint: str) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        meta = {
            "fingerprint": fingerprint, "patient_id": self.patient_id, "docs": self.docs,
            "item_ids": self.item_ids,
            "segs": [{"seg": sg.seg.model_dump(mode="json"), "norm": sg.norm, "domains": sorted(sg.domains),
                      "nodes": sorted(sg.nodes), "codes": sorted(sg.codes), "sides": sg.sides,
                      "polarity": sg.polarity, "group": sg.group} for sg in self.segs],
            "matched": [[i, k, v] for (i, k), v in self.matched.items()],
            "pair_polarity": [[i, k, v] for (i, k), v in self.pair_polarity.items()],
            "dense_lo": self.dense_lo, "dense_hi": self.dense_hi,
            "contradictions": [c.model_dump() for c in self.contradictions],
            "term_df": self.term_df, "build_info": self.build_info,
        }
        vault.write_text(folder / "index.json", json.dumps(meta, ensure_ascii=False))
        arrays = {"base": self.base, **{f"sig_{k}": v for k, v in self.signals.items()}}
        if self.seg_vectors is not None:
            arrays["seg_vectors"] = self.seg_vectors
        vault.write_npz(folder / "arrays.npz", **arrays)

    @classmethod
    def load(cls, folder: Path, fingerprint: str | None = None) -> "RemarkerIndex | None":
        if not (folder / "index.json").exists():
            return None
        try:
            meta = json.loads(vault.read_text(folder / "index.json"))
        except (vault.VaultError, json.JSONDecodeError):
            return None  # another key or a damaged file: rebuild
        if fingerprint and meta.get("fingerprint") != fingerprint:
            return None
        arrays = vault.read_npz(folder / "arrays.npz")
        segs = []
        for s in meta["segs"]:
            seg = Segment(**s["seg"])
            segs.append(_Seg(seg, s["norm"], set(_tokens(s["norm"])), set(s["domains"]), set(s["nodes"]),
                             set(s["codes"]), s["sides"], s["polarity"], s["group"]))
        return cls(meta["patient_id"], meta["docs"], segs, meta["item_ids"], arrays["base"],
                   {k[4:]: arrays[k] for k in arrays.files if k.startswith("sig_")},
                   {(i, k): v for i, k, v in meta["matched"]},
                   {(i, k): v for i, k, v in meta["pair_polarity"]},
                   arrays["seg_vectors"] if "seg_vectors" in arrays.files else None,
                   meta["dense_lo"], meta["dense_hi"],
                   [ContradictionCandidate(**c) for c in meta["contradictions"]],
                   meta["term_df"], meta["build_info"])


def _embed_text(title: str, seg: Segment) -> str:
    head = f"{title} - {seg.section}: " if seg.section else f"{title}: "
    return head + " ".join(seg.text.split())


def _item_text(item: dict) -> str:
    de = [t.rstrip("*") for t in item["terms"].get("de", [])][:10]
    return (f"{item['label']['en']} / {item['label']['de']}. {item['question']} "
            f"Suchbegriffe: {', '.join(de)}")


def _same_encounter(a: Segment, b: Segment) -> bool:
    if a.doc_id == b.doc_id:
        return True
    if a.doc_date and b.doc_date:
        return abs(a.doc_date.toordinal() - b.doc_date.toordinal()) <= 21
    return False


def _near_duplicates(segs: list[_Seg]) -> list[ContradictionCandidate]:
    """Group near-identical passages; report pairs that differ in a side or a number."""
    idx = [k for k, sg in enumerate(segs) if sg.seg.kind in SCORED_KINDS and len(sg.tokens) >= 5]
    parent = {k: k for k in idx}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    side_words = {w: s for s, ws in SIDES.items() for w in ws}
    out: list[ContradictionCandidate] = []
    seen_pairs = set()
    for a_pos, a in enumerate(idx):
        ta = segs[a].tokens
        for b in idx[a_pos + 1:]:
            tb = segs[b].tokens
            inter = len(ta & tb)
            if not inter:
                continue
            jac = inter / len(ta | tb)
            if jac < 0.6:
                continue
            diff = (ta ^ tb)
            sa = {side_words[w] for w in ta - tb if w in side_words} - {"both"}
            sb = {side_words[w] for w in tb - ta if w in side_words} - {"both"}
            nums_a = {w for w in ta - tb if re.fullmatch(r"\d+([.,]\d+)?", w)}
            nums_b = {w for w in tb - ta if re.fullmatch(r"\d+([.,]\d+)?", w)}
            kind = None
            if sa and sb and sa != sb:
                kind = "laterality"
            elif nums_a and nums_b and jac >= 0.75:
                kind = "number"
            if kind == "number" and not _same_encounter(segs[a].seg, segs[b].seg):
                kind = None  # a value that changed between stays is not a contradiction
                continue
            if kind:
                key = (segs[a].seg.doc_id, segs[b].seg.doc_id, kind, tuple(sorted(diff))[:6])
                if key not in seen_pairs:
                    seen_pairs.add(key)
                    out.append(ContradictionCandidate(
                        segment_ids=[segs[a].seg.segment_id, segs[b].seg.segment_id],
                        doc_ids=[segs[a].seg.doc_id, segs[b].seg.doc_id],
                        differing=sorted(w for w in diff if w in side_words or w in nums_a | nums_b),
                        kind=kind))
            elif jac >= 0.85 and not (sa or sb or nums_a or nums_b):
                parent[find(a)] = find(b)  # same passage, nothing differs that matters
    for k in idx:
        segs[k].group = find(k)
    return out


# "no known allergies" (normalised text) and a documented allergy
ALLERGY_NONE = re.compile(r"\b(allergi\w*|unvertraeglichkeit\w*) (keine|nicht) (bekannt|bekannte|vorhanden|dokumentiert)"
                          r"|\bkeine (bekannten )?(allergi|unvertraeglichkeit)|\bnkda\b|\bno known (drug )?allerg")
ALLERGY_TERM = re.compile(r"(allergi|unvertraeglichkeit)")


def _allergy_conflicts(segs: list[_Seg]) -> list[ContradictionCandidate]:
    """A later passage says no allergies are known although an earlier one records an allergy.

    An allergy does not go away, so this is a status contradiction whatever happened in between;
    the reverse order (none, then a new allergy) is not reported. One candidate per document pair.
    """
    none, present = [], []
    for sg in segs:
        if sg.seg.kind not in SCORED_KINDS:
            continue
        text = normalize(f"{sg.seg.label} {sg.seg.text}")
        if ALLERGY_NONE.search(text):
            none.append(sg)
        elif ALLERGY_TERM.search(text) and sg.polarity not in ("negated", "uncertain"):
            present.append(sg)
    out, seen = [], set()
    for n in none:
        for p in present:
            if n.seg.doc_id == p.seg.doc_id or (n.seg.doc_id, p.seg.doc_id) in seen:
                continue
            if n.seg.doc_date and p.seg.doc_date and n.seg.doc_date < p.seg.doc_date:
                continue
            seen.add((n.seg.doc_id, p.seg.doc_id))
            when = lambda s: s.seg.doc_date.isoformat() if s.seg.doc_date else "undated"
            out.append(ContradictionCandidate(
                segment_ids=[p.seg.segment_id, n.seg.segment_id], doc_ids=[p.seg.doc_id, n.seg.doc_id],
                differing=[], kind="status", status="accepted",
                explanation=(f"Document {n.seg.doc_id} ({when(n)}) states that no allergies are known, but document "
                             f"{p.seg.doc_id} ({when(p)}) records an allergy: \"{' '.join(p.seg.text.split())[:80]}\".")))
    return out


# ---------------------------------------------------------------------------
# Online
# ---------------------------------------------------------------------------
class Remarker:
    def __init__(self, index: RemarkerIndex, tree: DecisionTree, embedder: GeminiEmbedder | None = None):
        self.evidence: EvidenceLayer | None = None
        self.evidence_issue: str | None = None
        self._fact_segments: dict[int, list] = {}
        self.ix = index
        self.tree = tree
        self.embedder = embedder
        self.item_pos = {iid: i for i, iid in enumerate(index.item_ids)}
        self.seg_dates = np.array([_ordinal(sg.seg.doc_date) for sg in index.segs])
        self.n_scored = sum(1 for sg in index.segs if sg.seg.kind in SCORED_KINDS)

    @classmethod
    def for_patient(cls, patient_dir: Path, tree: DecisionTree | None = None, dense: bool = True,
                    rerank: bool = False, rebuild: bool = False, evidence=True) -> "Remarker":
        """Defaults = the best measured configuration: lexical + embeddings, no reranker.
        The reranker passed the same 18 checks with more noise and 44 extra API calls."""
        tree = tree or DecisionTree.load()
        configure_for_patient(patient_dir)
        fp = RemarkerIndex.fingerprint(patient_dir, tree, dense, rerank)
        folder = CACHE_DIR / "remarker" / patient_dir.name / fp
        index = None if rebuild else RemarkerIndex.load(folder, fp)
        embedder = None
        if dense:
            try:
                embedder = GeminiEmbedder()
            except EmbeddingError:
                embedder = None
        if index is None:
            reranker = None
            if rerank:
                try:
                    reranker = JinaReranker()
                except EmbeddingError:
                    reranker = None
            index = RemarkerIndex.build(patient_dir, tree, embedder, reranker)
            index.save(folder, fp)
        rm = cls(index, tree, embedder)
        rm.attach_evidence(patient_dir, evidence)
        return rm

    def attach_evidence(self, patient_dir: Path, evidence=None) -> None:
        """Blocks 1-4: `evidence` is a (bundle, history) pair, True to load the handoff
        package for this patient, or None/False to run without facts."""
        self.evidence: EvidenceLayer | None = None
        self.evidence_issue: str | None = None
        if not evidence:
            return
        try:
            bundle, history = evidence if isinstance(evidence, tuple) else load_bundle(self.ix.patient_id)
            layer = build_layer(bundle, history, {d: v["text"] for d, v in self.ix.docs.items()},
                                [sg.seg for sg in self.ix.segs])
        except BundleError as e:
            self.evidence_issue = f"Evidence package not used: {e}"
            return
        self.evidence = layer
        # facts decide polarity and sides where our regexes only guessed
        seg_pos = {sg.seg.segment_id: k for k, sg in enumerate(self.ix.segs)}
        self._fact_segments: dict[int, list] = {}
        for sid, fids in layer.by_segment.items():
            k = seg_pos.get(sid)
            if k is not None:
                self._fact_segments[k] = [layer.facts[f] for f in fids]

    # ----------------------------------------------------------------------------
    def remark(self, plan: QueryPlan) -> RemarkerResult:
        t0 = time.perf_counter()
        ix = self.ix
        issues = list(ix.build_info.get("issues", []))
        api_calls = 0
        as_of = plan.as_of or max((date.fromisoformat(d["date"]) for d in ix.docs.values() if d["date"]),
                                  default=None)
        too_new = self.seg_dates > _ordinal(as_of) if as_of else np.zeros(len(ix.segs), bool)

        # context: segments that mention the request's context / concept nodes
        ctx_nodes = {self.tree.node_index[h.node_id] for h in plan.nodes
                     if h.kind in ("context", "concept") and h.node_id in self.tree.node_index}
        ctx = np.array([1.0 if sg.nodes & ctx_nodes else 0.0 for sg in ix.segs], np.float32)

        # LLM-added terms, one small automaton for all items of this plan
        llm_lex = self._llm_terms(plan)

        items: list[ItemEvidence] = []
        for entry in plan.checklist.entries:
            i = self.item_pos.get(entry.item_id)
            if i is None:
                continue
            row = ix.base[i].copy()
            extra = {}
            if entry.item_id in CONTEXTUAL_ITEMS and ctx_nodes:
                row = 1 - (1 - row) * (1 - W_CONTEXT * ctx)
                extra["context"] = ctx
            if entry.item_id in llm_lex:
                row = 1 - (1 - row) * (1 - W_LLM_TERMS * llm_lex[entry.item_id])
                extra["llm_terms"] = llm_lex[entry.item_id]
            if self._fact_segments:
                fact_vec = self._fact_vector(entry.domains, i)
                fact_vec[row < FACT_MIN_BASE] = 0  # a fact confirms a match, it never creates one
                if fact_vec.any():
                    row = 1 - (1 - row) * (1 - W_FACT * fact_vec)
                    extra["fact"] = fact_vec
            row[too_new] = 0
            items.append(self._evidence(entry.item_id, entry.label, entry.priority, entry.time_rule,
                                        row, i, extra))
        self._apply_completion_rules(items)

        custom: list[ItemEvidence] = []
        if plan.custom_questions:
            custom, calls, err = self._custom(plan, too_new)
            api_calls += calls
            if err:
                issues.append(err)

        records = self._records(items + custom, plan)
        # which of this request's items each contradiction concerns (by the base scores of its
        # passages), so later steps can tell a relevant conflict from one about something else
        seg_pos = {sg.seg.segment_id: k for k, sg in enumerate(ix.segs)}
        contradictions = []
        for c in ix.contradictions:
            ks = [seg_pos[s] for s in c.segment_ids if s in seg_pos]
            rel = [e.item_id for e in plan.checklist.entries
                   if ks and e.item_id in self.item_pos
                   and max(float(ix.base[self.item_pos[e.item_id], k]) for k in ks) >= FLAG_THRESHOLD]
            contradictions.append(c.model_copy(update={"items": rel}))
        derived: list[DerivedValue] = []
        if self.evidence:
            seen = {(tuple(sorted(c.doc_ids)), c.kind) for c in contradictions}
            for c in self.evidence.contradictions:
                key = (tuple(sorted(c.doc_ids)), c.kind)
                if key in seen and c.status != "accepted":
                    continue  # our near-duplicate detector already has this candidate
                ks = [seg_pos[s] for s in c.segment_ids if s in seg_pos]
                rel = [e.item_id for e in plan.checklist.entries
                       if ks and e.item_id in self.item_pos
                       and max(float(ix.base[self.item_pos[e.item_id], k]) for k in ks) >= FLAG_THRESHOLD]
                contradictions = [x for x in contradictions if not (key == (tuple(sorted(x.doc_ids)), x.kind)
                                                                     and c.status == "accepted")]
                contradictions.append(ContradictionCandidate(
                    segment_ids=c.segment_ids, doc_ids=c.doc_ids, differing=[], kind=c.kind,
                    items=rel, status=c.status, explanation=c.explanation, source="evidence_bundle"))
            item_ids = {e.item_id for e in plan.checklist.entries}
            for d in self.evidence.derived:
                rel = [i for i in DERIVED_ITEMS.get(d.concept, []) if i in item_ids]
                derived.append(DerivedValue(id=d.id, concept=d.concept, label=d.label, value=d.value, unit=d.unit,
                                            explanation=d.explanation, segment_ids=d.segment_ids,
                                            doc_ids=d.doc_ids, items=rel))
            if self.evidence.status != "complete":
                issues.append("Evidence package is marked partial; full-text search covered all documents anyway.")
        elif self.evidence_issue:
            issues.append(self.evidence_issue)
        coverage = {"documents": len(ix.docs), "segments_searched": int(sum(1 for sg in ix.segs if sg.seg.kind in SCORED_KINDS)),
                    "dense_search": ix.seg_vectors is not None,
                    "evidence_version": self.evidence.version if self.evidence else None,
                    "verified_facts": len(self.evidence.facts) if self.evidence else 0}
        result = RemarkerResult(patient_id=ix.patient_id, as_of=as_of, items=items, custom=custom,
                                records=records, contradictions=contradictions, api_calls=api_calls,
                                timings_ms={"remark": round((time.perf_counter() - t0) * 1000, 2)},
                                issues=issues, derived=derived, coverage=coverage)
        return result

    # ----------------------------------------------------------------------------
    def _fact_vector(self, domains, i: int) -> np.ndarray:
        """1.0 where a verified fact that fits the item sits in the segment."""
        v = np.zeros(len(self.ix.segs), np.float32)
        for k, facts in self._fact_segments.items():
            if any(self._fact_fits(f, domains, i, k) for f in facts):
                v[k] = 1.0
        return v

    def _fact_fits(self, fact, domains, i: int | None, k: int) -> bool:
        """A fact fits an item when their domains overlap and either the fact's kind is the
        item's kind (drug for a medication item, ...) or the item's matched terms occur in
        the fact's label. A diagnosis fact alone does not make every problem item match."""
        wanted = set(domains)
        if not (fact.domains & wanted):
            return False
        kinds = FACT_KIND_DOMAINS.get(fact.kind, set())
        if kinds & wanted:
            return True
        if i is None:
            return False
        label = normalize(fact.label + " " + fact.summary + " " + fact.concept.replace("_", " "))
        terms = self.ix.matched.get((i, k), [])
        return any(t and t in label for t in terms)

    def _llm_terms(self, plan: QueryPlan) -> dict[str, np.ndarray]:
        wanted = {e.item_id: e.terms.get("llm") for e in plan.checklist.entries if e.terms.get("llm")}
        if not wanted:
            return {}
        auto = Automaton()
        for iid, terms in wanted.items():
            for raw in terms:
                pat, open_end, open_start = _pattern(raw)
                if len(pat) >= 2:
                    auto.add(pat, open_end, iid, open_start)
        auto.build()
        n = max(1, self.n_scored)
        out: dict[str, np.ndarray] = {}
        found: dict[str, dict[int, set[str]]] = {}
        df: dict[str, int] = {}
        for k, sg in enumerate(self.ix.segs):
            if sg.seg.kind not in SCORED_KINDS:
                continue
            seen = set()
            for _, _, pid in auto.find(sg.norm):
                pat, _, _, iid = auto.patterns[pid]
                found.setdefault(iid, {}).setdefault(k, set()).add(pat)
                seen.add(pat)
            for p in seen:
                df[p] = df.get(p, 0) + 1
        for iid, segs in found.items():
            v = np.zeros(len(self.ix.segs), np.float32)
            for k, pats in segs.items():
                s = sum(math.log(1 + (n - df[p] + 0.5) / (df[p] + 0.5)) for p in pats)
                v[k] = 1 - math.exp(-s / LEXICAL_SCALE)
            out[iid] = v
        return out

    def _evidence(self, item_id, label, priority, time_rule, row, i, extra) -> ItemEvidence:
        ix = self.ix
        order = [k for k in np.argsort(-row) if row[k] >= FLAG_THRESHOLD][:MAX_FLAGS * 3]
        # within a duplicate group, the copy from the newest document represents the group
        newest: dict[int, int] = {}
        for k in order:
            g = ix.segs[k].group
            if g >= 0 and (g not in newest or self.seg_dates[k] > self.seg_dates[newest[g]]):
                newest[g] = k
        order = sorted(order, key=lambda k: (ix.segs[k].group < 0 or newest.get(ix.segs[k].group) != k,
                                             -row[k]))
        order = sorted(order, key=lambda k: -max(row[j] for j in order
                                                 if ix.segs[j].group >= 0 and ix.segs[j].group == ix.segs[k].group)
                       if ix.segs[k].group >= 0 else -row[k])
        flags: list[Flag] = []
        groups: dict[int, Flag] = {}
        for k in order:
            sg = ix.segs[k]
            pol = ix.pair_polarity.get((i, k), sg.polarity) if i is not None else sg.polarity
            if sg.group >= 0 and sg.group in groups:
                groups[sg.group].duplicates.append(sg.seg.segment_id)
                continue
            signals = {name: round(float(m[i, k]), 3) for name, m in ix.signals.items()
                       if i is not None and m[i, k] > 0}
            for name, v in extra.items():
                if v[k] > 0:
                    signals[name] = round(float(v[k]), 3)
            fact_ids, structured, sides = [], None, sg.sides
            wanted = set(self.tree.items[i]["domains"]) if i is not None else set()
            for fc in self._fact_segments.get(k, []):
                if i is None or not self._fact_fits(fc, wanted, i, k):
                    continue
                fact_ids.append(fc.id)
                if structured is None:
                    structured = {"kind": fc.kind, "concept": fc.concept, "label": fc.label,
                                  "summary": fc.summary, **fc.structured}
                    pol = fc.polarity
                    if fc.sides:
                        sides = fc.sides
            f = Flag(segment_id=sg.seg.segment_id, doc_id=sg.seg.doc_id, start=sg.seg.start,
                     end=sg.seg.end, text=sg.seg.text, section=sg.seg.section, doc_date=sg.seg.doc_date,
                     ridx=round(float(row[k]), 3), signals=signals,
                     matched_terms=ix.matched.get((i, k), []) if i is not None else [],
                     polarity=pol, sides=sides, fact_ids=fact_ids, structured=structured)
            if sg.group >= 0:
                groups[sg.group] = f
            flags.append(f)
            if len(flags) >= MAX_FLAGS:
                break

        excluded = NOT_EVIDENCE.get(item_id, set())
        evidence = [f for f in flags if f.polarity not in excluded]
        if time_rule in ("current", "latest"):
            positive = [f for f in evidence if f.polarity in ("affirmed", "past", "planned")]
            newest = max((f.doc_date for f in positive if f.doc_date), default=None)
            if newest:
                for f in evidence:
                    f.current = f.doc_date is None or f.doc_date >= newest
                flags.sort(key=lambda f: (not f.current, -f.ridx))
        if any(f.polarity in ("affirmed", "past", "planned") for f in evidence):
            status = "found"
        elif any(f.polarity == "negated" for f in evidence):
            status = "documented_absent"
        elif evidence:
            status = "uncertain"
        elif ix.seg_vectors is None and not any(ix.signals["lexical"][i] > 0) if i is not None else False:
            status = "processing_incomplete"
        else:
            status = "not_documented"
        return ItemEvidence(item_id=item_id, label=label, priority=priority, status=status, flags=flags)

    def _apply_completion_rules(self, items: list[ItemEvidence]) -> None:
        by_id = {e.item_id: e for e in items}
        for done_id, rec_id in COMPLETES.items():
            done = by_id.get(done_id)
            if not done:
                continue
            rec = by_id.get(rec_id)
            rec_dates = [f.doc_date for f in (rec.flags if rec else []) if f.doc_date]
            if not rec_dates and rec_id in self.item_pos:
                i = self.item_pos[rec_id]
                rec_dates = [self.ix.segs[k].seg.doc_date for k in np.where(self.ix.base[i] >= FLAG_THRESHOLD)[0]
                             if self.ix.segs[k].seg.doc_date]
            if rec_dates:
                cutoff = max(rec_dates)
                done.flags = [f for f in done.flags if f.doc_date and f.doc_date > cutoff]
            evidence = [f for f in done.flags if f.polarity not in NOT_EVIDENCE.get(done_id, set())]
            if not any(f.polarity in ("affirmed", "past") for f in evidence):
                done.status = "not_documented"
                done.note = "No record after the recommendation."

    def _custom(self, plan: QueryPlan, too_new) -> tuple[list[ItemEvidence], int, str | None]:
        ix = self.ix
        rows = []
        calls = 0
        err = None
        dense = None
        if self.embedder is not None and ix.seg_vectors is not None:
            try:
                before = self.embedder.calls
                q = self.embedder.embed([c.question + " " + ", ".join(c.search_terms_de)
                                         for c in plan.custom_questions], "RETRIEVAL_QUERY")
                calls = self.embedder.calls - before
                cos = q @ ix.seg_vectors.T
                dense = np.clip((cos - ix.dense_lo) / max(ix.dense_hi - ix.dense_lo, 1e-6), 0, 1)
            except EmbeddingError as e:
                err = f"Custom-question embedding failed: {e}"
        out = []
        for n, c in enumerate(plan.custom_questions):
            auto = Automaton()
            for raw in c.search_terms_de + c.search_terms_en:
                pat, open_end, open_start = _pattern(raw)
                if len(pat) >= 2:
                    auto.add(pat, open_end, n, open_start)
            auto.build()
            lex = np.zeros(len(ix.segs), np.float32)
            for k, sg in enumerate(ix.segs):
                if sg.seg.kind in SCORED_KINDS:
                    pats = {auto.patterns[pid][0] for _, _, pid in auto.find(sg.norm)}
                    if pats:
                        lex[k] = 1 - math.exp(-sum(
                            math.log(1 + (self.n_scored + 0.5) / (ix.term_df.get(p, 0) + 0.5))
                            for p in pats) / LEXICAL_SCALE)
            row = 1 - (1 - W_LEXICAL * lex) * (1 - (W_DENSE * dense[n] if dense is not None else 0))
            row[too_new] = 0
            extra = {"lexical": lex}
            if dense is not None:
                extra["dense"] = dense[n].astype(np.float32)
            out.append(self._evidence(f"custom:{n + 1}", LocalizedText(en=c.question, de=c.question),
                                      c.priority, "history", row.astype(np.float32), None, extra))
        return out, calls, err

    def _records(self, evidence: list[ItemEvidence], plan: QueryPlan) -> list[RecordRelevance]:
        ix = self.ix
        total = sum(PRIORITY_WEIGHT[e.priority] for e in evidence) or 1.0
        per_doc: dict[str, dict] = {d: {"score": 0.0, "labels": {}, "flags": []} for d in ix.docs}
        for e in evidence:
            best: dict[str, float] = {}
            for f in e.flags:
                for doc in {f.doc_id} | {s.split("#")[0] for s in f.duplicates}:
                    best[doc] = max(best.get(doc, 0), f.ridx)
                    per_doc[doc]["labels"][e.item_id] = per_doc[doc]["labels"].get(e.item_id, 0) + 1
                per_doc[f.doc_id]["flags"].append((f.ridx * PRIORITY_WEIGHT[e.priority], f.segment_id))
            for doc, r in best.items():
                per_doc[doc]["score"] += PRIORITY_WEIGHT[e.priority] * r
        out = []
        for doc, v in per_doc.items():
            meta = ix.docs[doc]
            top = [s for _, s in sorted(v["flags"], reverse=True)]
            out.append(RecordRelevance(
                doc_id=doc, title=meta["title"], doc_type=meta["type"],
                date=date.fromisoformat(meta["date"]) if meta["date"] else None,
                score=round(100 * v["score"] / total, 1), label_counts=v["labels"],
                top_flags=list(dict.fromkeys(top))[:3]))
        out.sort(key=lambda r: -r.score)
        return out


def _ordinal(d: date | None) -> int:
    return d.toordinal() if d else 0


def _main(argv: list[str]) -> int:
    from .prompt_analysis import PromptAnalyzer

    ap = argparse.ArgumentParser(prog="python -m app.remarker")
    ap.add_argument("command", choices=["build", "query"])
    ap.add_argument("prompt", nargs="?")
    ap.add_argument("--patient", type=Path, default=os.environ.get("PATIENT_DIR"))
    ap.add_argument("--no-dense", action="store_true")
    ap.add_argument("--rerank", action="store_true", help="add the Jina reranker (off by default)")
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args(argv)
    if not args.patient:
        print("Pass --patient <folder with patient.json and documents/> or set PATIENT_DIR.")
        return 2
    t = time.perf_counter()
    rm = Remarker.for_patient(args.patient, dense=not args.no_dense, rerank=args.rerank,
                              rebuild=args.rebuild or args.command == "build")
    load_ms = (time.perf_counter() - t) * 1000
    info = rm.ix.build_info
    print(f"index: {info.get('segments')} segments, build {info.get('build_ms')} ms, "
          f"embed calls {info.get('embed_calls', 0)}, rerank calls {info.get('rerank_calls', 0)}, "
          f"ready in {load_ms:.0f} ms; issues: {info.get('issues') or '-'}")
    if args.command == "build":
        return 0
    t = time.perf_counter()
    plan = PromptAnalyzer(rm.tree, None, "off").analyse(args.prompt or "")
    plan_ms = (time.perf_counter() - t) * 1000
    res = rm.remark(plan)
    for e in res.items:
        print(f"{e.priority:<8} {e.item_id:<28} {e.status:<18} "
              + "; ".join(f"{f.segment_id}({f.ridx:.2f},{f.polarity})" for f in e.flags[:3]))
    print("records:", ", ".join(f"{r.doc_id}={r.score:.0f}%" for r in res.records))
    print(f"contradiction candidates: {len(res.contradictions)}; plan {plan_ms:.1f} ms, "
          f"remark {res.timings_ms['remark']:.1f} ms, api calls {res.api_calls}")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
