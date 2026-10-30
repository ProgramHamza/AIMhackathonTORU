"""Bounded German labelled-field rules; unsupported context remains for narrative extraction."""
import re
import json
from datetime import date

from prep.evidence.schema import ClinicalTime, EvidenceRef, Fact, ProcessingGap
from prep.ingestion.documents import digest

VERSION = "labelled-fields-v1"
NUM = r"\d+(?:[.,]\d+)?"
CONTEXT = re.compile(r"\b(?:kein\w*|nicht|ohne|Verdacht|Vd\.?\s*a\.?|Zielwert|Sollwert|Referenz|früher|damals|Familienanamnese|geplant\w*|empfohlen|soll)\b|\?", re.I)
MEASURES = [
    # "Gewicht: 74 kg", "Körpergewicht: 74 kg" and the inline "Größe 167 cm, Gewicht 74 kg, BMI 20,2"
    ("body_weight", "Weight", "vitals", rf"\b(?:Körper)?[Gg]ewicht\s*:?\s*({NUM})\s*(kg|g)\b"),
    ("body_height", "Height", "vitals", rf"\b(?:Körper)?[Gg]röße\s*:?\s*({NUM})\s*(cm|m)\b"),
    ("body_mass_index", "Recorded BMI", "vitals", rf"\bBMI\s*:?\s*({NUM})(?:\s*(kg/m2|kg/m²))?"),
    ("body_temperature", "Temperature", "vitals", rf"Körpertemperatur\s*:\s*({NUM})\s*(°\s*C)"),
    ("heart_rate", "Heart rate", "vitals", rf"HF\s*:?\s*({NUM})\s*(/min|bpm)"),
    ("ejection_fraction", "Ejection fraction", "functional_tests", rf"\bEF\s*:?\s*({NUM})\s*(%)"),
    ("hba1c", "HbA1c", "laboratory", rf"\bHbA1c\s*(?::|von)?\s*({NUM})\s*(%|mmol/mol)"),
    ("ki67", "Ki-67", "pathology", rf"\bKi-?67(?:-Proliferationsrate)?\s*:?\s*({NUM})\s*(%)"),
]


