"""Block 8 contracts: what the final step hands to the UI.

Kept in their own module while blocks 5-7 are being edited in parallel sessions;
re-exported from contracts.py at merge time.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from .contracts import DerivedValue, EvidenceStatus, Flag, LocalizedText, Priority, RecordRelevance

ClaimKind = Literal["finding", "absent", "not_documented", "incomplete", "uncertain", "conflict"]
DropReason = Literal["irrelevant", "wrong_polarity", "superseded", "duplicate"]
Lang = Literal["en", "de"]


class Claim(BaseModel):
    """One sentence of the summary. Every finding cites the passages it rests on."""

    claim_id: str
    item_id: str | None = Field(description="Checklist item, or None for a conflict claim")
    text: str
    lang: Lang
    cites: list[str] = Field(description="segment_ids; empty only for not_documented/incomplete")
    kind: ClaimKind
    rendered_by: Literal["template", "llm"]


class DroppedFlag(BaseModel):
    segment_id: str
    reason: DropReason


class ItemResult(BaseModel):
    """One checklist item after the ranking check: the row in the ranked list."""

    item_id: str
    label: LocalizedText
    priority: Priority
    status: EvidenceStatus
    order: int
    flags: list[Flag] = Field(description="Kept passages, best first")
    dropped: list[DroppedFlag] = Field(default_factory=list)
    note: str = ""


class Conflict(BaseModel):
    """A confirmed contradiction. Links every passage involved."""

    segment_ids: list[str]
    doc_ids: list[str]
    kind: Literal["laterality", "number", "date", "value", "status", "other"]
    differing: list[str]
    explanation: str
    confirmed_by: Literal["llm", "rule"]
    items: list[str] = Field(default_factory=list, description="Checklist items this conflict concerns")


class PatientStrip(BaseModel):
    patient_id: str
    name: str
    sex: str
    date_of_birth: date | None
    age_at_as_of: int | None
    as_of: date | None


class FinalResult(BaseModel):
    patient: PatientStrip
    lang: Lang
    summary: list[Claim]
    items: list[ItemResult]
    custom: list[ItemResult] = Field(default_factory=list)
    conflicts: list[Conflict]
    records: list[RecordRelevance]
    mode: Literal["llm", "partial", "template_only"]
    models: dict[str, str] = Field(default_factory=dict, description="call -> model that answered")
    timings_ms: dict[str, float] = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list)
    dropped_claims: list[dict] = Field(default_factory=list, description="LLM claims that failed a check")
    derived: list[DerivedValue] = Field(default_factory=list, description="Values computed from verified facts")
    coverage: dict = Field(default_factory=dict, description="What the search covered")
    privacy: dict = Field(default_factory=dict, description="Outbound gate statistics: what was replaced before sending")
    doc_labels: dict[str, dict[str, str]] = Field(default_factory=dict,
                                                  description='doc_id -> {"en", "de"} short name for source links')
    cached: bool = False
