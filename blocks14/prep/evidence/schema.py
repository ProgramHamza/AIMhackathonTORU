"""Patient evidence contract v1. Offsets count Unicode code points, not bytes."""

from datetime import date
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


Category = Literal[
    "demographics", "encounters", "diagnoses", "symptoms", "allergies",
    "medications", "vitals", "laboratory", "imaging", "functional_tests",
    "pathology", "procedures", "care_plans", "followups", "medical_history",
    "family_history", "social_history", "other_clinical",
]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClinicalTime(Model):
    """No invented day for partial dates. Relative dates preserve their wording."""
    precision: Literal["day", "month", "year", "interval", "relative", "unknown"]
    value: str | None = None
    end: str | None = None
    basis: Literal["explicit", "contextual", "document_fallback", "unknown"]
    original_text: str | None = None
    anchor_fact_id: str | None = None

    @model_validator(mode="after")
    def valid_time(self):
        if self.precision == "unknown":
            if self.value is not None or self.end is not None or self.basis != "unknown":
                raise ValueError("Unknown time cannot contain a date or assert a date basis")
        else:
            if not self.value or self.basis == "unknown":
                raise ValueError("Known time requires value and basis")
            if self.precision in ("day", "interval"):
                date.fromisoformat(self.value)
            elif self.precision == "month":
                if len(self.value) != 7:
                    raise ValueError("Month must be YYYY-MM")
                date.fromisoformat(self.value + "-01")
            elif self.precision == "year":
                if len(self.value) != 4:
                    raise ValueError("Year must be YYYY")
                date.fromisoformat(self.value + "-01-01")
            if self.precision == "interval":
                if self.end is None or date.fromisoformat(self.end) < date.fromisoformat(self.value):
                    raise ValueError("Interval requires an end on or after its start")
            elif self.end is not None:
                raise ValueError("Only intervals have an end")
        return self


class Document(Model):
    id: str
    title: str
    language: str = "de"
    source_kind: Literal["clinical_document", "patient_metadata"] = "clinical_document"
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    document_date: date | None = None
    original_text: str
    normalized_text: str
    normalization_version: str


class Passage(Model):
    id: str
    document_id: str
    section: str | None = None
    kind: Literal["sentence", "paragraph", "table_row", "heading"]
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1)


class EvidenceRef(Model):
    passage_id: str
    start: int = Field(ge=0, description="Absolute offset in normalized document")
    end: int = Field(gt=0, description="Exclusive absolute offset")
    quote: str = Field(min_length=1)


class Quantity(Model):
    value: float = Field(allow_inf_nan=False)
    unit: str = Field(min_length=1)


class Schedule(Model):
    morning: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    midday: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    evening: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    night: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    dose_unit: str | None = None
    frequency_text: str | None = None
    as_needed: bool | None = None
    original_text: str


class MedicationValue(Model):
    kind: Literal["medication"]
    drug_name: str
    generic_name: str | None = None
    normalization_mapping_id: str | None = None
    strength: Quantity | None = None
    dose: Quantity | None = None
    route: str | None = None
    schedule: Schedule | None = None
    prescription_context: str | None = None


class MeasurementValue(Model):
    kind: Literal["measurement"]
    quantity: Quantity
    site: str | None = None
    method: str | None = None


class AllergyValue(Model):
    kind: Literal["allergy"]
    substance: str
    reactions: list[str] = Field(default_factory=list)
    severity: str | None = None


class AssertionValue(Model):
    kind: Literal["assertion"]
    text: str
    site: str | None = None
    laterality: Literal["left", "right", "bilateral", "midline", "unspecified"] = "unspecified"


class EventValue(Model):
    kind: Literal["event"]
    name: str
    site: str | None = None
    laterality: Literal["left", "right", "bilateral", "midline", "unspecified"] = "unspecified"
    timing_text: str | None = None
    responsible_service: str | None = None
    outcome: str | None = None


class AttributeValue(Model):
    kind: Literal["attribute"]
    value: str


FactValue = Annotated[
    MedicationValue | MeasurementValue | AllergyValue | AssertionValue | EventValue | AttributeValue,
    Field(discriminator="kind"),
]


class Validation(Model):
    quote_match: Literal["passed"]
    field_check: Literal["passed", "not_checked"]
    semantic_check: Literal["rule_checked", "model_checked", "human_checked", "not_checked"]
    notes: list[str] = Field(default_factory=list)


class Fact(Model):
    id: str
    category: Category
    concept: str = Field(min_length=1, description="Stable concept key, e.g. body_weight")
    label: str
    value: FactValue
    assertion: Literal["affirmed", "negated", "suspected", "uncertain"]
    clinical_status: Literal[
        "active", "historical", "resolved", "discontinued", "recommended",
        "planned", "completed", "unknown",
    ]
    subject: Literal["patient", "family_member"] = "patient"
    clinical_time: ClinicalTime
    event_id: str | None = None
    evidence: list[EvidenceRef] = Field(min_length=1)
    extraction_method: Literal["rule", "llm", "hybrid"]
    extractor_version: str
    validation: Validation
    related_fact_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def category_payload(self):
        allowed = {
            "medications": {"medication"}, "allergies": {"allergy"},
            "vitals": {"measurement"}, "laboratory": {"measurement", "assertion"},
            "encounters": {"event"}, "procedures": {"event"},
            "care_plans": {"event"}, "followups": {"event"},
            "demographics": {"attribute"},
        }
        if self.category in allowed and self.value.kind not in allowed[self.category]:
            raise ValueError("Payload kind is incompatible with category")
        if isinstance(self.value, MedicationValue) and self.value.generic_name and not self.value.normalization_mapping_id:
            raise ValueError("Generic name requires a traceable normalization mapping")
        return self


