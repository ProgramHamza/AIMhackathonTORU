# Evidence handoff v1

Status: evidence contract, offline preparation/extraction, normalization, presentation reconciliation and bounded contradiction detection are implemented. API routes and the online query layer are separate integration work.

## Files and use

- `backend/evidence/schema.py`: canonical Pydantic v2 contract and relational integrity validation.
- `contracts/evidence-bundle.schema.json`: generated JSON Schema for another language or service.
- `contracts/evidence-categories.json`: complete machine-readable category catalogue.
- `contracts/examples/independent-patient.json`: independently authored fixture, not copied from IBM data.
- `tests/evidence/`: contract tests, not clinical extraction evaluation.

Install `backend/requirements.txt`, then run:

```sh
python -m backend.evidence.export_contract
python -m unittest discover -s tests/evidence -v
```

```python
from pathlib import Path
from backend.evidence.schema import EvidenceBundle
bundle = EvidenceBundle.model_validate_json(Path(path).read_text(encoding="utf-8"))
```

JSON Schema validates structure only. Consumers must also perform the reference, offset and coverage integrity checks implemented by `EvidenceBundle`; ordinary JSON Schema cannot enforce cross-record consistency.

## Scope and ownership

Preparation owns documents, passages, facts, derived values, contradiction candidates/decisions and processing gaps. Query processing owns guideline questions, relevance, ranking, coverage and rendering. There is no top-N extraction cap. Return all supported clinical facts; consolidate repeated mentions without erasing history or conflicting claims.

Existing frontend categories are presentation types, not extraction categories. The catalogue suggests mappings, not mandatory layouts. Eighteen clinical categories do NOT require eighteen displayed components. The online adapter selects relevant facts and maps them into the existing maximum-ten-category response or a future list renderer. It converts clinical statuses to UI labels deliberately.

## Categories

| ID | Meaning |
|---|---|
| demographics | Source-backed patient attributes |
| encounters | Admissions, discharges and encounter context |
| diagnoses | Conditions and their certainty/status |
| symptoms | Symptoms, episodes and explicit causal statements |
| allergies | Allergy substances, reactions and documented negative findings |
| medications | Drug, strength, dose, route and schedule |
| vitals | Vital signs, height and weight |
| laboratory | Quantitative and qualitative laboratory findings |
| imaging | Anatomical imaging findings |
| functional_tests | Cardiac, rhythm, cognitive and other functional findings |
| pathology | Histology, stage, grade, receptors and related findings |
| procedures | Investigations and interventions |
| care_plans | Planned or recommended treatment |
| followups | Recommended checks/reviews and linked completion evidence |
| medical_history | Historical conditions and surgery context |
| family_history | Findings concerning relatives |
| social_history | Documented social/lifestyle context and support |
| other_clinical | Supported information outside the current taxonomy |

One primary category per fact; `concept` is an extensible stable key. Use granular pathology attributes such as `estrogen_receptor` or `tumour_stage`, rather than flattening all pathology into one string. Blood pressure can use linked systolic and diastolic measurements sharing an event ID. A procedure and its finding can be separate related facts. Avoid duplicating identical claims just to populate another category.

## Fact semantics

- `assertion`: affirmed, negated, suspected or uncertain. This is separate from temporal/procedure status.
- `clinical_status`: active, historical, resolved, discontinued, recommended, planned, completed or unknown.
- Do not treat a diagnosis list as proof of a diagnosis onset date. Document fallback dates are labelled explicitly.
- Dates are ISO day/month/year, intervals, relative wording or unknown. No fabricated day for a partial date. Invalid source dates remain in the quote; use unknown plus a processing gap if unresolved.
- Relative times preserve wording and may reference an anchor fact; do not silently manufacture an exact day.
- Family history uses `subject=family_member`; never convert it into the patient's diagnosis.
- Strength and administered dose are separate quantities. Schedule nulls mean unknown, zero means an explicitly absent scheduled dose. Weekly and PRN schedules retain their original wording.
- Generic drug names require a versioned reviewed mapping identifier. Translations/normalizations require review; quotes remain in the source language.
- `event_id` groups facts only when event identity is established. Sharing a date is not sufficient.
- `other_clinical` preserves useful unexpected information but is not a way to avoid specific categorization.

