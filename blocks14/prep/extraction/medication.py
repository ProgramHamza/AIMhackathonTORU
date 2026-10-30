"""Conservative parser for four-slot discharge medication tables; no drug-name whitelist."""
import re
from fractions import Fraction

from prep.evidence.schema import ClinicalTime, EvidenceRef, Fact, ProcessingGap
from prep.ingestion.documents import MEDICATION_HEADING, TABLE_HEADER, digest

VERSION = "discharge-medication-v1"
NUMBER = r"(?:\d+/\d+|\d+(?:[.,]\d+)?)"
SLOTS = re.compile(rf"^(?P<mo>{NUMBER})\s+(?P<mi>{NUMBER})\s+(?P<ab>{NUMBER})\s+(?P<na>{NUMBER})(?:\s+(?P<unit>ST|Tabl\.?|Tabletten|Tropfen|Dosen))?$", re.I)
ROUTE = re.compile(r"\s+(oral|s\.\s*c\.|s\.\s*c|p\.\s*o\.)\s+", re.I)
STRENGTH = re.compile(r"^(.*?)\s*(\d+(?:[.,]\d+)?)\s*(mg|mcg|µg|μg|g|ml)\s*$", re.I)
WEEKLY = re.compile(rf"^(?:ST\s+)?1\s*x\s*/\s*Woche\s+(?P<amount>{NUMBER})\s*(?:Tabl\.?|Tabletten)$", re.I)


def reference(passage):
    return EvidenceRef(passage_id=passage.id, start=passage.start, end=passage.end, quote=passage.text)


def number(text):
    value = float(Fraction(text.replace(",", ".")))
    if value < 0:
        raise ValueError("Negative schedule")
    return value


def parse_row(text):
    if re.search(r"\b(?:abgesetzt|pausiert|bei Bedarf|nicht einnehmen|statt|bis zum)\b", text, re.I):
        raise ValueError("Status or conditional instruction requires contextual interpretation")
    route_match = ROUTE.search(text)
    if not route_match:
        raise ValueError("Missing or unsupported route/table format")
    prefix, suffix = text[:route_match.start()].strip(), text[route_match.end():].strip()
    # Never swallow unparsed dosage text into a drug name.
    strength_match = STRENGTH.fullmatch(prefix)
    if strength_match:
        drug, amount, unit = strength_match.groups()
        if not drug.strip() or re.search(r"\b(?:mg|mcg|µg|ml)\b", drug, re.I):
            raise ValueError("Ambiguous strength or concentration")
        strength = {"value": number(amount), "unit": {"mcg": "µg", "μg": "µg"}.get(unit.lower(), unit.lower())}
    else:
        if re.search(r"\d|\b(?:mg|mcg|µg|ml)\b", prefix, re.I):
            # Vitamin D3 is a drug-name token, not a numeric dose.
            if not re.fullmatch(r"[^\d]+D3\s+Tropfen", prefix, re.I):
                raise ValueError("Unresolved strength text before route")
        drug, strength = prefix, None
    slots = SLOTS.fullmatch(suffix)
    weekly = WEEKLY.fullmatch(suffix)
    if slots:
        unit = slots.group("unit")
        schedule = {name: number(slots.group(key)) for name, key in
                    [("morning", "mo"), ("midday", "mi"), ("evening", "ab"), ("night", "na")]}
        schedule.update(dose_unit={"st": "piece", "tabl": "tablet", "tabletten": "tablet", "tropfen": "drop", "dosen": "dose"}.get(unit.lower().rstrip(".")) if unit else None,
                        original_text=suffix)
    elif weekly:
        schedule = {"frequency_text": suffix, "dose_unit": "tablet", "original_text": suffix}
    else:
        raise ValueError("Unsupported or ambiguous schedule; row retained as a processing gap")
    route_token = re.sub(r"\s+", "", route_match.group(1).lower())
    route = "oral" if route_token in ("oral", "p.o.") else "subcutaneous"
    return {"kind": "medication", "drug_name": drug.strip(), "strength": strength,
            "route": route, "schedule": schedule, "prescription_context": "discharge medication"}


def extract_medications(document, passages):
    facts, gaps = [], []
    heading = header = None
    for p in passages:
        if p.kind == "heading" and MEDICATION_HEADING.fullmatch(p.text):
            heading, header = p, None
            continue
        if heading and TABLE_HEADER.match(p.text):
            header = p
            continue
        if p.kind == "heading":
            heading = header = None
            continue
        if not heading or p.kind != "table_row":
            continue
        try:
            if header is None:
                raise ValueError("Missing morning/midday/evening/night column header")
            value = parse_row(p.text)
            clinical_time = ClinicalTime(precision="day", value=document.document_date.isoformat(), basis="document_fallback") if document.document_date else ClinicalTime(precision="unknown", basis="unknown")
            facts.append(Fact(
                id="med-" + digest((p.id + VERSION).encode())[:24], category="medications",
                concept="medication:" + re.sub(r"\s+", "_", value["drug_name"].lower()), label=value["drug_name"],
                value=value, assertion="affirmed", clinical_status="unknown", clinical_time=clinical_time,
                evidence=[reference(p), reference(heading), reference(header)], extraction_method="rule", extractor_version=VERSION,
                validation={"quote_match": "passed", "field_check": "passed", "semantic_check": "rule_checked",
                            "notes": ["Discharge-list entry; not proof of present-day use. Date is document fallback."]}))
        except (ValueError, ZeroDivisionError) as error:
            gaps.append(ProcessingGap(id="gap-" + digest(p.id.encode())[:24], stage="extraction",
                                      document_ids=[document.id], passage_ids=[p.id], category="medications",
                                      reason=str(error), retryable=False))
    return facts, gaps
