"""Reusable narrative extraction with exact quote resolution and a separate support check."""
import json
from dataclasses import dataclass, field
from pydantic import ValidationError

from prep.evidence.schema import EvidenceRef, Fact, ProcessingGap
from prep.ingestion.documents import digest
from prep.llm.client import ModelError, StructuredClient
from prep.extraction.narrative_models import Candidate, ExtractionResponse, SupportResponse
from prep.extraction.source_checks import check_time, check_status, check_measurement
from prep.extraction.prompts import EXTRACT, REVIEW, VERSION as PROMPT_VERSION

VERSION = "narrative-extractor-v3"
MAX_DOCUMENT_CHARS = 40000


@dataclass
class ExtractionResult:
    facts: list[Fact] = field(default_factory=list)
    processing_gaps: list[ProcessingGap] = field(default_factory=list)
    reviewed_passage_ids: list[str] = field(default_factory=list)


def resolve_quote(quote, passages, document):
    p = passages.get(quote.passage_id)
    if p is None or p.document_id != document.id:
        raise ValueError("unknown_evidence_passage")
    positions = []
    offset = p.text.find(quote.quote)
    while offset >= 0:
        positions.append(offset)
        offset = p.text.find(quote.quote, offset + 1)
    if quote.occurrence >= len(positions):
        raise ValueError("quote_not_found_at_occurrence")
    start = p.start + positions[quote.occurrence]
    end = start + len(quote.quote)
    if document.normalized_text[start:end] != quote.quote:
        raise ValueError("quote_document_mismatch")
    return EvidenceRef(passage_id=p.id, start=start, end=end, quote=quote.quote)


def candidate_fact(candidate, passages, document, model):
    refs = [resolve_quote(q, passages, document) for q in candidate.evidence]
    check_status(candidate, [r.quote for r in refs])
    check_time(candidate.clinical_time, [r.quote for r in refs], document)
    check_measurement(candidate, [r.quote for r in refs])
    if candidate.value.kind == "medication" and (candidate.value.generic_name or candidate.value.normalization_mapping_id):
        raise ValueError("unreviewed_generic_mapping")
    content = candidate.model_dump(mode="json", exclude={"evidence"})
    identity = json.dumps(content | {"evidence": [r.model_dump() for r in refs], "version": VERSION,
                                     "prompt": PROMPT_VERSION, "model": model}, sort_keys=True, ensure_ascii=False)
    return Fact(**content, id="llm-" + digest(identity.encode())[:24], evidence=refs,
                extraction_method="llm", extractor_version=VERSION,
                validation={"quote_match": "passed", "field_check": "not_checked", "semantic_check": "not_checked",
                            "notes": ["Exact quotes and schema checked; semantic support pending separate review."]})


def checked_candidate(raw, passages, document, model):
    """Omit unsupported optional metadata, never invent a replacement value."""
    value = raw.model_dump(mode="json") if isinstance(raw, Candidate) else raw
    omissions = []
    try:
        candidate = Candidate.model_validate(value)
    except ValidationError as error:
        if not isinstance(value, dict) or not all(e['loc'] and e['loc'][0] == 'clinical_time' for e in error.errors()):
            raise
        value = value | {"clinical_time": {"precision": "unknown", "basis": "unknown"}}
        candidate = Candidate.model_validate(value)
        omissions.append('invalid_time_metadata')
    refs = [resolve_quote(q, passages, document) for q in candidate.evidence]
    try:
        check_time(candidate.clinical_time, [r.quote for r in refs], document)
    except ValueError as error:
        omissions.append(str(error))
        candidate.clinical_time = candidate.clinical_time.__class__(precision='unknown', basis='unknown')
    try:
        check_status(candidate, [r.quote for r in refs])
    except ValueError as error:
        omissions.append(str(error))
        candidate.clinical_status = 'unknown'
    fact = candidate_fact(candidate, passages, document, model)
    fact.validation.notes.extend('Unsupported metadata omitted: ' + code for code in omissions)
    return fact, omissions