## Provenance and offsets

Each document retains raw text and immutable normalized text. `source_sha256` hashes the original source file bytes; the configuration hash covers preparation settings. The manifest's evidence version must change when sources or normalization/extraction settings change.

Offsets are absolute, zero-based, Unicode code-point positions in `Document.normalized_text`, with an exclusive end. All evidence must lie within its passage and exactly equal the normalized substring. Keep whitespace normalization deterministic. A partial quote needs its own correct offsets even if the same wording occurs twice.

Python uses code-point offsets; JavaScript string slicing uses UTF-16. The API adapter must convert offsets or slice with `Array.from(text).slice(start,end).join('')`. Do not hand these offsets unchanged to a UTF-16-based source viewer.

Suggested future ID policy: document IDs from upstream identity plus source version; passage IDs from document version and span; fact IDs from normalized claim content and evidence. Do not promise unchanged IDs after source edits. UI citations must retain the evidence version. Test/example IDs are arbitrary stable identifiers.

Quote existence is not proof of clinical correctness. `Validation` records which checks actually ran. `not_checked` is explicit. Passing model validation establishes structural integrity, not semantic truth. Preparation must decide which semantically unresolved extractions to exclude and record as gaps; the online layer must not present extraction confidence as medical certainty.

## Derived values and contradictions

Derived facts are separate from source facts and reference source-fact inputs (no derived chains in v1). Calculation code must verify formula, unit conversion, date selection and rounding. The schema does not certify arithmetic.

Contradictions may reference source and derived facts; their evidence must include all underlying claim evidence. Status is candidate, accepted or rejected. The online layer normally displays accepted contradictions only. Count a real disagreement once even if copied across several documents. Different dates, sides or events do not by themselves establish a contradiction.

### Implemented bounded detector

`backend/evidence/contradictions.py` emits a `ContradictionReport` described by `contracts/contradiction-report.schema.json`. It retains source version/hash, generated BMI values, status-labelled contradictions, each rule's assumptions, and diagnostics for skipped comparisons. `report.validate_against(source_bundle)` rejects stale or edited reports by recomputing the deterministic rules. Changing a candidate's status by editing JSON is not a supported review workflow.

- **BMI:** compare height, weight and recorded BMI only within one cited paragraph/table block, with compatible time metadata, no conflicting established event IDs and one distinct value per field. Require labelled source values with supported explicit units. Calculate kg/m², preserve the recorded BMI, and account for displayed rounding precision. Accept an arithmetic documentation inconsistency only when the intervals remain separated by more than `max(0.5 kg/m², 3% of calculated BMI)`. This margin is a conservative engineering rule, not a clinical threshold. Historical/approximate wording, multiple dates, zero inputs, unsupported units and ambiguous measurements are skipped with diagnostics. Exact copied blocks with matching time metadata count once and retain all citations; this can undercount coincidentally identical independent blocks.
- **Event dates:** accept conflicting explicit day dates only for affirmed completed events sharing an established `event_id` and concept. Upstream event identity must be trustworthy; source-span IDs created by extraction are explicitly excluded. Same-document admission/discharge differences without that identity are review candidates. Separate encounters, plans, fallback dates and malformed dates are not accepted contradictions.
- **Laterality:** a matching anatomical measurement with differing source-linked sides in a finding versus a summary can become a review candidate. Different explicit dates/events, ambiguous sides and non-summary bilateral findings are excluded. Opposite sides alone never establish a contradiction.

`display_contradictions(source_bundle, report)` returns accepted entries only. An optional `attach_report(source_bundle, report)` creates a new validated evidence version with generated values and all status-labelled contradictions while preserving original facts/documents and existing gaps. Consumers of the enriched bundle must still filter `status == "accepted"`; candidate findings belong in a separate review workflow. Source claims resolve in `bundle.facts`; calculated claims resolve in the report's or enriched bundle's `derived_facts`, whose input IDs resolve back to source facts. No source value is silently corrected.

The detector does not establish complete contradiction recall, perform general semantic adjudication, compare medication changes, infer same-event identity across documents, or promote candidates using an LLM. Invalid source dates remain extraction/data-quality gaps, not counted clinical contradictions. An accepted rule result records satisfaction of the stated rule assumptions, not independent clinician review.

