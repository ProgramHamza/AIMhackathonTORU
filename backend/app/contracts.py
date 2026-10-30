"""Shared data contracts.

Only the models blocks 5-8 produce or need right now. Models consumed from blocks 1-4
(Segment, Fact, Contradiction, ProcessingGap, coverage) are added when they are agreed;
names are reconciled at merge time.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

Priority = Literal["critical", "high", "normal"]
TimeRule = Literal["current", "latest", "history"]
NodeKind = Literal["role", "task", "context", "concept"]
NodeSource = Literal["prompt", "fuzzy", "semantic", "ancestor", "implied", "default", "llm"]


class LocalizedText(BaseModel):
    en: str
    de: str


class NodeHit(BaseModel):
    """One node of the decision graph that is active for this request."""

    node_id: str
    kind: NodeKind
    activation: float = Field(ge=0, le=1, description="1.0 = named in the prompt")
    source: NodeSource
    matched: list[str] = Field(default_factory=list, description="Prompt words that matched")


class ChecklistEntry(BaseModel):
    """One checklist item selected for this request, with why it was selected."""

    item_id: str
    label: LocalizedText
    question: str
    priority: Priority
    score: float = Field(description="Relevance from the graph, 0-1")
    domains: list[str]
    filters: dict[str, str] = Field(default_factory=dict)
    time_rule: TimeRule
    terms: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Search terms for retrieval; key 'llm' holds terms the LLM step added")
    codes: dict[str, list[str]] = Field(default_factory=dict)
    reasons: list[str] = Field(description="Rule IDs, 'link:<item>', 'asked' or 'llm'")


class Checklist(BaseModel):
    entries: list[ChecklistEntry]
    suppressed: list[str] = Field(description="Item IDs a rule explicitly hid")


class Coverage(BaseModel):
    """How much of the prompt the keyword graph understood."""

    content_words: int
    accounted_words: int
    unaccounted: list[str]

    @property
    def ratio(self) -> float:
        return self.accounted_words / self.content_words if self.content_words else 1.0


class CustomQuestion(BaseModel):
    """A need from the prompt that no checklist item covers; goes to live retrieval."""

    question: str
    search_terms_de: list[str]
    search_terms_en: list[str]
    priority: Priority = "high"


class QueryPlan(BaseModel):
    """Output of block 5: how the request was understood and what to look for."""

    prompt: str
    nodes: list[NodeHit]
    checklist: Checklist
    custom_questions: list[CustomQuestion] = Field(default_factory=list)
    as_of: date | None = None
    coverage: Coverage
    method: Literal["keywords", "keywords+llm"] = "keywords"
    llm_ms: float | None = None
    semantic_links: list[str] = Field(default_factory=list,
                                      description="Unknown phrase -> graph alias (similarity)")
    semantic_ms: float | None = None
    issues: list[str] = Field(default_factory=list, description="Warnings for the hand-off")


# ---------------------------------------------------------------------------
# Block 1 (interim): segments. The other team's segmenter replaces ours at merge time.
# ---------------------------------------------------------------------------
SegmentKind = Literal["header", "field", "sentence", "table_row", "boilerplate"]


class Segment(BaseModel):
    """One sentence, labelled line or table row. `text` == document_text[start:end]."""

    segment_id: str = Field(description="'<doc_id>#<n>'")
    doc_id: str
    start: int
    end: int
    text: str
    kind: SegmentKind
    section: str = ""
    label: str = Field("", description="Field label for 'Label: value' lines")
    doc_date: date | None = None


# ---------------------------------------------------------------------------
# Blocks 6/7: the remarker
# ---------------------------------------------------------------------------
Polarity = Literal["affirmed", "negated", "uncertain", "past", "planned"]
EvidenceStatus = Literal["found", "documented_absent", "uncertain", "not_documented",
                         "processing_incomplete"]


class Flag(BaseModel):
    """One marked passage for one checklist item (or custom question)."""

    segment_id: str
    doc_id: str
    start: int
    end: int
    text: str
    section: str
    doc_date: date | None
    ridx: float = Field(description="Relevance index 0-1")
    signals: dict[str, float] = Field(description="lexical, dense, rerank, code, section, context, llm_terms")
    matched_terms: list[str]
    polarity: Polarity
    sides: list[str] = Field(default_factory=list, description="left / right / both, if stated")
    current: bool = Field(True, description="False when a newer document supersedes it")
    duplicates: list[str] = Field(default_factory=list, description="Same passage in other segments")
    fact_ids: list[str] = Field(default_factory=list, description="Verified facts (blocks 1-4) in this passage")
    structured: dict | None = Field(None, description="Structured value of the first matching fact")
    keyword: str = Field("", description="The few words that answer the item, shown instead of the passage")
    highlights: list[tuple[int, int]] = Field(default_factory=list,
                                              description="Document offsets of the keyword's words in the passage")


class ItemEvidence(BaseModel):
    item_id: str
    label: LocalizedText
    priority: Priority
    status: EvidenceStatus
    flags: list[Flag]
    note: str = ""


class RecordRelevance(BaseModel):
    """One document, for the record list."""

    doc_id: str
    title: str
    date: date | None
    doc_type: str
    score: float = Field(description="0-100")
    label_counts: dict[str, int] = Field(description="item_id -> number of flags in this document")
    top_flags: list[str] = Field(description="segment_ids of the strongest flags")


class ContradictionCandidate(BaseModel):
    """Two nearly identical passages that differ in a side or a number."""

    segment_ids: list[str]
    doc_ids: list[str]
    differing: list[str] = Field(default_factory=list, description="Words that differ, e.g. ['links', 'rechts']")
    kind: Literal["laterality", "number", "date", "status", "other"]
    items: list[str] = Field(default_factory=list,
                             description="Checklist items of this request whose scores mark these passages")
    status: Literal["candidate", "accepted"] = "candidate"
    explanation: str = ""
    source: Literal["near_duplicate", "evidence_bundle"] = "near_duplicate"


class DerivedValue(BaseModel):
    """A value computed in code from verified facts (blocks 1-4), e.g. weight change."""

    id: str
    concept: str
    label: str
    value: float
    unit: str
    explanation: str = ""
    segment_ids: list[str] = Field(default_factory=list, description="Passages of every input fact")
    doc_ids: list[str] = Field(default_factory=list)
    items: list[str] = Field(default_factory=list, description="Checklist items this value answers")

    @property
    def value_text(self) -> str:
        v = f"{self.value:+.1f}" if self.concept.endswith("_change") else f"{self.value:.1f}"
        return f"{v} {self.unit}"


class RemarkerResult(BaseModel):
    patient_id: str
    as_of: date | None
    items: list[ItemEvidence]
    custom: list[ItemEvidence] = Field(default_factory=list)
    records: list[RecordRelevance]
    contradictions: list[ContradictionCandidate]
    derived: list[DerivedValue] = Field(default_factory=list)
    coverage: dict = Field(default_factory=dict,
                           description="What the search covered: documents, segments, dense search, facts")
    api_calls: int = 0
    timings_ms: dict[str, float] = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list)
    doc_labels: dict[str, dict[str, str]] = Field(default_factory=dict,
                                                  description='doc_id -> {"en", "de"} short name for source links')