def extract_passages(document, passages, client: StructuredClient, existing_facts=(), requested_concepts=()):
    """One document per call; include original heading context for fallback use.

    Up to two extraction attempts and two support-review attempts. No shared-store mutation.
    """
    result = ExtractionResult()
    lookup = {p.id: p for p in passages}
    if len(lookup) != len(passages) or any(p.document_id != document.id for p in passages):
        raise ValueError("Passages must be unique and belong to the supplied document")

    def gap(code, ids=(), stage="extraction", retryable=False):
        key = json.dumps([document.id, code, sorted(ids), VERSION])
        item = ProcessingGap(id="narrative-gap-" + digest(key.encode())[:24], stage=stage,
            document_ids=[document.id], passage_ids=list(ids), reason=code, retryable=retryable)
        if item.id not in {g.id for g in result.processing_gaps}:
            result.processing_gaps.append(item)

    if not passages:
        gap("No passages supplied; narrative coverage unavailable")
        return result
    if sum(len(p.text) for p in passages) > MAX_DOCUMENT_CHARS:
        gap("Document exceeds narrative input limit; split with preserved context before retrying")
        return result
    source = {"document_id": document.id, "document_date": document.document_date.isoformat() if document.document_date else None,
              "passages": [{"id": p.id, "section": p.section, "text": p.text} for p in passages]}
    payload = source | {"existing_facts": [f.model_dump(mode="json") for f in existing_facts],
                        "requested_concepts": list(requested_concepts)}
    # Preserve valid candidates across repair failures instead of replacing the whole response.
    accepted, reviewed = {}, set()
    candidates, errors = [], []
    for attempt in range(2):
        try:
            response = client.generate(system=EXTRACT, payload=payload, response_type=ExtractionResponse)
            response = ExtractionResponse.model_validate(response)
        except (ModelError, ValidationError) as error:
            code = error.code if isinstance(error, ModelError) else "invalid_extraction_schema"
            if attempt == 0 and (not isinstance(error, ModelError) or error.retryable):
                payload = payload | {"retry_feedback": [code]}
                continue
            gap(code, retryable=isinstance(error, ModelError) and error.retryable)
            break
        errors, repair_items = [], []
        reviewed.update(set(response.reviewed_passage_ids) & set(lookup))
        if set(response.reviewed_passage_ids) - set(lookup) or len(response.reviewed_passage_ids) != len(set(response.reviewed_passage_ids)):
            errors.append("invalid_passage_coverage")
        if reviewed != set(lookup):
            errors.append("incomplete_passage_coverage")
        for unresolved in response.unresolved:
            if unresolved.passage_id in lookup:
                gap("Model reported unresolved source interpretation", [unresolved.passage_id])
            else:
                errors.append("unknown_unresolved_passage")
        for index, raw in enumerate(response.candidates):
            try:
                fact, omissions = checked_candidate(raw, lookup, document, client.model)
                for code in omissions:
                    gap('Unsupported metadata omitted: ' + code, sorted({r.passage_id for r in fact.evidence}), stage='validation')
                accepted[fact.id] = fact
            except (ValueError, ValidationError) as error:
                if isinstance(error, ValidationError):
                    code = "invalid_candidate_schema:" + ",".join(sorted({".".join(map(str, e["loc"])) for e in error.errors()})[:4])
                else:
                    code = str(error)
                value = raw.model_dump(mode="json") if isinstance(raw, Candidate) else raw
                repair_items.append({"index": index, "candidate": value, "error": code})
                errors.append(code)
        if errors and attempt == 0:
            # Failed candidates remain traceable even if the model omits them from its repair.
            for item in repair_items:
                raw = item["candidate"]
                ids = sorted({e.get("passage_id") for e in raw.get("evidence", []) if isinstance(e, dict) and e.get("passage_id") in lookup}) if isinstance(raw, dict) else []
                gap("Initial candidate rejected; repair requested: " + item["error"], ids, stage="validation")
            payload = source | {"existing_facts": [f.model_dump(mode="json") for f in existing_facts] + [f.model_dump(mode="json") for f in accepted.values()],
                "requested_concepts": list(requested_concepts), "retry_feedback": sorted(set(errors)),
                "repair_items": repair_items, "unreviewed_passage_ids": sorted(set(lookup) - reviewed),
                "repair_instruction": "Return ONLY corrected rejected candidates and facts from unreviewed passages. Do not repeat valid existing facts. If a field lacks evidence use unknown/null, not a guess. Report unresolved passages for items you cannot repair."}
            continue
        break
    candidates = list(accepted.values())
    result.reviewed_passage_ids = sorted(reviewed)
    for code in sorted(set(errors)):
        gap("Unresolved candidate or coverage issue: " + code, stage="validation")
    if not candidates:
        return result

    review_payload = source | {"candidates": [{"candidate_id": f.id, "fact": f.model_dump(mode="json")} for f in candidates]}
    expected = {f.id for f in candidates}
    decisions = None
    for attempt in range(2):
        try:
            response = client.generate(system=REVIEW, payload=review_payload, response_type=SupportResponse)
            response = SupportResponse.model_validate(response)
            if {d.candidate_id for d in response.decisions} != expected or len(response.decisions) != len(expected):
                raise ModelError("invalid_review_coverage", True)
            decisions = {d.candidate_id: d for d in response.decisions}
            break
        except (ModelError, ValidationError) as error:
            code = error.code if isinstance(error, ModelError) else "invalid_review_schema"
            if attempt == 0 and (not isinstance(error, ModelError) or error.retryable):
                review_payload = review_payload | {"retry_feedback": code}
                continue
            gap(code, stage="validation", retryable=isinstance(error, ModelError) and error.retryable)
            return result
    for fact in candidates:
        decision = decisions[fact.id]
        if decision.verdict != "supported":
            gap("Source-support review: " + decision.verdict, sorted({r.passage_id for r in fact.evidence}), stage="validation")
            continue
        fact.validation.semantic_check = "model_checked"
        fact.validation.notes = ["Exact source quote and schema checked; separate model review found cited evidence supportive. Not a guarantee of clinical correctness."] + [n for n in fact.validation.notes if n.startswith('Unsupported metadata omitted:')]
        result.facts.append(fact)
    # De-duplicate repeated gap IDs without silently dropping distinct passages.
    result.processing_gaps = list({g.id: g for g in result.processing_gaps}.values())
    return result