## Completeness and failure

`manifest.status=complete` means processing finished without recorded unresolved failures; it does not claim perfect recall or complete clinical documentation. Any unresolved processing gaps require `partial`.

There is deliberately no `not_documented` fact type. Query-specific absence is an online coverage conclusion after a successful search of the relevant full record. A gap or excluded extraction is not evidence of absence. Sparse facts in a category are not evidence that the category was exhaustively searched.

## Integration boundary

First integration should use this example bundle with no model calls. Target preparation interface (to implement next):

```text
prepare_patient(source_directory, config) -> EvidenceBundle
extract_passages(documents, passages, requested_concepts, config)
  -> {facts, processing_gaps}
```

Fallback extraction uses the same Fact and ProcessingGap models, quote validator and normalization version as batch preparation. Returned facts remain request-local initially. The caller merges into a temporary bundle to run relational validation; a partial result must carry gaps. Persisting new facts requires a new evidence version.

No patient answer, guideline priority, RIDX score, summary or UI layout belongs in this bundle. `cases/expected.json` is evaluation-only. Imported IBM concepts cannot override source text. Patient metadata, if included, is explicitly marked `source_kind=patient_metadata` and is not valid evidence for document-to-document contradiction scoring.

## Versioning and future additions

### Category policy and conservative reconciliation

Recommended or planned investigations/interventions belong to `care_plans`. Performed or explicitly not-performed investigations belong to `procedures`, with the original assertion and status preserved; the category alone never proves completion. Follow-up reviews remain `followups` and admission/discharge events remain `encounters`. Prompt v5 applies this policy to new extractions. Existing source facts remain unchanged; the reconciliation index records presentation category changes explicitly.

`contracts/reconciliation-index.schema.json` defines a separate presentation index. Each group records a representative source fact, every member source-fact ID, and a presentation category. All source facts, citations, validation records, related links, derived inputs and contradiction references remain in the original bundle. A representative is a display choice, not a declaration that a rule is more clinically reliable than a model.

Grouping requires identical structured values, assertion, status, subject, full clinical time, related-fact links and exact evidence locations (including heading context), plus the same concept or an explicit canonical alias. Citation ordering does not matter. Different source locations, dates, laterality, units or methods remain separate. A missing event ID may join one known event ID only when all other checks agree; multiple distinct known event IDs disable grouping for that bucket. There is no cross-document, fuzzy text or approximate-value deduplication.

Call `reconcile_bundle(bundle)` and persist its index, then `presentation_facts(bundle, index)` for display/ranking copies. This returns a list, not a replacement bundle: resolve all source references through the original bundle and expose each group's `source_fact_ids` for audit. Never overwrite the original bundle or discard the nonrepresentative records. The index validates its source version/hash and recomputed groups before use. It can coexist with the normalization index by joining source-fact IDs. Disagreements remain separate; reconciliation does not adjudicate contradictions or repair dates.

### Optional normalization index

`contracts/normalization-index.schema.json` describes a separate index with one entry per source fact. `contracts/concept-aliases.json` publishes the explicit alias vocabulary. This is a local concept vocabulary, not FHIR or a standard clinical coding system. Unmapped concepts remain null; original concepts and facts are preserved. Mapped concepts do not establish duplicate identity.

Each entry includes the original concept, optional canonical concept and mapping rule, reported laterality, normalized laterality, status, and exact evidence spans. Laterality requires an anatomical site or a recognized anatomical concept. Contextual annotations may expand backward within the cited passage; ambiguous sides remain unspecified. These lexical checks do not establish that a side applies clinically to the extracted claim. `conflict` means disagreement with the original extracted side, not an established clinical contradiction.

The index records the source evidence version and bundle content hash. Call `NormalizationIndex.validate_against(bundle)` before consuming it to reject stale or modified mappings. Indexing does not merge facts, resolve contradictions, modify source quotes, or call a model.

Unknown fields are rejected to catch integration drift. Additive schema changes require version coordination; breaking changes require a major version. Preserve the current frontend contract through an adapter rather than making the extractor emit frontend blocks. API/provider adapter ownership remains with the online developer; this module has no provider dependency.