class DerivedFact(Model):
    id: str
    category: Category
    concept: str
    label: str
    calculation: Literal["bmi", "weight_change", "age_at_date"]
    calculation_version: str
    input_fact_ids: list[str] = Field(min_length=1)
    result: Quantity
    reference_date: date | None = None
    explanation: str

    @model_validator(mode="after")
    def calculation_inputs(self):
        expected = 1 if self.calculation == "age_at_date" else 2
        if len(self.input_fact_ids) != expected:
            raise ValueError("Wrong number of inputs for calculation")
        if self.calculation == "age_at_date" and self.reference_date is None:
            raise ValueError("Age calculation requires an explicit reference date")
        return self


class Contradiction(Model):
    id: str
    kind: Literal["laterality", "event_date", "numeric_inconsistency", "status", "other"]
    status: Literal["candidate", "accepted", "rejected"]
    claim_ids: list[str] = Field(min_length=2, description="Fact or derived-fact IDs")
    explanation: str
    evidence: list[EvidenceRef] = Field(min_length=1)
    detector_version: str
    review_method: Literal["rules", "model", "human"]


class ProcessingGap(Model):
    id: str
    stage: Literal["normalization", "segmentation", "extraction", "validation", "reconciliation"]
    document_ids: list[str] = Field(min_length=1)
    passage_ids: list[str] = Field(default_factory=list)
    category: Category | None = None
    reason: str
    retryable: bool


class Manifest(Model):
    schema_version: Literal["1.0.0"] = "1.0.0"
    bundle_id: str
    patient_id: str
    dataset_kind: Literal["official_synthetic", "independent_synthetic"]
    evidence_version: str
    prepared_at: AwareDatetime
    pipeline_version: str
    configuration_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    model_versions: list[str] = Field(default_factory=list)
    status: Literal["complete", "partial"]
    offset_unit: Literal["unicode_code_points"] = "unicode_code_points"
    end_offset_exclusive: Literal[True] = True


class EvidenceBundle(Model):
    manifest: Manifest
    documents: list[Document] = Field(min_length=1)
    passages: list[Passage]
    facts: list[Fact]
    derived_facts: list[DerivedFact] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    processing_gaps: list[ProcessingGap] = Field(default_factory=list)

    @model_validator(mode="after")
    def integrity(self):
        def index(items):
            result = {item.id: item for item in items}
            if len(result) != len(items):
                raise ValueError("Duplicate IDs")
            return result

        docs, passages, facts = index(self.documents), index(self.passages), index(self.facts)
        derived = index(self.derived_facts)
        index(self.contradictions)
        index(self.processing_gaps)
        if set(facts) & set(derived):
            raise ValueError("Fact and derived-fact IDs must be disjoint")
        for p in self.passages:
            if p.document_id not in docs:
                raise ValueError("Unknown passage document")
            text = docs[p.document_id].normalized_text
            if not (0 <= p.start < p.end <= len(text)) or text[p.start:p.end] != p.text:
                raise ValueError("Passage text/offset mismatch")

        def check_ref(ref):
            if ref.passage_id not in passages:
                raise ValueError("Unknown evidence passage")
            p = passages[ref.passage_id]
            if not (p.start <= ref.start < ref.end <= p.end):
                raise ValueError("Evidence offsets outside passage")
            if docs[p.document_id].normalized_text[ref.start:ref.end] != ref.quote:
                raise ValueError("Evidence quote mismatch")

        for fact in self.facts:
            for ref in fact.evidence:
                check_ref(ref)
            targets = fact.related_fact_ids + ([fact.clinical_time.anchor_fact_id] if fact.clinical_time.anchor_fact_id else [])
            if any(target not in facts for target in targets):
                raise ValueError("Unknown related/anchor fact")
        for item in self.derived_facts:
            if len(set(item.input_fact_ids)) != len(item.input_fact_ids) or any(i not in facts for i in item.input_fact_ids):
                raise ValueError("Derived inputs must be unique existing source facts")
        for conflict in self.contradictions:
            if len(set(conflict.claim_ids)) != len(conflict.claim_ids):
                raise ValueError("Contradiction claims must be distinct")
            required = set()
            for claim in conflict.claim_ids:
                if claim in facts:
                    sources = [facts[claim]]
                elif claim in derived:
                    sources = [facts[i] for i in derived[claim].input_fact_ids]
                else:
                    raise ValueError("Unknown contradiction claim")
                required.update((r.passage_id, r.start, r.end, r.quote) for f in sources for r in f.evidence)
            for ref in conflict.evidence:
                check_ref(ref)
            supplied = {(r.passage_id, r.start, r.end, r.quote) for r in conflict.evidence}
            if not required.issubset(supplied):
                raise ValueError("Contradiction must include evidence for all claims")
        for gap in self.processing_gaps:
            if any(d not in docs for d in gap.document_ids) or any(p not in passages for p in gap.passage_ids):
                raise ValueError("Unknown gap document/passage")
            if any(passages[p].document_id not in gap.document_ids for p in gap.passage_ids):
                raise ValueError("Gap passage belongs to a different document")
        if self.processing_gaps and self.manifest.status != "partial":
            raise ValueError("Unresolved processing gaps require partial status")
        return self
