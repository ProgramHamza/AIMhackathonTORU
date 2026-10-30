"""Bridge to blocks 1-4 (the evidence backend in ../blocks14).

The evidence backend prepares, per patient, a validated bundle: documents, passages,
facts with exact quotes and offsets, derived values (BMI, weight change), contradictions
(accepted or candidate) and processing gaps. This module loads that bundle, checks its
hashes, and maps every fact to our sentence-level segments by its quote, so the remarker
can use facts as a strong signal and the final step can show structured values.

Nothing here calls a model. If the bundle is missing or invalid, the pipeline runs without
it (full-text retrieval still covers all documents) and says so in `issues`.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
BLOCKS14 = ROOT / "blocks14"
HANDOFF_DIR = BLOCKS14 / "data" / "handoff"

# evidence-backend category -> our fact domains (tree.yaml `domains`)
CATEGORY_DOMAINS = {
    "diagnoses": {"problems"}, "symptoms": {"problems"}, "medical_history": {"past_problems"},
    "vitals": {"vital_signs"}, "laboratory": {"results_lab"}, "pathology": {"results_pathology"},
    "imaging": {"results_imaging"}, "functional_tests": {"results_imaging"},
    "medications": {"medications"}, "allergies": {"allergies", "alerts"},
    "procedures": {"procedures"}, "care_plans": {"plan_of_care"}, "followups": {"plan_of_care"},
    "encounters": {"encounters"}, "family_history": {"family_history"},
    "social_history": {"social_history"}, "other_clinical": set(), "demographics": set(),
}
# their contradiction kinds -> ours
KIND_MAP = {"laterality": "laterality", "numeric_inconsistency": "number", "event_date": "date",
            "status": "status", "other": "other"}


class BundleError(RuntimeError):
    pass


@dataclass
class FactLite:
    id: str
    category: str
    concept: str
    label: str
    kind: str                      # medication | measurement | allergy | assertion | event | attribute
    assertion: str                 # affirmed | negated | suspected | uncertain
    status: str                    # active | historical | ... | unknown
    laterality: str
    when: date | None
    summary: str                   # short rendered value, e.g. "Aspirin 100 mg oral 1-0-0-0"
    structured: dict
    quotes: list[tuple[str, int, int, str]] = field(default_factory=list)   # (doc_id, start, end, quote)
    segment_ids: list[str] = field(default_factory=list)
    method: str = "rule"
    related: list[str] = field(default_factory=list)

    @property
    def polarity(self) -> str:
        if self.assertion == "negated":
            return "negated"
        if self.assertion in ("suspected", "uncertain"):
            return "uncertain"
        if self.status in ("planned", "recommended"):
            return "planned"
        if self.status in ("historical", "resolved", "discontinued", "completed"):
            return "past"
        return "affirmed"

    @property
    def sides(self) -> list[str]:
        return {"left": ["left"], "right": ["right"], "bilateral": ["both"]}.get(self.laterality, [])

    @property
    def domains(self) -> set[str]:
        return set(CATEGORY_DOMAINS.get(self.category, set()))


@dataclass
class DerivedLite:
    id: str
    concept: str
    label: str
    value: float
    unit: str
    explanation: str
    input_fact_ids: list[str]
    segment_ids: list[str] = field(default_factory=list)
    doc_ids: list[str] = field(default_factory=list)


@dataclass
class ContradictionLite:
    id: str
    kind: str                      # our kinds
    status: str                    # accepted | candidate
    explanation: str
    doc_ids: list[str]
    segment_ids: list[str]
    quotes: list[str]
    claim_ids: list[str]


@dataclass
class EvidenceLayer:
    version: str
    status: str
    facts: dict[str, FactLite]
    by_segment: dict[str, list[str]]
    derived: list[DerivedLite]
    contradictions: list[ContradictionLite]
    latest_medication_fact_ids: set[str]
    gaps: list[dict]
    unmapped_quotes: int = 0

    def facts_for_segment(self, segment_id: str) -> list[FactLite]:
        return [self.facts[i] for i in self.by_segment.get(segment_id, [])]


# ---------------------------------------------------------------------------
def _import_prep():
    if str(BLOCKS14) not in sys.path:
        sys.path.insert(0, str(BLOCKS14))
    try:
        from prep.evidence.contradictions import ContradictionReport  # noqa: F401
        from prep.evidence.normalization import NormalizationIndex, bundle_hash  # noqa: F401
        from prep.evidence.reconciliation import ReconciliationIndex  # noqa: F401
        from prep.evidence.schema import EvidenceBundle
    except ImportError as e:
        raise BundleError(f"evidence backend not importable from {BLOCKS14}: {e}") from e
    return EvidenceBundle


def load_bundle(patient_id: str, handoff_dir: Path | None = None):
    """The validated EvidenceBundle for a patient, after checking the package hashes."""
    root = Path(handoff_dir) if handoff_dir else HANDOFF_DIR / f"patient-{patient_id}"
    if not (root / "manifest.json").exists():
        raise BundleError(f"no evidence package at {root}")
    EvidenceBundle = _import_prep()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8-sig"))
    for name, expected in manifest.get("files", {}).items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise BundleError(f"checksum mismatch for {name}")
    bundle = EvidenceBundle.model_validate_json((root / "evidence.json").read_text(encoding="utf-8-sig"))
    if bundle.manifest.patient_id != patient_id:
        raise BundleError(f"bundle is for patient {bundle.manifest.patient_id}, not {patient_id}")
    history = json.loads((root / "history.json").read_text(encoding="utf-8-sig")) if (root / "history.json").exists() else {}
    return bundle, history


def load_bundle_file(path: Path):
    """A single evidence bundle file (used for the independent synthetic fixture in tests)."""
    EvidenceBundle = _import_prep()
    return EvidenceBundle.model_validate_json(Path(path).read_text(encoding="utf-8-sig")), {}


# ---------------------------------------------------------------------------
def _render(value) -> tuple[str, dict]:
    kind = value.kind
    if kind == "medication":
        parts = [value.drug_name]
        if value.generic_name:
            parts.append(f"({value.generic_name})")
        if value.strength:
            parts.append(f"{value.strength.value:g} {value.strength.unit}")
        if value.route:
            parts.append(value.route)
        sched = None
        if value.schedule:
            s = value.schedule
            if any(x is not None for x in (s.morning, s.midday, s.evening, s.night)):
                sched = "-".join(f"{(x or 0):g}" for x in (s.morning, s.midday, s.evening, s.night))
            elif s.frequency_text:
                sched = s.frequency_text
        if sched:
            parts.append(sched)
        return " ".join(parts), {"drug": value.drug_name, "generic": value.generic_name,
                                 "strength": value.strength.value if value.strength else None,
                                 "strength_unit": value.strength.unit if value.strength else None,
                                 "route": value.route, "schedule": sched}
    if kind == "measurement":
        return f"{value.quantity.value:g} {value.quantity.unit}", {"value": value.quantity.value, "unit": value.quantity.unit}
    if kind == "allergy":
        txt = value.substance + (f" ({', '.join(value.reactions)})" if value.reactions else "")
        return txt, {"substance": value.substance, "reactions": list(value.reactions)}
    if kind == "assertion":
        return value.text, {"site": value.site, "laterality": value.laterality}
    if kind == "event":
        return value.name + (f" ({value.timing_text})" if value.timing_text else ""), {"timing": value.timing_text}
    return str(getattr(value, "value", "")), {}


_WS = re.compile(r"\s+")


def _locate(text: str, quote: str, hint_start: int) -> tuple[int, int] | None:
    """Offsets of `quote` in our cleaned document text; exact near the hint first."""
    if not quote:
        return None
    if 0 <= hint_start <= len(text) and text.startswith(quote, hint_start):
        return hint_start, hint_start + len(quote)
    i = text.find(quote)
    if i >= 0:
        return i, i + len(quote)
    # whitespace differences: compare on collapsed text and map back
    pattern = re.escape(_WS.sub(" ", quote).strip()).replace(r"\ ", r"\s+")
    m = re.search(pattern, text)
    return (m.start(), m.end()) if m else None


def build_layer(bundle, history: dict, doc_texts: dict[str, str], segments: list) -> EvidenceLayer:
    """Map facts, derived values and contradictions onto our segments.

    doc_texts: our cleaned document text per doc_id.
    segments:  our Segment list (segment_id, doc_id, start, end)."""
    by_doc: dict[str, list] = {}
    for s in segments:
        by_doc.setdefault(s.doc_id, []).append(s)

    def segs_for(doc_id: str, start: int, end: int) -> list[str]:
        return [s.segment_id for s in by_doc.get(doc_id, []) if s.start < end and start < s.end]

    passages = {p.id: p for p in bundle.passages}
    facts: dict[str, FactLite] = {}
    by_segment: dict[str, list[str]] = {}
    unmapped = 0
    for f in bundle.facts:
        if f.subject != "patient" and f.category != "family_history":
            continue
        summary, structured = _render(f.value)
        when = None
        if f.clinical_time and f.clinical_time.value and f.clinical_time.precision in ("day", "month", "year"):
            try:
                when = date.fromisoformat(str(f.clinical_time.value)[:10])
            except ValueError:
                when = None
        lite = FactLite(id=f.id, category=f.category, concept=f.concept, label=f.label, kind=f.value.kind,
                        assertion=f.assertion, status=f.clinical_status,
                        laterality=getattr(f.value, "laterality", "unspecified"), when=when,
                        summary=summary, structured=structured, method=f.extraction_method,
                        related=list(f.related_fact_ids))
        for ref in f.evidence:
            p = passages.get(ref.passage_id)
            doc_id = p.document_id if p else ref.passage_id.split(":")[0]
            text = doc_texts.get(doc_id, "")
            loc = _locate(text, ref.quote, ref.start)
            if loc is None:
                unmapped += 1
                continue
            lite.quotes.append((doc_id, loc[0], loc[1], ref.quote))
            for sid in segs_for(doc_id, *loc):
                if sid not in lite.segment_ids:
                    lite.segment_ids.append(sid)
        if lite.segment_ids:
            facts[f.id] = lite
            for sid in lite.segment_ids:
                by_segment.setdefault(sid, []).append(f.id)

    derived: list[DerivedLite] = []
    for d in bundle.derived_facts:
        seg_ids, doc_ids = [], []
        for fid in d.input_fact_ids:
            lf = facts.get(fid)
            if lf:
                seg_ids += [s for s in lf.segment_ids if s not in seg_ids]
                for q in lf.quotes:
                    if q[0] not in doc_ids:
                        doc_ids.append(q[0])
        derived.append(DerivedLite(id=d.id, concept=d.concept, label=d.label, value=float(d.result.value),
                                   unit=d.result.unit, explanation=d.explanation,
                                   input_fact_ids=list(d.input_fact_ids), segment_ids=seg_ids, doc_ids=doc_ids))

    contradictions: list[ContradictionLite] = []
    for c in bundle.contradictions:
        if c.status == "rejected":
            continue
        seg_ids, doc_ids, quotes = [], [], []
        for ref in c.evidence:
            p = passages.get(ref.passage_id)
            doc_id = p.document_id if p else ref.passage_id.split(":")[0]
            loc = _locate(doc_texts.get(doc_id, ""), ref.quote, ref.start)
            if loc:
                seg_ids += [s for s in segs_for(doc_id, *loc) if s not in seg_ids]
            if doc_id not in doc_ids:
                doc_ids.append(doc_id)
            quotes.append(ref.quote)
        contradictions.append(ContradictionLite(id=c.id, kind=KIND_MAP.get(c.kind, "other"), status=c.status,
                                                explanation=c.explanation, doc_ids=doc_ids, segment_ids=seg_ids,
                                                quotes=quotes, claim_ids=list(c.claim_ids)))

    latest = set((history.get("latest_discharge_medications") or {}).get("fact_ids") or [])
    gaps = [{"stage": g.stage, "documents": list(g.document_ids), "category": g.category, "reason": g.reason}
            for g in bundle.processing_gaps]
    return EvidenceLayer(version=bundle.manifest.evidence_version, status=bundle.manifest.status, facts=facts,
                         by_segment=by_segment, derived=derived, contradictions=contradictions,
                         latest_medication_fact_ids=latest, gaps=gaps, unmapped_quotes=unmapped)
