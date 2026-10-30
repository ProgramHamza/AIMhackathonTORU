"""Model-facing schemas: no model-generated IDs, offsets or validation verdicts."""
from typing import Literal, Union
from pydantic import Field, SkipValidation, field_validator, ValidationError
from prep.evidence.schema import (
    Model, Category, ClinicalTime, MedicationValue, MeasurementValue, AllergyValue,
    AssertionValue, EventValue, AttributeValue,
)


class Quote(Model):
    passage_id: str
    quote: str = Field(min_length=1)
    occurrence: int = Field(ge=0, description="Zero-based occurrence of this exact quote within the passage")


class Candidate(Model):
    category: Category
    concept: str = Field(min_length=1)
    label: str
    # Plain union produces anyOf (supported by OpenAI), rather than discriminator/oneOf.
    value: Union[MedicationValue, MeasurementValue, AllergyValue, AssertionValue, EventValue, AttributeValue]
    assertion: Literal["affirmed", "negated", "suspected", "uncertain"]
    clinical_status: Literal["active", "historical", "resolved", "discontinued", "recommended", "planned", "completed", "unknown"]
    subject: Literal["patient", "family_member"]
    clinical_time: ClinicalTime
    evidence: list[Quote] = Field(min_length=1)


class Unresolved(Model):
    passage_id: str
    reason: str


class ExtractionResponse(Model):
    # Keep the full provider-facing schema, but validate each item independently.
    # An invalid candidate stays raw until the orchestrator can request a targeted repair.
    candidates: list[SkipValidation[Candidate]]
    reviewed_passage_ids: list[str]
    unresolved: list[Unresolved]

    @field_validator("candidates")
    @classmethod
    def validate_items_independently(cls, items):
        results = []
        for item in items:
            try:
                results.append(Candidate.model_validate(item))
            except ValidationError:
                results.append(item)
        return results


class SupportDecision(Model):
    candidate_id: str
    verdict: Literal["supported", "unsupported", "unclear"]
    reason: str


class SupportResponse(Model):
    decisions: list[SupportDecision]