def extract_structured(document, passages):
    facts, gaps = [], []
    headings = [p for p in passages if p.kind == "heading" and p.text.rstrip(":") == p.section]
    fallback = ClinicalTime(precision="day", value=document.document_date.isoformat(), basis="document_fallback") if document.document_date else ClinicalTime(precision="unknown", basis="unknown")

    def evidence(p, start, end):
        refs = [EvidenceRef(passage_id=p.id, start=start, end=end, quote=document.normalized_text[start:end])]
        heading = next((h for h in reversed(headings) if h.section == p.section and h.start <= p.start), None)
        if heading and heading.id != p.id:
            refs.append(EvidenceRef(passage_id=heading.id, start=heading.start, end=heading.end, quote=heading.text))
        return refs

    def gap(p, start, concept, reason):
        key = f"{p.id}:{start}:{concept}:{VERSION}"
        gaps.append(ProcessingGap(id="structured-gap-" + digest(key.encode())[:24], stage="extraction",
                                  document_ids=[document.id], passage_ids=[p.id], category=None,
                                  reason=reason, retryable=False))

    def add(p, start, end, concept, label, category, value, assertion="affirmed", time=None, status="unknown"):
        key = f"{p.id}:{start}:{concept}:{VERSION}:" + json.dumps(value, sort_keys=True)
        fact_id = "field-" + digest(key.encode())[:24]
        if any(f.id == fact_id for f in facts):
            return
        facts.append(Fact(id=fact_id, category=category, concept=concept, label=label,
                          value=value, assertion=assertion, clinical_status=status, clinical_time=time or fallback,
                          event_id=f"{document.id}:span:{start}", evidence=evidence(p, start, end),
                          extraction_method="rule", extractor_version=VERSION,
                          validation={"quote_match": "passed", "field_check": "passed", "semantic_check": "rule_checked",
                                      "notes": ["Bounded labelled-field rule; document-date fallback unless explicit event date is present."]}))

    for p in passages:
        if p.kind in ("heading", "table_row"):
            continue
        cursor = p.start
        for raw in p.text.splitlines(keepends=True):
            line = raw.rstrip("\n")
            start, end = cursor, cursor + len(line)
            cursor += len(raw)
            for concept, label, category, pattern in MEASURES:
                for match in re.finditer(r"(?<!\w)" + pattern + r"(?![\w/])", line, re.I):
                    # Avoid partial matches of ranges or unexpected units and temporal/negated context.
                    suffix = line[match.end():]
                    ambiguous = CONTEXT.search((p.section or "") + " " + line) or re.match(r"\s*(?:[-–]\s*\d|mmol|kg|cm|%)", suffix)
                    if concept == "body_mass_index" and match.group(2) is None and re.match(r"\s*[A-Za-z/²]", suffix):
                        ambiguous = True
                    if ambiguous:
                        gap(p, start + match.start(), concept, f"Ambiguous context/unit for {concept}; retained for contextual extraction")
                        continue
                    value = float(match.group(1).replace(",", "."))
                    unit = match.group(2) or "kg/m2"
                    unit = {"kg/m²": "kg/m2", "bpm": "/min"}.get(unit, unit.replace(" ", ""))
                    add(p, start, end, concept, label, category, {"kind": "measurement", "quantity": {"value": value, "unit": unit}})

            bp = re.fullmatch(r"\s*(?:(?:RR(?: bei Aufnahme)?|Blutdruck|24-Mittelwert|Tagesmittelwert|Nachtmittelwert)\s*:\s*)?(\d{2,3})\s*/\s*(\d{2,3})\s*mmHg\s*", line, re.I)
            if bp and (":" in line or (p.section and re.match(r"RR|Blutdruck", p.section, re.I))):
                for index, concept in enumerate(("systolic_blood_pressure", "diastolic_blood_pressure"), 1):
                    add(p, start, end, concept, concept.replace("_", " "), "vitals",
                        {"kind": "measurement", "quantity": {"value": int(bp.group(index)), "unit": "mmHg"}})

            # Allergy lines must be explicit, not arbitrary mentions in narrative.
            allergy = re.fullmatch(r"\s*(?:Allergie(?:n)?\s*:\s*)?(KM|Kontrastmittel|[A-Za-zÄÖÜäöüß -]+)-Allergie\s*\(([^()]*)\)\s*", line, re.I)
            if allergy:
                substance, reaction = allergy.groups()
                if CONTEXT.search(substance):
                    gap(p, start, "allergy", "Qualified/negated allergy requires contextual interpretation")
                else:
                    substance = "Kontrastmittel" if substance.upper() == "KM" else substance.strip()
                    add(p, start, end, "allergy:" + substance.lower(), "Documented allergy", "allergies",
                        {"kind": "allergy", "substance": substance, "reactions": [x.strip() for x in reaction.split(",") if x.strip()]})
            elif re.fullmatch(r"\s*(?:Allergien:\s*)?Keine (?:bekannten )?Allergien(?: bekannt)?[.]?\s*", line, re.I):
                add(p, start, end, "allergy_unspecified", "No known allergies documented", "allergies",
                    {"kind": "allergy", "substance": "unspecified", "reactions": []}, assertion="negated")
            elif p.section and re.fullmatch(r"Allergien?", p.section, re.I) and line.strip():
                gap(p, start, "allergy", "Unrecognized allergy section entry; no absence inference")

            # A complete staging tuple is preserved as recorded; no inference from tumour size.
            for stage in re.finditer(r"\bT[0-4xX](?:[a-c])?\s+N[0-3xX](?:[a-c])?\s+M[01xX]\s+V[012xX]\s+G[1-4xX]\b", line):
                if CONTEXT.search(line):
                    gap(p, start + stage.start(), "tumour_stage", "Qualified staging requires contextual interpretation")
                else:
                    add(p, start, end, "tumour_stage", "Recorded tumour stage", "pathology", {"kind": "attribute", "value": stage.group()})

            receptor_pattern = r"(Östrogenrezeptor|Progesteronrezeptor|Her2neu-Expression|HER2)\s*:\s*(positiv|negativ)\b([^\n]*?)(?=Östrogenrezeptor\s*:|Progesteronrezeptor\s*:|Her2neu-Expression\s*:|HER2\s*:|$)"
            for receptor in re.finditer(receptor_pattern, line, re.I):
                name, status, tail = receptor.groups()
                if CONTEXT.search(line):
                    gap(p, start + receptor.start(), "receptor", "Qualified receptor result requires contextual interpretation")
                    continue
                concept = {"östrogenrezeptor": "estrogen_receptor", "progesteronrezeptor": "progesterone_receptor"}.get(name.lower(), "her2")
                add(p, start + receptor.start(), start + receptor.end(), concept, name, "pathology", {"kind": "attribute", "value": status.lower()})
                percent = re.search(rf"\(({NUM})%\s+rezeptorpositive Tumorzellen\)", tail, re.I)
                if percent:
                    add(p, start + receptor.start(), start + receptor.end(), concept + "_percent", name + " positive cells", "pathology",
                        {"kind": "measurement", "quantity": {"value": float(percent.group(1).replace(",", ".")), "unit": "%"}})
                allred = re.search(r"Allred-Score\s*:\s*([0-8])\b", tail, re.I)
                if allred:
                    add(p, start + receptor.start(), start + receptor.end(), concept + "_allred", name + " Allred score", "pathology",
                        {"kind": "measurement", "quantity": {"value": int(allred.group(1)), "unit": "score"}})

            for event in re.finditer(r"\b(Aufnahme am|Entlassen am|Entnahmedatum:)\s*(\d{1,2}[./]\d{1,2}[./]\d{4,5})\b", line, re.I):
                label, raw_date = event.groups()
                try:
                    day, month, year = map(int, re.split(r"[./]", raw_date))
                    parsed = date(year, month, day).isoformat()
                except ValueError:
                    gap(p, start + event.start(), "event_date", "Invalid explicit event date retained without repair")
                    continue
                if CONTEXT.search(line):
                    gap(p, start + event.start(), "event_date", "Qualified event date requires contextual interpretation")
                    continue
                concept = {"aufnahme am": "admission", "entlassen am": "discharge", "entnahmedatum:": "specimen_collection"}[label.lower()]
                category = "procedures" if concept == "specimen_collection" else "encounters"
                add(p, start + event.start(), start + event.end(), concept, concept, category,
                    {"kind": "event", "name": concept}, time=ClinicalTime(precision="day", value=parsed, basis="explicit", original_text=raw_date), status="completed")
    return facts, gaps
